"""Encrypted outbox and bounded delivery for workforce identity recovery."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import smtplib
import ssl
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from urllib.parse import urlencode

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.interfaces.identity_notification_provider import (
    IdentityNotificationDelivery,
    IdentityNotificationDeliveryDisabled,
    IdentityNotificationProvider,
    IdentityNotificationProviderError,
    IdentityRecoveryNotification,
)
from app.core.config.settings import Settings, get_settings
from app.core.security.identity_security import IdentitySecurityError, hash_identity_value
from app.infrastructure.database.models import (
    IdentityActionTokenModel,
    IdentityNotificationOutboxModel,
    UserModel,
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.observability.metrics import metrics
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository


def _secret_text(value: object) -> str:
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        return str(getter())
    return str(value)


def _notification_fernet(secret: str, key_id: str) -> Fernet:
    purpose = (
        b"identity:notification-encryption:legacy-v1"
        if key_id == "legacy-v1"
        else b"identity:notification-encryption:v2"
    )
    derived = hmac.new(secret.encode("utf-8"), purpose, hashlib.sha256).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


class IdentityNotificationCipher:
    """Bounded keyring for sensitive outbox recipient and recovery URL data."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self.active_key_id = self._settings.identity_notification_encryption_key_id
        configured = self._settings.identity_notification_encryption_key
        active_secret = (
            _secret_text(configured) if configured is not None else self._settings.app_secret_key
        )
        self._keys = {self.active_key_id: _notification_fernet(active_secret, self.active_key_id)}
        self._keys.update(
            {
                key_id: _notification_fernet(_secret_text(secret), key_id)
                for key_id, secret in self._settings.identity_notification_decryption_keys.items()
            }
        )

    def encrypt(self, value: bytes) -> bytes:
        return self._keys[self.active_key_id].encrypt(value)

    def decrypt(self, value: bytes, *, key_id: str) -> bytes:
        key = self._keys.get(key_id)
        if key is None:
            raise IdentitySecurityError("Identity notification key is unavailable")
        try:
            return key.decrypt(value)
        except InvalidToken:
            raise IdentitySecurityError("Identity notification could not be decrypted") from None


@dataclass(frozen=True, slots=True)
class ClaimedIdentityNotification:
    id: uuid.UUID
    agency_id: uuid.UUID | None
    user_id: uuid.UUID | None
    action_token_id: uuid.UUID | None
    purpose: str
    recipient_ciphertext: bytes
    payload_ciphertext: bytes
    encryption_key_id: str
    dedupe_key: str
    attempt_count: int
    max_attempts: int


class DevelopmentIdentityNotificationProvider:
    """Deterministic local adapter; it never logs or returns the raw URL."""

    async def deliver(
        self,
        notification: IdentityRecoveryNotification,
    ) -> IdentityNotificationDelivery:
        return IdentityNotificationDelivery(
            provider_message_id=f"development-{notification.idempotency_key}"
        )


class SMTPIdentityNotificationProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def deliver(
        self,
        notification: IdentityRecoveryNotification,
    ) -> IdentityNotificationDelivery:
        return await asyncio.wait_for(
            asyncio.to_thread(self._deliver_sync, notification),
            timeout=self._settings.password_recovery_delivery_timeout_seconds,
        )

    def _deliver_sync(
        self,
        notification: IdentityRecoveryNotification,
    ) -> IdentityNotificationDelivery:
        host = (self._settings.password_recovery_smtp_host or "").strip()
        sender = (self._settings.password_recovery_smtp_sender or "").strip()
        if not host or not sender:
            raise IdentityNotificationProviderError("SMTP recovery delivery is not configured")
        message = EmailMessage()
        message["From"] = sender
        message["To"] = notification.recipient
        message["Subject"] = "Reset your Global Connect password"
        sender_domain = sender.rpartition("@")[2].strip().lower()
        if not sender_domain or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for character in sender_domain
        ):
            raise IdentityNotificationProviderError("SMTP recovery sender is invalid")
        # A stable Message-ID gives SMTP relays and recipients a deterministic
        # deduplication key if a worker dies after the external send but before
        # the local outbox completion commits.
        message_id = f"<identity-recovery-{notification.idempotency_key}@{sender_domain}>"
        message["Message-ID"] = message_id
        message.set_content(
            "A password reset was requested for your account.\n\n"
            f"Open this one-time link: {notification.recovery_url}\n\n"
            f"It expires at {notification.expires_at.astimezone(UTC).isoformat()}. "
            "If you did not request this, you can ignore this message."
        )
        try:
            with smtplib.SMTP(
                host,
                self._settings.password_recovery_smtp_port,
                timeout=self._settings.password_recovery_delivery_timeout_seconds,
            ) as client:
                client.ehlo()
                if self._settings.password_recovery_smtp_starttls:
                    client.starttls(context=ssl.create_default_context())
                    client.ehlo()
                username = (self._settings.password_recovery_smtp_username or "").strip()
                password = self._settings.password_recovery_smtp_password
                if username and password is not None:
                    client.login(username, password.get_secret_value())
                client.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            raise IdentityNotificationProviderError("SMTP recovery delivery failed") from exc
        return IdentityNotificationDelivery(provider_message_id=message_id)


