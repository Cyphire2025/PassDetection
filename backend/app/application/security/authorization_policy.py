"""Centralized authorization policy for tenant and role decisions."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.domain.entities.entities import GroupStatus, User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import (
    AttendanceSessionModel,
    ClientGroupModel,
    CoordinatorAssignmentModel,
    CoordinatorGroupAssignmentModel,
    ManagerGroupAccessModel,
    PassportSubmissionModel,
)
from app.infrastructure.repositories.coordinator_assignment_lifecycle import (
    expired_trip_clause,
)


class AuthorizationPolicy:
    """Single place for role, tenant, manager, and coordinator decisions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def staff_group_visibility_filter(user: User) -> ColumnElement[bool]:
        """Limit staff to groups they created or were explicitly assigned."""

        return (ClientGroupModel.created_by_user_id == user.id) | ClientGroupModel.id.in_(
            select(ManagerGroupAccessModel.group_id).where(ManagerGroupAccessModel.manager_id == user.id)
        )

    @staticmethod
    def staff_passport_visibility_filter(user: User) -> ColumnElement[bool]:
        """Scope staff passports by group id without an unjoined group table."""

        owned_group_ids = select(ClientGroupModel.id).where(
            ClientGroupModel.created_by_user_id == user.id
        )
        assigned_group_ids = select(ManagerGroupAccessModel.group_id).where(
            ManagerGroupAccessModel.manager_id == user.id
        )
        return PassportSubmissionModel.group_id.in_(
            owned_group_ids
        ) | PassportSubmissionModel.group_id.in_(assigned_group_ids)

    @staticmethod
    def apply_group_visibility_scope(stmt, user: User):  # type: ignore[no-untyped-def]
        if user.role == UserRole.SUPER_ADMIN:
            return stmt
        stmt = stmt.where(ClientGroupModel.agency_id == user.agency_id)
        if user.role == UserRole.AGENCY_STAFF:
            stmt = stmt.where(AuthorizationPolicy.staff_group_visibility_filter(user))
        elif user.role == UserRole.AGENCY_COORDINATOR:
            stmt = stmt.where(
                ~expired_trip_clause(),
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
            stmt = stmt.where(
                AuthorizationPolicy.staff_passport_visibility_filter(user)
            )
        elif user.role == UserRole.AGENCY_COORDINATOR:
            stmt = stmt.where(
                PassportSubmissionModel.id.in_(
                    select(CoordinatorAssignmentModel.passenger_id)
                    .join(
                        ClientGroupModel,
                        ClientGroupModel.id == CoordinatorAssignmentModel.group_id,
                    )
                    .where(
                        CoordinatorAssignmentModel.coordinator_user_id == user.id,
                        CoordinatorAssignmentModel.active.is_(True),
                        ~expired_trip_clause(),
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
        if user.role == UserRole.AGENCY_MANAGER:
            return True
        if user.role == UserRole.AGENCY_STAFF:
            return await self.staff_can_access_group(user.id, group.id)
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
        if user.role == UserRole.AGENCY_MANAGER:
            return True
        if user.role == UserRole.AGENCY_STAFF:
            return await self.staff_can_access_group(user.id, group.id)
        return False

    async def can_view_passport(self, user: User, passport: Any) -> bool:
        if user.role == UserRole.SUPER_ADMIN:
            return True
        if not user.agency_id or passport.agency_id != user.agency_id:
            return False
        if user.role == UserRole.AGENCY_ADMIN:
            return True
        if user.role == UserRole.AGENCY_MANAGER:
            return True
        if user.role == UserRole.AGENCY_STAFF:
            return await self.staff_can_access_group(user.id, passport.group_id)
        if user.role == UserRole.AGENCY_COORDINATOR:
            return await self.coordinator_has_passenger(user.id, passport.group_id, passport.id)
        return False

    async def can_confirm_passport(self, user: User, passport: Any) -> bool:
        return user.role in {UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER, UserRole.AGENCY_STAFF} and await self.can_view_passport(user, passport)

    async def can_staff_approve_passport(self, user: User, passport: Any) -> bool:
        """Require an office role plus object-level tenant/group visibility."""

        return await self.can_confirm_passport(user, passport)

    async def can_assign_coordinator(self, user: User, group: Any) -> bool:
        if user.role not in {UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER, UserRole.AGENCY_STAFF}:
            return False
        if user.role == UserRole.AGENCY_STAFF:
            return await self.can_view_group(user, group)
        return await self.can_manage_group(user, group)

    async def can_scan_passenger(self, user: User, session: AttendanceSessionModel, passenger: Any) -> bool:
        if user.role != UserRole.AGENCY_COORDINATOR:
            return False
        if not user.agency_id or session.agency_id != user.agency_id or passenger.agency_id != user.agency_id:
            return False
        if session.group_id != passenger.group_id:
            return False
        return await self.coordinator_has_group(user.id, session.group_id)

    async def can_export_data(self, user: User, group: Any) -> bool:
        return user.role in {UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER, UserRole.AGENCY_STAFF} and await self.can_view_group(user, group)

    async def can_delete_data(self, user: User, group: Any, *, permanent: bool = False) -> bool:
        if user.role == UserRole.SUPER_ADMIN:
            return True
        if not user.agency_id or group.agency_id != user.agency_id:
            return False
        if permanent:
            return user.role in {UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN}
        if user.role == UserRole.AGENCY_ADMIN:
            return True
        if user.role == UserRole.AGENCY_MANAGER:
            return await self.can_manage_group(user, group)
        if user.role == UserRole.AGENCY_STAFF:
            return await self.staff_can_access_group(user.id, group.id)
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

    async def require_staff_approve_passport(self, user: User, passport: Any) -> None:
        if not await self.can_staff_approve_passport(user, passport):
            raise AuthorizationError("You cannot approve this passport submission")

    async def require_assign_coordinator(self, user: User, group: Any) -> None:
        if not await self.can_assign_coordinator(user, group):
            raise AuthorizationError("You cannot assign coordinators for this group")

    async def require_export_data(self, user: User, group: Any) -> None:
        if not await self.can_export_data(user, group):
            raise AuthorizationError("You cannot export data for this group")

    async def require_delete_data(self, user: User, group: Any, *, permanent: bool = False) -> None:
        if not await self.can_delete_data(user, group, permanent=permanent):
            raise AuthorizationError("You cannot delete data for this group")

    async def staff_can_access_group(self, staff_id: uuid.UUID, group_id: uuid.UUID) -> bool:
        """Allow staff-owned or assigned groups while rejecting removed groups."""

        result = await self._session.execute(
            select(ClientGroupModel.id)
            .outerjoin(
                ManagerGroupAccessModel,
                (ManagerGroupAccessModel.group_id == ClientGroupModel.id)
                & (ManagerGroupAccessModel.manager_id == staff_id),
            )
            .where(
                ClientGroupModel.id == group_id,
                ClientGroupModel.status.notin_(
                    [GroupStatus.ARCHIVED.value, GroupStatus.DELETED.value]
                ),
                or_(
                    ClientGroupModel.created_by_user_id == staff_id,
                    ManagerGroupAccessModel.manager_id == staff_id,
                ),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def coordinator_has_group(self, coordinator_id: uuid.UUID, group_id: uuid.UUID) -> bool:
        result = await self._session.execute(
            select(CoordinatorGroupAssignmentModel.id)
            .join(
                ClientGroupModel,
                ClientGroupModel.id == CoordinatorGroupAssignmentModel.group_id,
            )
            .where(
                CoordinatorGroupAssignmentModel.group_id == group_id,
                CoordinatorGroupAssignmentModel.coordinator_user_id == coordinator_id,
                CoordinatorGroupAssignmentModel.active.is_(True),
                ~expired_trip_clause(),
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
        # Compatibility-only lookup retained for generic passport visibility.
        # Attendance routes use the separate group-scoped authorization path.
        result = await self._session.execute(
            select(CoordinatorAssignmentModel.id)
            .join(
                ClientGroupModel,
                ClientGroupModel.id == CoordinatorAssignmentModel.group_id,
            )
            .where(
                CoordinatorAssignmentModel.group_id == group_id,
                CoordinatorAssignmentModel.passenger_id == passenger_id,
                CoordinatorAssignmentModel.coordinator_user_id == coordinator_id,
                CoordinatorAssignmentModel.active.is_(True),
                ~expired_trip_clause(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None
