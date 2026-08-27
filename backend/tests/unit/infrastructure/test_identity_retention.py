from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.settings import Settings
from app.infrastructure.database.models import (
    AgencyModel,
    DashboardAuthChallengeModel,
    IdentityActionTokenModel,
    IdentityNotificationOutboxModel,
    MFARecoveryCodeModel,
    UserModel,
)
from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository
from app.infrastructure.security.identity_retention import apply_identity_retention


async def _user(
    session: AsyncSession,
    *,
    email: str,
    agency_id: uuid.UUID | None = None,
) -> UserModel:
    row = UserModel(
        email=email,
        hashed_password="unusable-test-placeholder",
        full_name="Identity Retention User",
        role="agency_staff",
        agency_id=agency_id,
        is_active=True,
    )
    session.add(row)
    await session.flush()
    return row


def _token(
    *,
    user_id: uuid.UUID,
    token_hash: str,
    created_at: datetime,
    expires_at: datetime,
    consumed_at: datetime | None = None,
    invalidated_at: datetime | None = None,
) -> IdentityActionTokenModel:
    return IdentityActionTokenModel(
        id=uuid.uuid4(),
        user_id=user_id,
        purpose="password_recovery",
        token_key_id="legacy-v1",
        token_hash=token_hash,
        created_at=created_at,
        expires_at=expires_at,
        consumed_at=consumed_at,
        invalidated_at=invalidated_at,
    )


def _outbox(
    *,
    status: str,
    created_at: datetime,
    updated_at: datetime,
) -> IdentityNotificationOutboxModel:
    return IdentityNotificationOutboxModel(
        id=uuid.uuid4(),
        purpose="password_recovery",
        channel="email",
        recipient_ciphertext=b"encrypted-recipient",
        payload_ciphertext=b"encrypted-payload",
        encryption_key_id="legacy-v1",
        dedupe_key=uuid.uuid4().hex * 2,
        status=status,
        attempt_count=1,
        max_attempts=5,
        next_attempt_at=created_at,
        created_at=created_at,
        updated_at=updated_at,
    )


@pytest.mark.asyncio
async def test_retention_honors_exact_time_boundaries_and_preserves_active_rows(
    db_session: AsyncSession,
    test_settings: Settings,
) -> None:
    now = datetime(2026, 8, 23, 16, 0, tzinfo=UTC)
    general_cutoff = now - timedelta(days=test_settings.identity_token_retention_days)
    consumed_cutoff = now - timedelta(days=test_settings.identity_consumed_token_retention_days)
    challenge_cutoff = now - timedelta(days=test_settings.identity_challenge_retention_days)
    users = [await _user(db_session, email=f"retention-{index}@example.com") for index in range(8)]
    stale_expired = _token(
        user_id=users[0].id,
        token_hash="0" * 64,
        created_at=general_cutoff - timedelta(days=1),
        expires_at=general_cutoff,
    )
    just_inside_retention = _token(
        user_id=users[1].id,
        token_hash="1" * 64,
        created_at=general_cutoff - timedelta(days=1),
        expires_at=general_cutoff + timedelta(microseconds=1),
    )
    active_future = _token(
        user_id=users[2].id,
        token_hash="2" * 64,
        created_at=general_cutoff - timedelta(days=1),
        expires_at=now + timedelta(minutes=20),
    )
    consumed_at_cutoff = _token(
        user_id=users[3].id,
        token_hash="3" * 64,
        created_at=general_cutoff - timedelta(days=1),
        expires_at=now + timedelta(minutes=20),
        consumed_at=consumed_cutoff,
    )
    consumed_after_cutoff = _token(
        user_id=users[4].id,
        token_hash="4" * 64,
        created_at=general_cutoff - timedelta(days=1),
        expires_at=now + timedelta(minutes=20),
        consumed_at=consumed_cutoff + timedelta(microseconds=1),
    )
    terminal_challenge = DashboardAuthChallengeModel(
        id=uuid.uuid4(),
        user_id=users[5].id,
        purpose="mfa_login",
        challenge_token_hash="5" * 64,
        status="cancelled",
        attempt_count=0,
        max_attempts=5,
        expires_at=challenge_cutoff + timedelta(minutes=5),
        created_at=challenge_cutoff,
        updated_at=challenge_cutoff,
    )
    fresh_terminal_challenge = DashboardAuthChallengeModel(
        id=uuid.uuid4(),
        user_id=users[6].id,
        purpose="mfa_login",
        challenge_token_hash="6" * 64,
        status="cancelled",
        attempt_count=0,
        max_attempts=5,
        expires_at=challenge_cutoff + timedelta(minutes=5, microseconds=1),
        created_at=challenge_cutoff + timedelta(microseconds=1),
        updated_at=challenge_cutoff + timedelta(microseconds=1),
    )
    consumed_code = MFARecoveryCodeModel(
        id=uuid.uuid4(),
        user_id=users[7].id,
        code_hash="7" * 64,
        consumed_at=consumed_cutoff,
        created_at=general_cutoff,
    )
    stale_outbox = _outbox(
        status="delivered",
        created_at=general_cutoff - timedelta(days=1),
        updated_at=general_cutoff,
    )
    orphaned_pending_outbox = _outbox(
        status="pending",
        created_at=general_cutoff,
        updated_at=general_cutoff,
    )
    fresh_orphaned_outbox = _outbox(
        status="pending",
        created_at=general_cutoff + timedelta(microseconds=1),
        updated_at=general_cutoff + timedelta(microseconds=1),
    )
    db_session.add_all(
        [
            stale_expired,
            just_inside_retention,
            active_future,
            consumed_at_cutoff,
            consumed_after_cutoff,
            terminal_challenge,
            fresh_terminal_challenge,
            consumed_code,
            stale_outbox,
            orphaned_pending_outbox,
            fresh_orphaned_outbox,
        ]
    )
    row_ids = {
        "stale_expired": stale_expired.id,
        "consumed_at_cutoff": consumed_at_cutoff.id,
        "just_inside_retention": just_inside_retention.id,
        "active_future": active_future.id,
        "consumed_after_cutoff": consumed_after_cutoff.id,
        "terminal_challenge": terminal_challenge.id,
        "fresh_terminal_challenge": fresh_terminal_challenge.id,
        "consumed_code": consumed_code.id,
        "stale_outbox": stale_outbox.id,
        "orphaned_pending_outbox": orphaned_pending_outbox.id,
        "fresh_orphaned_outbox": fresh_orphaned_outbox.id,
    }
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    result = await apply_identity_retention(
        session_factory=factory,
        settings=test_settings,
        now=now,
    )

    assert result.action_tokens == 2
    assert result.auth_challenges == 1
    assert result.recovery_codes == 1
    assert result.notification_outbox == 2
    db_session.expire_all()
    assert await db_session.get(IdentityActionTokenModel, row_ids["stale_expired"]) is None
    assert await db_session.get(IdentityActionTokenModel, row_ids["consumed_at_cutoff"]) is None
    assert (
        await db_session.get(IdentityActionTokenModel, row_ids["just_inside_retention"]) is not None
    )
    assert await db_session.get(IdentityActionTokenModel, row_ids["active_future"]) is not None
    assert (
        await db_session.get(IdentityActionTokenModel, row_ids["consumed_after_cutoff"]) is not None
    )
    assert await db_session.get(DashboardAuthChallengeModel, row_ids["terminal_challenge"]) is None
    assert (
        await db_session.get(
            DashboardAuthChallengeModel,
            row_ids["fresh_terminal_challenge"],
        )
        is not None
    )
    assert await db_session.get(MFARecoveryCodeModel, row_ids["consumed_code"]) is None
    assert await db_session.get(IdentityNotificationOutboxModel, row_ids["stale_outbox"]) is None
    assert (
        await db_session.get(
            IdentityNotificationOutboxModel,
            row_ids["orphaned_pending_outbox"],
        )
        is None
    )
    assert (
        await db_session.get(
            IdentityNotificationOutboxModel,
            row_ids["fresh_orphaned_outbox"],
        )
        is not None
    )


