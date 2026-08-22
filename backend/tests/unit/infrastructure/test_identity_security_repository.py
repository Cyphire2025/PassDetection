from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    DashboardAuthChallengeModel,
    IdentityActionTokenModel,
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
