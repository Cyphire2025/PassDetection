from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.interfaces.identity_notification_provider import (
    IdentityNotificationDelivery,
    IdentityNotificationDeliveryDisabled,
    IdentityNotificationProviderError,
    IdentityRecoveryNotification,
)
from app.core.config.settings import Settings
from app.core.security.password import hash_password
from app.infrastructure.database.models import (
    IdentityActionTokenModel,
    IdentityNotificationOutboxModel,
    UserModel,
)
from app.infrastructure.security.identity_notifications import (
    DevelopmentIdentityNotificationProvider,
    deliver_due_identity_notifications,
    identity_notification_provider,
    stage_password_recovery_notification,
)


class CapturingProvider:
    def __init__(self) -> None:
        self.notifications: list[IdentityRecoveryNotification] = []

    async def deliver(
        self,
        notification: IdentityRecoveryNotification,
    ) -> IdentityNotificationDelivery:
        self.notifications.append(notification)
        return IdentityNotificationDelivery(provider_message_id="provider-message-1")


class FailingProvider:
    async def deliver(
        self,
        notification: IdentityRecoveryNotification,
    ) -> IdentityNotificationDelivery:
        raise IdentityNotificationProviderError("bounded_test_failure")


class TimingOutProvider:
    async def deliver(
        self,
        notification: IdentityRecoveryNotification,
    ) -> IdentityNotificationDelivery:
        raise TimeoutError("bounded test timeout")


@pytest.mark.asyncio
async def test_development_provider_is_deterministic_without_returning_raw_url() -> None:
    notification = IdentityRecoveryNotification(
        recipient="development-recovery@example.com",
        purpose="password_recovery",
        recovery_url="http://localhost:3000/auth/recover?token=raw-secret-value",
        expires_at=datetime(2026, 8, 23, 9, 0, tzinfo=UTC),
        idempotency_key="a" * 64,
    )
    provider = DevelopmentIdentityNotificationProvider()

    first = await provider.deliver(notification)
    second = await provider.deliver(notification)

    assert first == second
    assert first.provider_message_id == f"development-{'a' * 64}"
    assert "raw-secret-value" not in first.provider_message_id


def test_development_delivery_adapter_fails_closed_outside_development(
    test_settings: Settings,
) -> None:
    production_like = test_settings.model_copy(update={"app_env": "production"})

    with pytest.raises(IdentityNotificationDeliveryDisabled):
        identity_notification_provider(production_like)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def _stage_recovery(
    session: AsyncSession,
    *,
    settings: Settings,
    now: datetime,
) -> tuple[UserModel, IdentityNotificationOutboxModel, str]:
    user = UserModel(
        email="recovery-delivery@example.test",
        hashed_password=hash_password("ExistingPassword9"),
        full_name="Recovery Delivery",
        role="agency_staff",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    raw_token = "raw-recovery-token-that-must-stay-encrypted"
    action_token = IdentityActionTokenModel(
        id=uuid.uuid4(),
        user_id=user.id,
        purpose="password_recovery",
        token_key_id="legacy-v1",
        token_hash="a" * 64,
        expires_at=now + timedelta(minutes=20),
        created_at=now,
    )
    session.add(action_token)
    await session.flush()
    outbox = stage_password_recovery_notification(
        session,
        user=user,
        action_token=action_token,
        raw_token=raw_token,
        settings=settings,
        now=now,
    )
    await session.commit()
    return user, outbox, raw_token


@pytest.mark.asyncio
async def test_recovery_notification_is_encrypted_and_delivered_from_durable_outbox(
    db_session: AsyncSession,
    test_settings: Settings,
) -> None:
    now = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)
    _, outbox, raw_token = await _stage_recovery(
        db_session,
        settings=test_settings,
        now=now,
    )
    outbox_id = outbox.id
    assert raw_token.encode() not in outbox.payload_ciphertext
    assert b"recovery-delivery@example.test" not in outbox.recipient_ciphertext

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    provider = CapturingProvider()
    delivered = await deliver_due_identity_notifications(
        session_factory=factory,
        provider=provider,
        settings=test_settings,
        now=now,
    )

    assert delivered == 1
    assert len(provider.notifications) == 1
    assert raw_token in provider.notifications[0].recovery_url
    assert provider.notifications[0].idempotency_key == outbox.dedupe_key
    db_session.expire_all()
    stored = (
        await db_session.execute(
            select(IdentityNotificationOutboxModel).where(
                IdentityNotificationOutboxModel.id == outbox_id
            )
        )
    ).scalar_one()
    assert stored.status == "delivered"
    assert stored.delivered_at is not None
    assert _as_utc(stored.delivered_at) == now
    assert stored.provider_message_id_hash is not None