@pytest.mark.asyncio
async def test_tenant_retention_is_bounded_restart_safe_and_idempotent(
    db_session: AsyncSession,
    test_settings: Settings,
) -> None:
    now = datetime(2026, 8, 23, 17, 0, tzinfo=UTC)
    agency_a = AgencyModel(name="Retention A", email="retention-a@example.com")
    agency_b = AgencyModel(name="Retention B", email="retention-b@example.com")
    db_session.add_all([agency_a, agency_b])
    await db_session.flush()
    user_a = await _user(
        db_session,
        email="tenant-a-retention@example.com",
        agency_id=agency_a.id,
    )
    user_b = await _user(
        db_session,
        email="tenant-b-retention@example.com",
        agency_id=agency_b.id,
    )
    created_at = now - timedelta(days=40)
    expires_at = now - timedelta(days=31)
    invalidated_at = now - timedelta(days=31)
    for index in range(12):
        db_session.add(
            _token(
                user_id=user_a.id,
                token_hash=f"{index:064x}",
                created_at=created_at,
                expires_at=expires_at,
                invalidated_at=invalidated_at,
            )
        )
    for index in range(12, 24):
        db_session.add(
            _token(
                user_id=user_b.id,
                token_hash=f"{index:064x}",
                created_at=created_at,
                expires_at=expires_at,
                invalidated_at=invalidated_at,
            )
        )
    await db_session.commit()
    settings = test_settings.model_copy(update={"identity_retention_batch_size": 10})
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    first = await apply_identity_retention(
        session_factory=factory,
        settings=settings,
        agency_id=agency_a.id,
        now=now,
    )
    second = await apply_identity_retention(
        session_factory=factory,
        settings=settings,
        agency_id=agency_a.id,
        now=now,
    )
    third = await apply_identity_retention(
        session_factory=factory,
        settings=settings,
        agency_id=agency_a.id,
        now=now,
    )

    assert (first.action_tokens, second.action_tokens, third.action_tokens) == (10, 2, 0)
    remaining_a = (
        await db_session.execute(
            select(func.count(IdentityActionTokenModel.id)).where(
                IdentityActionTokenModel.user_id == user_a.id
            )
        )
    ).scalar_one()
    remaining_b = (
        await db_session.execute(
            select(func.count(IdentityActionTokenModel.id)).where(
                IdentityActionTokenModel.user_id == user_b.id
            )
        )
    ).scalar_one()
    assert remaining_a == 0
    assert remaining_b == 12


@pytest.mark.asyncio
async def test_cleanup_never_deletes_an_active_token_before_redemption(
    db_session: AsyncSession,
    test_settings: Settings,
) -> None:
    now = datetime(2026, 8, 23, 18, 0, tzinfo=UTC)
    user = await _user(db_session, email="active-retention@example.com")
    repository = IdentitySecurityRepository(db_session)
    await repository.ensure_state(user)
    token, raw = await repository.issue_action_token(
        user_id=user.id,
        purpose="password_recovery",
        expires_in=timedelta(minutes=20),
        now=now,
    )
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    result = await apply_identity_retention(
        session_factory=factory,
        settings=test_settings,
        now=now,
    )

    assert result.action_tokens == 0
    db_session.expire_all()
    claim = await IdentitySecurityRepository(db_session).get_valid_action_token(
        raw_token=raw,
        purpose="password_recovery",
        now=now,
    )
    assert claim is not None
    assert claim.id == token.id
