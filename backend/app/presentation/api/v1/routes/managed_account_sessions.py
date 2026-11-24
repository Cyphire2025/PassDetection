"""Dashboard/mobile session fences and coordinator assignment deactivation."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import (
    ClientGroupModel,
    CoordinatorAssignmentModel,
    CoordinatorGroupAssignmentModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository
from app.infrastructure.repositories.mobile_session_security import revoke_user_mobile_sessions
from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository


async def _deactivate_coordinator_assignments(session: AsyncSession, account: UserModel) -> None:
    if account.role != UserRole.AGENCY_COORDINATOR.value:
        return
    active_group_ids = list(
        (
            await session.execute(
                select(CoordinatorGroupAssignmentModel.group_id).where(
                    CoordinatorGroupAssignmentModel.coordinator_user_id == account.id,
                    CoordinatorGroupAssignmentModel.active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    if active_group_ids:
        # Manager close and assignment replacement use the group row as their
        # participant-set mutex. Lock every affected group deterministically
        # before changing active assignment membership.
        await session.execute(
            select(ClientGroupModel.id)
            .where(ClientGroupModel.id.in_(sorted(set(active_group_ids), key=str)))
            .order_by(ClientGroupModel.id.asc())
            .with_for_update(of=ClientGroupModel)
        )
    now = datetime.now(tz=UTC)
    await session.execute(
        update(CoordinatorAssignmentModel)
        .where(
            CoordinatorAssignmentModel.coordinator_user_id == account.id,
            CoordinatorAssignmentModel.active.is_(True),
        )
        .values(active=False, unassigned_at=now)
    )
    await session.execute(
        update(CoordinatorGroupAssignmentModel)
        .where(
            CoordinatorGroupAssignmentModel.coordinator_user_id == account.id,
            CoordinatorGroupAssignmentModel.active.is_(True),
        )
        .values(active=False, unassigned_at=now)
    )


async def _fence_dashboard_sessions(
    session: AsyncSession,
    account: UserModel,
) -> UserSecurityStateModel:
    """Invalidate both refresh tokens and already-issued access JWTs."""

    repository = IdentitySecurityRepository(session)
    security_state = await repository.get_state(account.id, lock=True)
    if security_state is None:
        security_state = await repository.ensure_state(account)
    security_state.session_version += 1
    security_state.updated_at = datetime.now(tz=UTC)
    await RefreshTokenRepository(session).revoke_all_for_user(account.id)
    await _fence_coordinator_mobile_sessions(
        session,
        account,
        reason="account_session_fenced",
    )
    return security_state


async def _fence_coordinator_mobile_sessions(
    session: AsyncSession,
    account: UserModel,
    *,
    reason: str,
) -> None:
    if account.role != UserRole.AGENCY_COORDINATOR.value or account.agency_id is None:
        return
    await revoke_user_mobile_sessions(
        session,
        agency_id=account.agency_id,
        user_id=account.id,
        subject_role="coordinator",
        reason=reason,
    )
