"""Fail-closed authorization for every GC mobile trip resource."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.mobile_jwt import MobileAccessClaims, MobilePrincipalType
from app.domain.entities.entities import GroupStatus
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerGroupAssignmentModel,
    ClientManagerProfileModel,
    GCGroupAccessModel,
    MobilePassengerIdentityModel,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
)


@dataclass(frozen=True, slots=True)
class AuthorizedMobileTrip:
    group: ClientGroupModel
    access: GCGroupAccessModel
    principal_type: MobilePrincipalType
    passenger_identity: MobilePassengerIdentityModel | None = None
    client_manager_profile: ClientManagerProfileModel | None = None


class MobileAccessPolicy:
    """Evaluate tenant, lifecycle, publication gate, dates, and ownership together."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def require_trip_access(
        self,
        claims: MobileAccessClaims,
        group_id: uuid.UUID,
    ) -> AuthorizedMobileTrip:
        now = datetime.now(tz=UTC)
        result = await self._session.execute(
            select(GCGroupAccessModel, ClientGroupModel)
            .join(ClientGroupModel, ClientGroupModel.id == GCGroupAccessModel.group_id)
            .where(
                GCGroupAccessModel.group_id == group_id,
                GCGroupAccessModel.agency_id == claims.agency_id,
                ClientGroupModel.agency_id == claims.agency_id,
                ClientGroupModel.status.in_(
                    (GroupStatus.ACTIVE.value, GroupStatus.CLOSED.value)
                ),
                ClientGroupModel.deleted_at.is_(None),
                GCGroupAccessModel.is_enabled.is_(True),
                GCGroupAccessModel.revoked_at.is_(None),
                (
                    GCGroupAccessModel.access_starts_at.is_(None)
                    | (GCGroupAccessModel.access_starts_at <= now)
                ),
                (
                    GCGroupAccessModel.access_expires_at.is_(None)
                    | (GCGroupAccessModel.access_expires_at > now)
                ),
            )
            .limit(1)
        )
        row = result.first()
        if row is None:
            raise AuthorizationError("Mobile trip access is not available")
        access, group = row

        if claims.principal_type == "passenger":
            return await self._require_passenger(claims, access, group)
        if claims.principal_type == "client_manager":
            return await self._require_client_manager(claims, access, group)
        if claims.principal_type == "coordinator":
            return await self._require_coordinator(claims, access, group)
        raise AuthorizationError("Mobile trip access is not available")

    async def require_passenger_ownership(
        self,
        claims: MobileAccessClaims,
        *,
        group_id: uuid.UUID,
        passenger_id: uuid.UUID,
    ) -> AuthorizedMobileTrip:
        trip = await self.require_trip_access(claims, group_id)
        identity = trip.passenger_identity
        if identity is None or identity.passenger_submission_id != passenger_id:
            raise AuthorizationError("Passenger resource is not available")
        return trip

    async def _require_passenger(
        self,
        claims: MobileAccessClaims,
        access: GCGroupAccessModel,
        group: ClientGroupModel,
    ) -> AuthorizedMobileTrip:
        if not access.passenger_access_enabled:
            raise AuthorizationError("Mobile trip access is not available")
        result = await self._session.execute(
            select(MobilePassengerIdentityModel)
            .where(
                MobilePassengerIdentityModel.id == claims.principal_id,
                MobilePassengerIdentityModel.agency_id == claims.agency_id,
                MobilePassengerIdentityModel.group_id == group.id,
                MobilePassengerIdentityModel.gc_group_access_id == access.id,
                MobilePassengerIdentityModel.status.in_(("eligible", "claimed")),
                MobilePassengerIdentityModel.revoked_at.is_(None),
            )
            .limit(1)
        )
        identity = result.scalar_one_or_none()
        if identity is None:
            raise AuthorizationError("Mobile trip access is not available")
        return AuthorizedMobileTrip(
            group=group,
            access=access,
            principal_type=claims.principal_type,
            passenger_identity=identity,
        )

    async def _require_client_manager(
        self,
        claims: MobileAccessClaims,
        access: GCGroupAccessModel,
        group: ClientGroupModel,
    ) -> AuthorizedMobileTrip:
        if not access.client_manager_access_enabled:
            raise AuthorizationError("Mobile trip access is not available")
        result = await self._session.execute(
            select(ClientManagerProfileModel)
            .join(
                ClientManagerGroupAssignmentModel,
                ClientManagerGroupAssignmentModel.profile_id
                == ClientManagerProfileModel.id,
            )
            .where(
                ClientManagerProfileModel.user_id == claims.principal_id,
                ClientManagerProfileModel.agency_id == claims.agency_id,
                ClientManagerProfileModel.status == "active",
                ClientManagerProfileModel.deleted_at.is_(None),
                ClientManagerGroupAssignmentModel.agency_id == claims.agency_id,
                ClientManagerGroupAssignmentModel.group_id == group.id,
                ClientManagerGroupAssignmentModel.gc_group_access_id == access.id,
                ClientManagerGroupAssignmentModel.is_active.is_(True),
                ClientManagerGroupAssignmentModel.revoked_at.is_(None),
            )
            .limit(1)
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            raise AuthorizationError("Mobile trip access is not available")
        return AuthorizedMobileTrip(
            group=group,
            access=access,
            principal_type=claims.principal_type,
            client_manager_profile=profile,
        )

    async def _require_coordinator(
        self,
        claims: MobileAccessClaims,
        access: GCGroupAccessModel,
        group: ClientGroupModel,
    ) -> AuthorizedMobileTrip:
        if not access.coordinator_access_enabled:
            raise AuthorizationError("Mobile trip access is not available")
        result = await self._session.execute(
            select(CoordinatorGroupAssignmentModel.id)
            .where(
                CoordinatorGroupAssignmentModel.agency_id == claims.agency_id,
                CoordinatorGroupAssignmentModel.group_id == group.id,
                CoordinatorGroupAssignmentModel.coordinator_user_id
                == claims.principal_id,
                CoordinatorGroupAssignmentModel.active.is_(True),
            )
            .limit(1)
        )
        if result.scalar_one_or_none() is None:
            raise AuthorizationError("Mobile trip access is not available")
        return AuthorizedMobileTrip(
            group=group,
            access=access,
            principal_type=claims.principal_type,
        )