def identity_notification_provider(
    settings: Settings | None = None,
) -> IdentityNotificationProvider:
    active = settings or get_settings()
    provider = active.password_recovery_delivery_provider
    if provider == "development" and active.is_development:
        return DevelopmentIdentityNotificationProvider()
    if provider == "smtp":
        return SMTPIdentityNotificationProvider(active)
    raise IdentityNotificationDeliveryDisabled("Recovery delivery is disabled")


def stage_password_recovery_notification(
    session: AsyncSession,
    *,
    user: UserModel,
    action_token: IdentityActionTokenModel,
    raw_token: str,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> IdentityNotificationOutboxModel:
    """Stage the only recoverable copy of the raw token in the caller's transaction."""

    active = settings or get_settings()
    active_now = now or datetime.now(tz=UTC)
    cipher = IdentityNotificationCipher(active)
    query = urlencode({"token": raw_token})
    recovery_url = f"{active.password_recovery_frontend_url}?{query}"
    payload = json.dumps(
        {
            "purpose": "password_recovery",
            "recovery_url": recovery_url,
            "expires_at": action_token.expires_at.astimezone(UTC).isoformat(),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    row = IdentityNotificationOutboxModel(
        id=uuid.uuid4(),
        agency_id=user.agency_id,
        user_id=user.id,
        action_token_id=action_token.id,
        purpose="password_recovery",
        channel="email",
        recipient_ciphertext=cipher.encrypt(user.email.encode("utf-8")),
        payload_ciphertext=cipher.encrypt(payload),
        encryption_key_id=cipher.active_key_id,
        dedupe_key=hash_identity_value(
            str(action_token.id), purpose="identity-notification-dedupe"
        ),
        status="pending",
        attempt_count=0,
        max_attempts=active.password_recovery_delivery_max_attempts,
        next_attempt_at=active_now,
        created_at=active_now,
        updated_at=active_now,
    )
    session.add(row)
    return row


async def _claim_due_notifications(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    now: datetime,
) -> list[ClaimedIdentityNotification]:
    async with session_factory() as session:
        async with session.begin():
            rows = (
                (
                    await session.execute(
                        select(IdentityNotificationOutboxModel)
                        .where(
                            IdentityNotificationOutboxModel.next_attempt_at <= now,
                            or_(
                                IdentityNotificationOutboxModel.status == "pending",
                                (IdentityNotificationOutboxModel.status == "running")
                                & (IdentityNotificationOutboxModel.lease_expires_at <= now),
                            ),
                        )
                        .order_by(
                            IdentityNotificationOutboxModel.next_attempt_at,
                            IdentityNotificationOutboxModel.created_at,
                            IdentityNotificationOutboxModel.id,
                        )
                        .limit(settings.password_recovery_delivery_batch_size)
                        .with_for_update(skip_locked=True)
                    )
                )
                .scalars()
                .all()
            )
            claimed: list[ClaimedIdentityNotification] = []
            for row in rows:
                if row.attempt_count >= row.max_attempts:
                    # A worker may die after claiming its final allowed attempt.
                    # Reclaiming must not violate the database attempt bound or
                    # create an unbounded extra provider call.
                    row.status = "dead_letter"
                    row.lease_expires_at = None
                    row.last_error_code = "delivery_lease_exhausted"
                    row.updated_at = now
                    await AuditLogRepository(session).record(
                        action="auth.password_recovery_delivery_failed",
                        entity_type="identity_notification",
                        agency_id=row.agency_id,
                        user_id=row.user_id,
                        entity_id=str(row.id),
                        result="failed",
                        metadata={
                            "attempt_count": row.attempt_count,
                            "terminal": True,
                            "error_code": row.last_error_code,
                        },
                    )
                    metrics.increment("identity.recovery_delivery.dead_letter")
                    continue
                row.status = "running"
                row.attempt_count += 1
                row.lease_expires_at = now + timedelta(
                    seconds=max(60.0, settings.password_recovery_delivery_timeout_seconds * 3)
                )
                row.updated_at = now
                claimed.append(
                    ClaimedIdentityNotification(
                        id=row.id,
                        agency_id=row.agency_id,
                        user_id=row.user_id,
                        action_token_id=row.action_token_id,
                        purpose=row.purpose,
                        recipient_ciphertext=row.recipient_ciphertext,
                        payload_ciphertext=row.payload_ciphertext,
                        encryption_key_id=row.encryption_key_id,
                        dedupe_key=row.dedupe_key,
                        attempt_count=row.attempt_count,
                        max_attempts=row.max_attempts,
                    )
                )
            return claimed


def _decode_notification(
    claim: ClaimedIdentityNotification,
    *,
    cipher: IdentityNotificationCipher,
) -> IdentityRecoveryNotification:
    recipient = cipher.decrypt(claim.recipient_ciphertext, key_id=claim.encryption_key_id).decode(
        "utf-8"
    )
    payload_value = json.loads(
        cipher.decrypt(claim.payload_ciphertext, key_id=claim.encryption_key_id)
    )
    if not isinstance(payload_value, dict):
        raise IdentitySecurityError("Identity notification payload is invalid")
    recovery_url = payload_value.get("recovery_url")
    expires_at_value = payload_value.get("expires_at")
    purpose = payload_value.get("purpose")
    if not isinstance(recovery_url, str) or not recovery_url:
        raise IdentitySecurityError("Identity notification payload is invalid")
    if not isinstance(expires_at_value, str) or not expires_at_value:
        raise IdentitySecurityError("Identity notification payload is invalid")
    if not isinstance(purpose, str) or not purpose:
        raise IdentitySecurityError("Identity notification payload is invalid")
    if purpose != claim.purpose or purpose != "password_recovery":
        raise IdentitySecurityError("Identity notification purpose is invalid")
    expires_at = datetime.fromisoformat(expires_at_value)
    if expires_at.tzinfo is None:
        raise IdentitySecurityError("Identity notification expiry is invalid")
    return IdentityRecoveryNotification(
        recipient=recipient,
        purpose=purpose,
        recovery_url=recovery_url,
        expires_at=expires_at.astimezone(UTC),
        idempotency_key=claim.dedupe_key,
    )


async def _action_token_is_deliverable(
    claim: ClaimedIdentityNotification,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    now: datetime,
) -> bool:
    if claim.action_token_id is None:
        return False
    async with session_factory() as session:
        token_id = (
            await session.execute(
                select(IdentityActionTokenModel.id).where(
                    IdentityActionTokenModel.id == claim.action_token_id,
                    IdentityActionTokenModel.purpose == "password_recovery",
                    IdentityActionTokenModel.expires_at > now,
                    IdentityActionTokenModel.consumed_at.is_(None),
                    IdentityActionTokenModel.invalidated_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        return token_id is not None


async def _complete_delivery(
    claim: ClaimedIdentityNotification,
    *,
    provider_message_id: str,
    session_factory: async_sessionmaker[AsyncSession],
    now: datetime,
) -> bool:
    async with session_factory() as session:
        async with session.begin():
            row = (
                await session.execute(
                    select(IdentityNotificationOutboxModel)
                    .where(IdentityNotificationOutboxModel.id == claim.id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row is None or row.status != "running" or row.attempt_count != claim.attempt_count:
                return False
            row.status = "delivered"
            row.delivered_at = now
            row.lease_expires_at = None
            row.provider_message_id_hash = hashlib.sha256(
                provider_message_id.encode("utf-8")
            ).hexdigest()
            row.last_error_code = None
            row.updated_at = now
            await AuditLogRepository(session).record(
                action="auth.password_recovery_delivered",
                entity_type="identity_notification",
                agency_id=claim.agency_id,
                user_id=claim.user_id,
                entity_id=str(claim.id),
                metadata={"attempt_count": claim.attempt_count, "channel": "email"},
            )
            return True


async def _defer_delivery(
    claim: ClaimedIdentityNotification,
    *,
    error_code: str,
    session_factory: async_sessionmaker[AsyncSession],
    now: datetime,
    force_terminal: bool = False,
) -> bool:
    async with session_factory() as session:
        async with session.begin():
            row = (
                await session.execute(
                    select(IdentityNotificationOutboxModel)
                    .where(IdentityNotificationOutboxModel.id == claim.id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row is None or row.status != "running" or row.attempt_count != claim.attempt_count:
                return False
            terminal = force_terminal or row.attempt_count >= row.max_attempts
            row.status = "dead_letter" if terminal else "pending"
            row.lease_expires_at = None
            row.last_error_code = error_code[:80]
            row.next_attempt_at = now + timedelta(
                seconds=min(3_600, 30 * (2 ** max(0, row.attempt_count - 1)))
            )
            row.updated_at = now
            await AuditLogRepository(session).record(
                action=(
                    "auth.password_recovery_delivery_failed"
                    if terminal
                    else "auth.password_recovery_delivery_deferred"
                ),
                entity_type="identity_notification",
                agency_id=claim.agency_id,
                user_id=claim.user_id,
                entity_id=str(claim.id),
                result="failed" if terminal else "blocked",
                metadata={
                    "attempt_count": row.attempt_count,
                    "terminal": terminal,
                    "error_code": row.last_error_code,
                },
            )
            return terminal


async def deliver_due_identity_notifications(
    *,
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionFactory,
    provider: IdentityNotificationProvider | None = None,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> int:
    """Deliver one lease-safe page; return the number successfully delivered."""

    active = settings or get_settings()
    active_now = now or datetime.now(tz=UTC)
    try:
        delivery_provider = provider or identity_notification_provider(active)
    except IdentityNotificationDeliveryDisabled:
        metrics.increment("identity.recovery_delivery.disabled")
        return 0
    claims = await _claim_due_notifications(
        session_factory=session_factory,
        settings=active,
        now=active_now,
    )
    cipher = IdentityNotificationCipher(active)
    delivered = 0
    for claim in claims:
        if not await _action_token_is_deliverable(
            claim,
            session_factory=session_factory,
            now=active_now,
        ):
            await _defer_delivery(
                claim,
                error_code="action_token_inactive",
                session_factory=session_factory,
                now=active_now,
                force_terminal=True,
            )
            metrics.increment("identity.recovery_delivery.dead_letter")
            continue
        try:
            notification = _decode_notification(claim, cipher=cipher)
            if notification.expires_at <= active_now:
                await _defer_delivery(
                    claim,
                    error_code="recovery_token_expired",
                    session_factory=session_factory,
                    now=active_now,
                    force_terminal=True,
                )
                metrics.increment("identity.recovery_delivery.dead_letter")
                continue
            result = await delivery_provider.deliver(notification)
            if (
                not isinstance(result.provider_message_id, str)
                or not result.provider_message_id
                or len(result.provider_message_id) > 4_096
            ):
                raise IdentityNotificationProviderError("invalid_provider_message_id")
        except (
            IdentityNotificationProviderError,
            IdentitySecurityError,
            TimeoutError,
            ValueError,
            TypeError,
        ) as exc:
            error_code = type(exc).__name__.lower()
            terminal = await _defer_delivery(
                claim,
                error_code=error_code,
                session_factory=session_factory,
                now=active_now,
            )
            metrics.increment(
                "identity.recovery_delivery.dead_letter"
                if terminal
                else "identity.recovery_delivery.retry"
            )
            continue
        completed = await _complete_delivery(
            claim,
            provider_message_id=result.provider_message_id,
            session_factory=session_factory,
            now=active_now,
        )
        if completed:
            metrics.increment("identity.recovery_delivery.delivered")
            delivered += 1
    return delivered


__all__ = [
    "DevelopmentIdentityNotificationProvider",
    "IdentityNotificationCipher",
    "SMTPIdentityNotificationProvider",
    "deliver_due_identity_notifications",
    "identity_notification_provider",
    "stage_password_recovery_notification",
]
