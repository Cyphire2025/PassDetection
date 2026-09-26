"""Centralized authorization policy for tenant and role decisions."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, false, or_, select, true
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
    def can_access_retained_data(user: User) -> bool:
        """Only the platform role may inspect retained deleted records."""
        return user.role == UserRole.SUPER_ADMIN

    @staticmethod
    def _visible_group_statuses(role: UserRole) -> tuple[str, ...]:
        # Archive administration is an established office-admin/manager workflow.
        # Staff and coordinators do not inherit that historical-data capability.
        if role in {UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER}:
            return (GroupStatus.ACTIVE.value, GroupStatus.CLOSED.value, GroupStatus.ARCHIVED.value)
        if role in {UserRole.AGENCY_STAFF, UserRole.AGENCY_COORDINATOR}:
            return (GroupStatus.ACTIVE.value, GroupStatus.CLOSED.value)
        return ()

    @staticmethod
    def _group_lifecycle_filter(role: UserRole) -> ColumnElement[bool]:
        return and_(
            ClientGroupModel.deleted_at.is_(None),
            ClientGroupModel.status.in_(AuthorizationPolicy._visible_group_statuses(role)),
        )

    @staticmethod
    def _group_visibility_boundary(user: User) -> ColumnElement[bool]:
        """Tenant and lifecycle boundary, also used by parent-passport lookups."""
        if AuthorizationPolicy.can_access_retained_data(user):
            return true()
        if not user.agency_id:
            return false()
        return and_(
            ClientGroupModel.agency_id == user.agency_id,
            AuthorizationPolicy._group_lifecycle_filter(user.role),
        )

    @staticmethod
    def _group_within_visibility_boundary(user: User, group: Any) -> bool:
        if AuthorizationPolicy.can_access_retained_data(user):
            return True
        return bool(
            user.agency_id
            and group.agency_id == user.agency_id
            and group.deleted_at is None
            and group.status in AuthorizationPolicy._visible_group_statuses(user.role)
        )

    @staticmethod
    def staff_group_visibility_filter(user: User) -> ColumnElement[bool]:
        """Limit staff to groups they created or were explicitly assigned."""

        return and_(
            AuthorizationPolicy._group_visibility_boundary(user),
            or_(
                ClientGroupModel.created_by_user_id == user.id,
                ClientGroupModel.id.in_(
                    select(ManagerGroupAccessModel.group_id).where(ManagerGroupAccessModel.manager_id == user.id)
                ),
            ),
        )

    @staticmethod
    def staff_passport_visibility_filter(user: User) -> ColumnElement[bool]:
        """Scope staff passports by group id without an unjoined group table."""

        visible_group_ids = select(ClientGroupModel.id).where(
            AuthorizationPolicy.staff_group_visibility_filter(user)
        ).correlate(None)
        return and_(
            PassportSubmissionModel.agency_id == user.agency_id,
            PassportSubmissionModel.group_id.in_(visible_group_ids),
        )

    @staticmethod
    def coordinator_group_visibility_filter(
        coordinator_id: uuid.UUID, *, agency_id: uuid.UUID | None = None,
    ) -> ColumnElement[bool]:
        """Shared boundary for coordinator groups and their attendance sessions."""
        assignment = select(CoordinatorGroupAssignmentModel.id).where(
            CoordinatorGroupAssignmentModel.group_id == ClientGroupModel.id,
            CoordinatorGroupAssignmentModel.agency_id == ClientGroupModel.agency_id,
            CoordinatorGroupAssignmentModel.coordinator_user_id == coordinator_id,
            CoordinatorGroupAssignmentModel.active.is_(True),
        ).correlate(ClientGroupModel).exists()
        return and_(
            ClientGroupModel.agency_id == agency_id if agency_id is not None else true(),
            AuthorizationPolicy._group_lifecycle_filter(UserRole.AGENCY_COORDINATOR),
            ~expired_trip_clause(),
            assignment,
        )

    @staticmethod
    def apply_group_visibility_scope(stmt, user: User):  # type: ignore[no-untyped-def]
        stmt = stmt.where(AuthorizationPolicy._group_visibility_boundary(user))
        if user.role == UserRole.AGENCY_STAFF:
            stmt = stmt.where(AuthorizationPolicy.staff_group_visibility_filter(user))
        elif user.role == UserRole.AGENCY_COORDINATOR:
            stmt = stmt.where(
                AuthorizationPolicy.coordinator_group_visibility_filter(user.id, agency_id=user.agency_id)
            )
        return stmt

    @staticmethod
    def apply_passport_visibility_scope(stmt, user: User):  # type: ignore[no-untyped-def]
        # Explicit correlation keeps this correct both with and without an
        # outer ClientGroup join (search joins one; several list callers do not).
        parent_group = select(ClientGroupModel.id).where(
            ClientGroupModel.id == PassportSubmissionModel.group_id,
            ClientGroupModel.agency_id == PassportSubmissionModel.agency_id,
            AuthorizationPolicy._group_visibility_boundary(user),
        ).correlate(PassportSubmissionModel).exists()
        stmt = stmt.where(parent_group)
        if not AuthorizationPolicy.can_access_retained_data(user):
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
        if not self._group_within_visibility_boundary(user, group):
            return False
        if user.role == UserRole.SUPER_ADMIN:
            return True
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
        if not self._group_within_visibility_boundary(user, group):
            return False
        if user.role == UserRole.SUPER_ADMIN:
            return True
        if user.role == UserRole.AGENCY_ADMIN:
            return True
        if user.role == UserRole.AGENCY_MANAGER:
            return True
        if user.role == UserRole.AGENCY_STAFF:
            return await self.staff_can_access_group(user.id, group.id)
        return False

    async def can_view_passport(self, user: User, passport: Any) -> bool:
        if not self.can_access_retained_data(user) and (
            not user.agency_id or passport.agency_id != user.agency_id
        ):
            return False
        parent = await self._session.execute(
            select(ClientGroupModel.id).where(
                ClientGroupModel.id == passport.group_id,
                ClientGroupModel.agency_id == passport.agency_id,
                self._group_visibility_boundary(user),
            )
        )
        if parent.scalar_one_or_none() is None:
            return False
        if user.role == UserRole.SUPER_ADMIN:
            return True
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
            # Deliberately separate from content visibility: an authorized
            # retry of permanent deletion must keep its idempotent response.
            return user.role in {UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN}
        if user.role in {UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER}:
            return await self.can_manage_group(user, group)
        return False

    async def can_delete_passport_submissions(self, user: User, group: Any) -> bool:
        """Allow managers to delete submissions without granting group purge access."""

        return user.role in {
            UserRole.SUPER_ADMIN,
            UserRole.AGENCY_ADMIN,
            UserRole.AGENCY_MANAGER,
        } and await self.can_manage_group(user, group)

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

    async def require_delete_passport_submissions(self, user: User, group: Any) -> None:
        if not await self.can_delete_passport_submissions(user, group):
            raise AuthorizationError("You cannot delete passport submissions from this group")

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
                self._group_lifecycle_filter(UserRole.AGENCY_STAFF),
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
            select(ClientGroupModel.id)
            .where(
                ClientGroupModel.id == group_id,
                self.coordinator_group_visibility_filter(coordinator_id),
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
                self._group_lifecycle_filter(UserRole.AGENCY_COORDINATOR),
                ~expired_trip_clause(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None
