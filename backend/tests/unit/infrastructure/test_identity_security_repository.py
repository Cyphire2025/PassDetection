from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config.settings import Settings
from app.core.security import identity_security
from app.infrastructure.database.models import (
    Base,
    DashboardAuthChallengeModel,
    IdentityActionTokenModel,
    IdentityNotificationOutboxModel,
    MFARecoveryCodeModel,
    UserModel,
)
from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository


@pytest.mark.asyncio
async def test_identity_actions_are_hashed_single_use_and_supersede_older_links(
    db_session: AsyncSession,
) -> None:
    user = UserModel(
        email="identity-token@example.test",
        hashed_password="unusable-test-placeholder",
        full_name="Identity Token User",
        role="agency_staff",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    repository = IdentitySecurityRepository(db_session)
    await repository.ensure_state(user, credential_state="invited")

    first_row, first_raw = await repository.issue_action_token(
        user_id=user.id,
        purpose="activation",
        expires_in=timedelta(days=7),
    )
    second_row, second_raw = await repository.issue_action_token(
        user_id=user.id,
        purpose="activation",
        expires_in=timedelta(days=7),
    )

    assert first_raw != second_raw
    assert first_raw != first_row.token_hash
    assert second_raw != second_row.token_hash
    assert first_row.invalidated_at is not None
    assert await repository.get_valid_action_token(
        raw_token=first_raw,
        purpose="activation",
    ) is None
    assert await repository.get_valid_action_token(
        raw_token=second_raw,
        purpose="activation",
    ) is second_row


@pytest.mark.asyncio
async def test_recovery_code_consumption_is_atomic_and_mfa_reset_clears_all_artifacts(
    db_session: AsyncSession,
) -> None:
    user = UserModel(
        email="mfa-reset@example.test",
        hashed_password="unusable-test-placeholder",
        full_name="MFA Reset User",
        role="agency_manager",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    repository = IdentitySecurityRepository(db_session)
    state = await repository.ensure_state(user)
    state.mfa_secret_ciphertext = "encrypted-test-value"
    state.mfa_enabled_at = state.updated_at
    state.mfa_last_counter = 42
    await repository.replace_recovery_codes(
        user_id=user.id,
        raw_codes=[f"AAAA-BBBB-CCCC-{index:04d}" for index in range(10)],
    )
    challenge, _ = await repository.issue_auth_challenge(
        user_id=user.id,
        purpose="mfa_login",
        pending_secret_ciphertext=None,
        request_ip_hash=None,
        user_agent_hash=None,
    )

    assert await repository.consume_recovery_code(
        user_id=user.id,
        raw_code="AAAA-BBBB-CCCC-0000",
    ) is True
    assert await repository.consume_recovery_code(
        user_id=user.id,
        raw_code="AAAA-BBBB-CCCC-0000",
    ) is False
    original_session_version = state.session_version

    await repository.reset_mfa(state=state)

    assert state.mfa_secret_ciphertext is None
    assert state.mfa_enabled_at is None
    assert state.mfa_last_counter is None
    assert state.session_version == original_session_version + 1
    assert challenge.status == "cancelled"
    assert (
        await db_session.execute(
            select(MFARecoveryCodeModel).where(MFARecoveryCodeModel.user_id == user.id)
        )
    ).scalars().all() == []
    assert len(
        (
            await db_session.execute(
                select(IdentityActionTokenModel).where(
                    IdentityActionTokenModel.user_id == user.id
                )
            )
        ).scalars().all()
    ) == 0
    assert (
        await db_session.execute(
            select(DashboardAuthChallengeModel).where(
                DashboardAuthChallengeModel.user_id == user.id
            )
        )
    ).scalar_one().status == "cancelled"


@pytest.mark.asyncio
async def test_action_token_final_consume_gate_is_single_use_even_for_stale_claim(
    db_session: AsyncSession,
) -> None:
    user = UserModel(
        email="atomic-recovery@example.com",
        hashed_password="unusable-test-placeholder",
        full_name="Atomic Recovery User",
        role="agency_staff",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    repository = IdentitySecurityRepository(db_session)
    await repository.ensure_state(user)
    token, _ = await repository.issue_action_token(
        user_id=user.id,
        purpose="password_recovery",
        expires_in=timedelta(minutes=20),
    )
    now = datetime.now(tz=UTC)

    first = await repository.consume_action_token(
        token_id=token.id,
        purpose="password_recovery",
        now=now,
    )
    second = await repository.consume_action_token(
        token_id=token.id,
        purpose="password_recovery",
        now=now,
    )

    assert first is True
    assert second is False


@pytest.mark.asyncio
async def test_concurrent_action_token_redemption_has_exactly_one_winner(
    tmp_path: Path,
) -> None:
    database_path = (tmp_path / "concurrent-identity.sqlite3").as_posix()
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}",
        connect_args={"timeout": 10},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as seed_session:
        user = UserModel(
            email="concurrent-recovery@example.com",
            hashed_password="unusable-test-placeholder",
            full_name="Concurrent Recovery User",
            role="agency_staff",
            is_active=True,
        )
        seed_session.add(user)
        await seed_session.flush()
        repository = IdentitySecurityRepository(seed_session)
        await repository.ensure_state(user)
        _, raw = await repository.issue_action_token(
            user_id=user.id,
            purpose="password_recovery",
            expires_in=timedelta(minutes=20),
        )
        await seed_session.commit()

    ready = 0
    ready_event = asyncio.Event()
    release_event = asyncio.Event()

    async def redeem() -> bool:
        nonlocal ready
        async with factory() as session:
            repository = IdentitySecurityRepository(session)
            token = await repository.get_valid_action_token(
                raw_token=raw,
                purpose="password_recovery",
            )
            assert token is not None
            ready += 1
            if ready == 2:
                ready_event.set()
            await release_event.wait()
            consumed = await repository.consume_action_token(
                token_id=token.id,
                purpose="password_recovery",
            )
            await session.commit()
            return consumed

    contenders = [asyncio.create_task(redeem()) for _ in range(2)]
    await ready_event.wait()
    release_event.set()
    results = await asyncio.gather(*contenders)

    assert sorted(results) == [False, True]
    await engine.dispose()


@pytest.mark.asyncio
async def test_replacement_terminalizes_pending_or_claimed_old_delivery(
    db_session: AsyncSession,
) -> None:
    user = UserModel(
        email="superseded-recovery@example.com",
        hashed_password="unusable-test-placeholder",
        full_name="Superseded Recovery User",
        role="agency_staff",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    repository = IdentitySecurityRepository(db_session)
    await repository.ensure_state(user)
    first, _ = await repository.issue_action_token(
        user_id=user.id,
        purpose="password_recovery",
        expires_in=timedelta(minutes=20),
    )
    outbox = IdentityNotificationOutboxModel(
        id=uuid.uuid4(),
        user_id=user.id,
        action_token_id=first.id,
        purpose="password_recovery",
        channel="email",
        recipient_ciphertext=b"encrypted-recipient",
        payload_ciphertext=b"encrypted-payload",
        encryption_key_id="legacy-v1",
        dedupe_key="d" * 64,
        status="running",
        attempt_count=1,
        max_attempts=5,
        next_attempt_at=datetime.now(tz=UTC),
        lease_expires_at=datetime.now(tz=UTC) + timedelta(minutes=1),
    )
    db_session.add(outbox)
    await db_session.flush()

    second, _ = await repository.issue_action_token(
        user_id=user.id,
        purpose="password_recovery",
        expires_in=timedelta(minutes=20),
    )

    await db_session.refresh(outbox)
    assert first.invalidated_at is not None
    assert second.invalidated_at is None
    assert outbox.status == "dead_letter"
    assert outbox.last_error_code == "superseded"
    assert outbox.lease_expires_at is None


@pytest.mark.asyncio
async def test_action_token_issued_before_hmac_rotation_remains_redeemable(
    db_session: AsyncSession,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = UserModel(
        email="rotated-action-token@example.com",
        hashed_password="unusable-test-placeholder",
        full_name="Rotated Action Token User",
        role="agency_staff",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    repository = IdentitySecurityRepository(db_session)
    await repository.ensure_state(user)
    monkeypatch.setattr(identity_security, "get_settings", lambda: test_settings)
    issued, raw = await repository.issue_action_token(
        user_id=user.id,
        purpose="password_recovery",
        expires_in=timedelta(minutes=20),
    )
    assert issued.token_key_id == "legacy-v1"
    rotated = test_settings.model_copy(
        update={
            "identity_action_hmac_key_id": "actions-2026-08",
            "identity_action_hmac_key": SecretStr("new-action-key-material-2026-08"),
            "identity_action_hmac_previous_keys": {
                "legacy-v1": SecretStr(test_settings.app_secret_key)
            },
        }
    )
    monkeypatch.setattr(identity_security, "get_settings", lambda: rotated)

    resolved = await repository.get_valid_action_token(
        raw_token=raw,
        purpose="password_recovery",
    )

    assert resolved is issued
