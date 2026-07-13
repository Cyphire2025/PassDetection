"""Centralized authorization policy for tenant and role decisions."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import (
    AttendanceSessionModel,
    ClientGroupModel,
    CoordinatorAssignmentModel,
    CoordinatorGroupAssignmentModel,
    ManagerGroupAccessModel,
    PassportSubmissionModel,
)


class AuthorizationPolicy:
    """Single place for role, tenant, manager, and coordinator decisions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def manager_group_visibility_filter(user: User):
        return (ClientGroupModel.created_by_user_id == user.id) | ClientGroupModel.id.in_(
            select(ManagerGroupAccessModel.group_id).where(ManagerGroupAccessModel.manager_id == user.id)
        )

    @staticmethod
    def apply_group_visibility_scope(stmt, user: User):  # type: ignore[no-untyped-def]
        if user.role == UserRole.SUPER_ADMIN:
            return stmt
        stmt = stmt.where(ClientGroupModel.agency_id == user.agency_id)
        if user.role == UserRole.AGENCY_STAFF:
            stmt = stmt.where(AuthorizationPolicy.manager_group_visibility_filter(user))
        elif user.role == UserRole.AGENCY_COORDINATOR:
            stmt = stmt.where(
                ClientGroupModel.id.in_(
                    select(CoordinatorGroupAssignmentModel.group_id).where(
                        CoordinatorGroupAssignmentModel.coordinator_user_id == user.id,
                        CoordinatorGroupAssignmentModel.active.is_(True),
                    )
                )
            )
        return stmt

    @staticmethod
    def apply_passport_visibility_scope(stmt, user: User):  # type: ignore[no-untyped-def]
        if user.role == UserRole.SUPER_ADMIN:
            return stmt
        stmt = stmt.where(PassportSubmissionModel.agency_id == user.agency_id)
        if user.role == UserRole.AGENCY_STAFF:
            stmt = stmt.where(AuthorizationPolicy.manager_group_visibility_filter(user))
        elif user.role == UserRole.AGENCY_COORDINATOR:
            stmt = stmt.where(
                PassportSubmissionModel.id.in_(
                    select(CoordinatorAssignmentModel.passenger_id).where(
                        CoordinatorAssignmentModel.coordinator_user_id == user.id,
                        CoordinatorAssignmentModel.active.is_(True),
                    )
                )
            )
        return stmt

    async def can_view_group(self, user: User, group: Any) -> bool:
        if user.role == UserRole.SUPER_ADMIN:
            return True
        if not user.agency_id or group.agency_id != user.agency_id:
            return False
        if user.role == UserRole.AGENCY_ADMIN:
            return True
        if user.role == UserRole.AGENCY_STAFF:
            return await self.manager_can_access_group(user.id, group.id)
        if user.role == UserRole.AGENCY_COORDINATOR:
            return await self.coordinator_has_group(user.id, group.id)
        return False

    async def can_manage_group(self, user: User, group: Any) -> bool:
        if user.role == UserRole.SUPER_ADMIN:
            return True
        if not user.agency_id or group.agency_id != user.agency_id:
            return False
        if user.role == UserRole.AGENCY_ADMIN:
            return True
        if user.role == UserRole.AGENCY_STAFF:
            return group.created_by_user_id == user.id
        return False

    async def can_view_passport(self, user: User, passport: Any) -> bool:
        if user.role == UserRole.SUPER_ADMIN:
            return True
        if not user.agency_id or passport.agency_id != user.agency_id:
            return False
        if user.role == UserRole.AGENCY_ADMIN:
            return True
        if user.role == UserRole.AGENCY_STAFF:
            return await self.manager_can_access_group(user.id, passport.group_id)
        if user.role == UserRole.AGENCY_COORDINATOR:
            return await self.coordinator_has_passenger(user.id, passport.group_id, passport.id)
        return False

    async def can_confirm_passport(self, user: User, passport: Any) -> bool:
        return user.role in {UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_STAFF} and await self.can_view_passport(user, passport)

    async def can_assign_coordinator(self, user: User, group: Any) -> bool:
        if user.role not in {UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_STAFF}:
            return False
        if user.role == UserRole.AGENCY_STAFF:
            return await self.can_view_group(user, group)
        return await self.can_manage_group(user, group)

    async def can_scan_passenger(self, user: User, session: AttendanceSessionModel, passenger: Any) -> bool:
        if user.role != UserRole.AGENCY_COORDINATOR:
            return False
        if not user.agency_id or session.agency_id != user.agency_id or passenger.agency_id != user.agency_id:
            return False
        if session.created_by_user_id != user.id or session.group_id != passenger.group_id:
            return False
        return await self.coordinator_has_passenger(user.id, session.group_id, passenger.id)

    async def can_export_data(self, user: User, group: Any) -> bool:
        return user.role in {UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_STAFF} and await self.can_view_group(user, group)

    async def can_delete_data(self, user: User, group: Any, *, permanent: bool = False) -> bool:
        if user.role == UserRole.SUPER_ADMIN:
            return True
        if not user.agency_id or group.agency_id != user.agency_id:
            return False
        if permanent:
            return user.role == UserRole.AGENCY_ADMIN
        if user.role == UserRole.AGENCY_ADMIN:
            return True
        if user.role == UserRole.AGENCY_STAFF:
            return group.created_by_user_id == user.id
        return False

    async def require_view_group(self, user: User, group: Any) -> None:
        if not await self.can_view_group(user, group):
            raise AuthorizationError("You do not have access to this group")

    async def require_manage_group(self, user: User, group: Any) -> None:
        if not await self.can_manage_group(user, group):
            raise AuthorizationError("You cannot manage this group")

    async def require_view_passport(self, user: User, passport: Any) -> None:
        if not await self.can_view_passport(user, passport):
            raise AuthorizationError("You do not have access to this passport submission")

    async def require_confirm_passport(self, user: User, passport: Any) -> None:
        if not await self.can_confirm_passport(user, passport):
            raise AuthorizationError("You cannot confirm this passport submission")

    async def require_assign_coordinator(self, user: User, group: Any) -> None:
        if not await self.can_assign_coordinator(user, group):
            raise AuthorizationError("You cannot assign coordinators for this group")

    async def require_export_data(self, user: User, group: Any) -> None:
        if not await self.can_export_data(user, group):
            raise AuthorizationError("You cannot export data for this group")

    async def require_delete_data(self, user: User, group: Any, *, permanent: bool = False) -> None:
        if not await self.can_delete_data(user, group, permanent=permanent):
            raise AuthorizationError("You cannot delete data for this group")

    async def manager_can_access_group(self, manager_id: uuid.UUID, group_id: uuid.UUID) -> bool:
        result = await self._session.execute(
            select(ClientGroupModel.id)
            .outerjoin(
                ManagerGroupAccessModel,
                (ManagerGroupAccessModel.group_id == ClientGroupModel.id)
                & (ManagerGroupAccessModel.manager_id == manager_id),
            )
            .where(
                ClientGroupModel.id == group_id,
                or_(
                    ClientGroupModel.created_by_user_id == manager_id,
                    ManagerGroupAccessModel.manager_id == manager_id,
                ),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def coordinator_has_group(self, coordinator_id: uuid.UUID, group_id: uuid.UUID) -> bool:
        result = await self._session.execute(
            select(CoordinatorGroupAssignmentModel.id)
            .where(
                CoordinatorGroupAssignmentModel.group_id == group_id,
                CoordinatorGroupAssignmentModel.coordinator_user_id == coordinator_id,
                CoordinatorGroupAssignmentModel.active.is_(True),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def coordinator_has_passenger(
        self,
        coordinator_id: uuid.UUID,
        group_id: uuid.UUID,
        passenger_id: uuid.UUID,
    ) -> bool:
        result = await self._session.execute(
            select(CoordinatorAssignmentModel.id)
            .where(
                CoordinatorAssignmentModel.group_id == group_id,
                CoordinatorAssignmentModel.passenger_id == passenger_id,
                CoordinatorAssignmentModel.coordinator_user_id == coordinator_id,
                CoordinatorAssignmentModel.active.is_(True),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None
