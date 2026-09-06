"""Live, tenant-scoped authorization snapshots for dashboard realtime."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.realtime_authorization import MobileRealtimeAuthorization
from app.core.security.jwt import decode_access_token
from app.domain.entities.entities import GroupStatus, UserRole
from app.domain.exceptions.exceptions import AuthenticationError, AuthorizationError
from app.infrastructure.database.models import (
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
    ManagerGroupAccessModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.repositories.coordinator_assignment_lifecycle import (
    expired_trip_clause,
)

DASHBOARD_REALTIME_ROLES = frozenset(
    {
        UserRole.AGENCY_ADMIN,
        UserRole.AGENCY_MANAGER,
        UserRole.AGENCY_STAFF,
        UserRole.AGENCY_COORDINATOR,
    }
)


@dataclass(frozen=True, slots=True)
class DashboardRealtimeClaims:
    """The small access-token subset needed to fence a dashboard socket."""

    user_id: uuid.UUID
    role: UserRole
    agency_id: uuid.UUID
    token_id: uuid.UUID
    session_version: int


def parse_dashboard_realtime_claims(token: str) -> DashboardRealtimeClaims:
    """Verify the signed access token and reject malformed authority claims."""

    payload = decode_access_token(token)
    try:
        user_id = uuid.UUID(_required_string(payload, "sub"))
        token_id = uuid.UUID(_required_string(payload, "jti"))
        role = UserRole(_required_string(payload, "role"))
    except (TypeError, ValueError) as exc:
        raise AuthenticationError("Invalid dashboard access token") from exc

    raw_session_version = payload.get("sv")
    if (
        not isinstance(raw_session_version, int)
        or isinstance(raw_session_version, bool)
        or raw_session_version < 1
    ):
        raise AuthenticationError("Invalid dashboard access token")
    if role not in DASHBOARD_REALTIME_ROLES:
        raise AuthorizationError("Dashboard realtime access is not available")
    try:
        agency_id = uuid.UUID(_required_string(payload, "agency_id"))
    except (TypeError, ValueError) as exc:
        raise AuthenticationError("Invalid dashboard access token") from exc
    return DashboardRealtimeClaims(
        user_id=user_id,
        role=role,
        agency_id=agency_id,
        token_id=token_id,
        session_version=raw_session_version,
    )


async def load_dashboard_realtime_authorization(
    session: AsyncSession,
    token: str,
    *,
    maximum_trips: int,
) -> MobileRealtimeAuthorization:
    """Resolve current identity state and the exact visible trip set.

    The snapshot is intentionally short-lived. Re-running it while the socket
    is open makes account suspension, session-epoch changes, role changes,
    tenant moves, and assignment removal revoke fanout without reconnecting.
    """

    claims = parse_dashboard_realtime_claims(token)
    identity_result = await session.execute(
        select(UserModel, UserSecurityStateModel)
        .outerjoin(
            UserSecurityStateModel,
            UserSecurityStateModel.user_id == UserModel.id,
        )
        .where(
            UserModel.id == claims.user_id,
            UserModel.deleted_at.is_(None),
        )
        .limit(1)
    )
    identity = identity_result.first()
    if identity is None:
        raise AuthenticationError("User not found")
    user, security_state = identity
    live_session_version = security_state.session_version if security_state is not None else 1
    live_credential_state = (
        security_state.credential_state if security_state is not None else "active"
    )
    if (
        not user.is_active
        or live_credential_state != "active"
        or live_session_version != claims.session_version
        or user.role != claims.role.value
        or user.agency_id != claims.agency_id
    ):
        raise AuthenticationError("Session is no longer valid")

    trip_statement = select(ClientGroupModel.id).where(
        ClientGroupModel.agency_id == claims.agency_id,
        ClientGroupModel.status.in_((GroupStatus.ACTIVE.value, GroupStatus.CLOSED.value)),
        ClientGroupModel.deleted_at.is_(None),
    )
    if claims.role == UserRole.AGENCY_STAFF:
        assigned = exists().where(
            ManagerGroupAccessModel.manager_id == claims.user_id,
            ManagerGroupAccessModel.agency_id == claims.agency_id,
            ManagerGroupAccessModel.group_id == ClientGroupModel.id,
        )
        trip_statement = trip_statement.where(
            or_(
                ClientGroupModel.created_by_user_id == claims.user_id,
                assigned,
            )
        )
    elif claims.role == UserRole.AGENCY_COORDINATOR:
        trip_statement = trip_statement.join(
            CoordinatorGroupAssignmentModel,
            (
                CoordinatorGroupAssignmentModel.group_id == ClientGroupModel.id
            )
            & (
                CoordinatorGroupAssignmentModel.agency_id
                == ClientGroupModel.agency_id
            ),
        ).where(
            CoordinatorGroupAssignmentModel.agency_id == claims.agency_id,
            CoordinatorGroupAssignmentModel.coordinator_user_id == claims.user_id,
            CoordinatorGroupAssignmentModel.active.is_(True),
            ~expired_trip_clause(),
        )

    trips_result = await session.execute(
        trip_statement.distinct().order_by(ClientGroupModel.id).limit(maximum_trips + 1)
    )
    trip_ids = list(trips_result.scalars().all())
    if len(trip_ids) > maximum_trips:
        raise AuthorizationError("Dashboard realtime trip limit exceeded")
    return MobileRealtimeAuthorization(
        agency_id=claims.agency_id,
        account_id=claims.user_id,
        principal_id=claims.user_id,
        principal_type="dashboard",
        session_id=claims.token_id,
        session_generation=claims.session_version,
        trip_ids=frozenset(trip_ids),
    )


def _required_string(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise AuthenticationError("Invalid dashboard access token")
    return value


__all__ = [
    "DASHBOARD_REALTIME_ROLES",
    "DashboardRealtimeClaims",
    "load_dashboard_realtime_authorization",
    "parse_dashboard_realtime_claims",
]