@pytest.mark.asyncio
async def test_recovery_delivery_retries_with_backoff_then_dead_letters(
    db_session: AsyncSession,
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(update={"password_recovery_delivery_max_attempts": 2})
    now = datetime(2026, 8, 23, 11, 0, tzinfo=UTC)
    _, outbox, _ = await _stage_recovery(db_session, settings=settings, now=now)
    outbox_id = outbox.id
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    assert (
        await deliver_due_identity_notifications(
            session_factory=factory,
            provider=FailingProvider(),
            settings=settings,
            now=now,
        )
        == 0
    )
    db_session.expire_all()
    pending = await db_session.get(IdentityNotificationOutboxModel, outbox_id)
    assert pending is not None
    assert pending.status == "pending"
    assert pending.attempt_count == 1
    assert _as_utc(pending.next_attempt_at) == now + timedelta(seconds=30)

    assert (
        await deliver_due_identity_notifications(
            session_factory=factory,
            provider=FailingProvider(),
            settings=settings,
            now=now + timedelta(seconds=30),
        )
        == 0
    )
    db_session.expire_all()
    terminal = await db_session.get(IdentityNotificationOutboxModel, outbox_id)
    assert terminal is not None
    assert terminal.status == "dead_letter"
    assert terminal.attempt_count == 2
    assert terminal.last_error_code == "identitynotificationprovidererror"


@pytest.mark.asyncio
async def test_recovery_delivery_timeout_is_deferred_without_losing_outbox(
    db_session: AsyncSession,
    test_settings: Settings,
) -> None:
    now = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
    _, outbox, _ = await _stage_recovery(db_session, settings=test_settings, now=now)
    outbox_id = outbox.id
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    assert (
        await deliver_due_identity_notifications(
            session_factory=factory,
            provider=TimingOutProvider(),
            settings=test_settings,
            now=now,
        )
        == 0
    )

    db_session.expire_all()
    pending = await db_session.get(IdentityNotificationOutboxModel, outbox_id)
    assert pending is not None
    assert pending.status == "pending"
    assert pending.attempt_count == 1
    assert pending.last_error_code == "timeouterror"


@pytest.mark.asyncio
async def test_inactive_action_token_is_never_delivered_and_is_terminal(
    db_session: AsyncSession,
    test_settings: Settings,
) -> None:
    now = datetime(2026, 8, 23, 13, 0, tzinfo=UTC)
    _, outbox, _ = await _stage_recovery(db_session, settings=test_settings, now=now)
    outbox_id = outbox.id
    assert outbox.action_token_id is not None
    action_token = await db_session.get(IdentityActionTokenModel, outbox.action_token_id)
    assert action_token is not None
    action_token.invalidated_at = now
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    provider = CapturingProvider()

    assert (
        await deliver_due_identity_notifications(
            session_factory=factory,
            provider=provider,
            settings=test_settings,
            now=now,
        )
        == 0
    )

    assert provider.notifications == []
    db_session.expire_all()
    terminal = await db_session.get(IdentityNotificationOutboxModel, outbox_id)
    assert terminal is not None
    assert terminal.status == "dead_letter"
    assert terminal.last_error_code == "action_token_inactive"


@pytest.mark.asyncio
async def test_expired_final_delivery_lease_dead_letters_without_extra_attempt(
    db_session: AsyncSession,
    test_settings: Settings,
) -> None:
    settings = test_settings.model_copy(update={"password_recovery_delivery_max_attempts": 2})
    now = datetime(2026, 8, 23, 14, 0, tzinfo=UTC)
    _, outbox, _ = await _stage_recovery(db_session, settings=settings, now=now)
    outbox_id = outbox.id
    outbox.status = "running"
    outbox.attempt_count = 2
    outbox.lease_expires_at = now - timedelta(seconds=1)
    outbox.next_attempt_at = now - timedelta(seconds=1)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    provider = CapturingProvider()

    assert (
        await deliver_due_identity_notifications(
            session_factory=factory,
            provider=provider,
            settings=settings,
            now=now,
        )
        == 0
    )

    assert provider.notifications == []
    db_session.expire_all()
    terminal = await db_session.get(IdentityNotificationOutboxModel, outbox_id)
    assert terminal is not None
    assert terminal.status == "dead_letter"
    assert terminal.attempt_count == 2
    assert terminal.last_error_code == "delivery_lease_exhausted"


@pytest.mark.asyncio
async def test_notification_key_rotation_delivers_old_outbox_with_previous_key(
    db_session: AsyncSession,
    test_settings: Settings,
) -> None:
    now = datetime(2026, 8, 23, 15, 0, tzinfo=UTC)
    _, _, raw_token = await _stage_recovery(db_session, settings=test_settings, now=now)
    rotated = test_settings.model_copy(
        update={
            "identity_notification_encryption_key_id": "notify-2026-08",
            "identity_notification_encryption_key": SecretStr(
                "new-notification-encryption-material-2026-08"
            ),
            "identity_notification_decryption_keys": {
                "legacy-v1": SecretStr(test_settings.app_secret_key)
            },
        }
    )
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    provider = CapturingProvider()

    assert (
        await deliver_due_identity_notifications(
            session_factory=factory,
            provider=provider,
            settings=rotated,
            now=now,
        )
        == 1
    )
    assert raw_token in provider.notifications[0].recovery_url
