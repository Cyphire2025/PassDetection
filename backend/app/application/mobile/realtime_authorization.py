"""Short-lived authorization snapshots for mobile realtime fanout."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, TypeAlias

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.mobile_jwt import MobileAccessClaims
from app.domain.entities.entities import GroupStatus
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerGroupAssignmentModel,
    ClientManagerProfileModel,
    GCGroupAccessModel,
    MobilePassengerIdentityModel,
    MobilePassengerSessionIdentityModel,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
)
from app.infrastructure.repositories.coordinator_assignment_lifecycle import (
    expired_trip_clause,
)

RealtimePrincipalType: TypeAlias = Literal[
    "passenger",
    "client_manager",
    "coordinator",
    "dashboard",
]


@dataclass(frozen=True, slots=True)
class MobileRealtimeAuthorization:
    agency_id: uuid.UUID
    account_id: uuid.UUID
    principal_id: uuid.UUID
    principal_type: RealtimePrincipalType
    session_id: uuid.UUID
    session_generation: int
    trip_ids: frozenset[uuid.UUID]

    def same_authentication_boundary(self, other: MobileRealtimeAuthorization) -> bool:
        return (
            self.agency_id == other.agency_id
            and self.account_id == other.account_id
            and self.principal_id == other.principal_id
            and self.principal_type == other.principal_type
            and self.session_id == other.session_id
            and self.session_generation == other.session_generation
        )


async def load_mobile_realtime_authorization(
    session: AsyncSession,
    claims: MobileAccessClaims,
    *,
    maximum_trips: int,
) -> MobileRealtimeAuthorization:
    """Resolve the exact live trip set using the same fail-closed grants.

    The query is bounded and tenant-qualified at every join. It is rerun on a
    timer while the socket is open, so session revocation, role removal, trip
    expiry, and assignment changes stop fanout without waiting for a reconnect.
    """

    now = datetime.now(tz=UTC)
    statement = (
        select(GCGroupAccessModel.group_id)
        .join(
            ClientGroupModel,
            and_(
                ClientGroupModel.id == GCGroupAccessModel.group_id,
                ClientGroupModel.agency_id == GCGroupAccessModel.agency_id,
            ),
        )
        .where(
            GCGroupAccessModel.agency_id == claims.agency_id,
            ClientGroupModel.status.in_((GroupStatus.ACTIVE.value, GroupStatus.CLOSED.value)),
            ClientGroupModel.deleted_at.is_(None),
            GCGroupAccessModel.is_enabled.is_(True),
            GCGroupAccessModel.revoked_at.is_(None),
            or_(
                GCGroupAccessModel.access_starts_at.is_(None),
                GCGroupAccessModel.access_starts_at <= now,
            ),
            or_(
                GCGroupAccessModel.access_expires_at.is_(None),
                GCGroupAccessModel.access_expires_at > now,
            ),
        )
    )
    if claims.principal_type == "passenger":
        statement = (
            statement.join(
                MobilePassengerSessionIdentityModel,
                and_(
                    MobilePassengerSessionIdentityModel.gc_group_access_id == GCGroupAccessModel.id,
                    MobilePassengerSessionIdentityModel.agency_id == GCGroupAccessModel.agency_id,
                    MobilePassengerSessionIdentityModel.group_id == GCGroupAccessModel.group_id,
                ),
            )
            .join(
                MobilePassengerIdentityModel,
                and_(
                    MobilePassengerIdentityModel.id
                    == MobilePassengerSessionIdentityModel.passenger_identity_id,
                    MobilePassengerIdentityModel.gc_group_access_id
                    == MobilePassengerSessionIdentityModel.gc_group_access_id,
                    MobilePassengerIdentityModel.agency_id
                    == MobilePassengerSessionIdentityModel.agency_id,
                    MobilePassengerIdentityModel.group_id
                    == MobilePassengerSessionIdentityModel.group_id,
                ),
            )
            .where(
                GCGroupAccessModel.passenger_access_enabled.is_(True),
                MobilePassengerSessionIdentityModel.session_id == claims.session_id,
                MobilePassengerSessionIdentityModel.agency_id == claims.agency_id,
                MobilePassengerIdentityModel.claim_generation
                == MobilePassengerSessionIdentityModel.identity_claim_generation,
                MobilePassengerIdentityModel.status.in_(("eligible", "claimed")),
                MobilePassengerIdentityModel.revoked_at.is_(None),
            )
        )
    elif claims.principal_type == "client_manager":
        statement = (
            statement.join(
                ClientManagerGroupAssignmentModel,
                and_(
                    ClientManagerGroupAssignmentModel.gc_group_access_id == GCGroupAccessModel.id,
                    ClientManagerGroupAssignmentModel.agency_id == GCGroupAccessModel.agency_id,
                    ClientManagerGroupAssignmentModel.group_id == GCGroupAccessModel.group_id,
                ),
            )
            .join(
                ClientManagerProfileModel,
                and_(
                    ClientManagerProfileModel.id == ClientManagerGroupAssignmentModel.profile_id,
                    ClientManagerProfileModel.agency_id
                    == ClientManagerGroupAssignmentModel.agency_id,
                ),
            )
            .where(
                GCGroupAccessModel.client_manager_access_enabled.is_(True),
                ClientManagerProfileModel.user_id == claims.principal_id,
                ClientManagerProfileModel.agency_id == claims.agency_id,
                ClientManagerProfileModel.status == "active",
                ClientManagerProfileModel.deleted_at.is_(None),
                ClientManagerGroupAssignmentModel.is_active.is_(True),
                ClientManagerGroupAssignmentModel.revoked_at.is_(None),
            )
        )
    elif claims.principal_type == "coordinator":
        statement = statement.join(
            CoordinatorGroupAssignmentModel,
            and_(
                CoordinatorGroupAssignmentModel.group_id == GCGroupAccessModel.group_id,
                CoordinatorGroupAssignmentModel.agency_id == GCGroupAccessModel.agency_id,
            ),
        ).where(
            GCGroupAccessModel.coordinator_access_enabled.is_(True),
            CoordinatorGroupAssignmentModel.coordinator_user_id == claims.principal_id,
            CoordinatorGroupAssignmentModel.active.is_(True),
            ~expired_trip_clause(now),
        )
    else:  # pragma: no cover - MobileAccessClaims is a closed literal today.
        raise AuthorizationError("Mobile realtime access is not available")

    result = await session.execute(
        statement.distinct().order_by(GCGroupAccessModel.group_id).limit(maximum_trips + 1)
    )
    trip_ids = [row[0] for row in result.all()]
    if len(trip_ids) > maximum_trips:
        raise AuthorizationError("Mobile realtime trip limit exceeded")
    return MobileRealtimeAuthorization(
        agency_id=claims.agency_id,
        account_id=claims.account_id,
        principal_id=claims.principal_id,
        principal_type=claims.principal_type,
        session_id=claims.session_id,
        session_generation=claims.session_generation,
        trip_ids=frozenset(trip_ids),
    )


__all__ = [
    "MobileRealtimeAuthorization",
    "RealtimePrincipalType",
    "load_mobile_realtime_authorization",
]
