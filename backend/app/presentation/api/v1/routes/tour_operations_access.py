"""Access for tour operations; preserve tenant, lock and transaction boundaries."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import GroupStatus, User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.domain.value_objects.trip_lifecycle import trip_has_ended
from app.infrastructure.database.models import AttendanceSessionModel, ClientGroupModel

TOUR_OPERATION_ROLES = [
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
    UserRole.AGENCY_STAFF,
    UserRole.AGENCY_COORDINATOR,
]

COORDINATOR_MANAGEMENT_ROLES = [
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
    UserRole.AGENCY_STAFF,
]

COORDINATOR_ACCOUNT_ROLES = [
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
]

ATTENDANCE_CLOSURE_ROLES = [
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
]

TOUR_OPERATION_GROUP_STATUSES = (
    GroupStatus.ACTIVE.value,
    GroupStatus.CLOSED.value,
)


def _require_agency(current_user: User) -> uuid.UUID:
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="User is not assigned to an agency"
        )
    return current_user.agency_id


def _agency_scope(current_user: User) -> uuid.UUID | None:
    """Return the agency scope for office list views.

    Super admins are intentionally allowed to have no agency. They should still
    be able to open empty/new production dashboards without every agency-scoped
    overview endpoint failing with 400.
    """
    if current_user.role == UserRole.SUPER_ADMIN:
        return current_user.agency_id
    return _require_agency(current_user)


async def _get_group(
    session: AsyncSession, agency_id: uuid.UUID, group_id: uuid.UUID
) -> ClientGroupModel:
    result = await session.execute(
        select(ClientGroupModel).where(
            ClientGroupModel.id == group_id, ClientGroupModel.agency_id == agency_id
        )
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group was not found")
    return group


async def _lock_attendance_closeout_group(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
) -> None:
    locked_group_id = await session.scalar(
        select(ClientGroupModel.id)
        .where(
            ClientGroupModel.id == group_id,
            ClientGroupModel.agency_id == agency_id,
            ClientGroupModel.status != GroupStatus.DELETED.value,
            ClientGroupModel.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if locked_group_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group was not found")


def _require_assignable_trip(group: ClientGroupModel) -> None:
    if not (group.return_date or group.travel_date):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Set the trip dates before assigning coordinators.",
        )
    if trip_has_ended(
        travel_date=group.travel_date,
        return_date=group.return_date,
        timezone=group.timezone,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This trip has ended. Coordinators can only be assigned to upcoming or ongoing trips.",
        )


async def _get_manageable_group(
    session: AsyncSession,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    current_user: User,
    *,
    lock_for_update: bool = False,
) -> ClientGroupModel:
    statement = select(ClientGroupModel).where(
        ClientGroupModel.id == group_id,
        ClientGroupModel.agency_id == agency_id,
        ClientGroupModel.status != "deleted",
    )
    if lock_for_update:
        statement = statement.with_for_update()
    result = await session.execute(statement)
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group was not found")
    try:
        await AuthorizationPolicy(session).require_assign_coordinator(current_user, group)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)
    return group


async def _get_managed_attendance_session(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    session_id: uuid.UUID,
    lock_for_update: bool = True,
) -> AttendanceSessionModel:
    statement = select(AttendanceSessionModel).where(
        AttendanceSessionModel.id == session_id,
        AttendanceSessionModel.canonical_session_id == session_id,
        AttendanceSessionModel.agency_id == agency_id,
        AttendanceSessionModel.group_id == group_id,
    )
    if lock_for_update:
        statement = statement.with_for_update()
    result = await session.execute(statement)
    attendance_session = result.scalar_one_or_none()
    if attendance_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attendance activity was not found",
        )
    return attendance_session


async def _get_attendance_close_group_scope(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    current_user: User,
    lock_for_update: bool = False,
) -> tuple[uuid.UUID, ClientGroupModel]:
    """Resolve the target tenant before closing, including global super admins."""

    if current_user.role != UserRole.SUPER_ADMIN or current_user.agency_id is not None:
        agency_id = _require_agency(current_user)
        group = await _get_manageable_group(
            session,
            agency_id,
            group_id,
            current_user,
            lock_for_update=lock_for_update,
        )
        return agency_id, group

    statement = select(ClientGroupModel).where(
        ClientGroupModel.id == group_id,
        ClientGroupModel.status != "deleted",
    )
    if lock_for_update:
        statement = statement.with_for_update()
    result = await session.execute(statement)
    global_group = result.scalar_one_or_none()
    if global_group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group was not found")
    try:
        await AuthorizationPolicy(session).require_assign_coordinator(current_user, global_group)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)
    return global_group.agency_id, global_group


async def _ensure_group_assigned_to_coordinator(
    session: AsyncSession,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    coordinator_id: uuid.UUID,
) -> None:
    if not await AuthorizationPolicy(session).coordinator_has_group(coordinator_id, group_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group was not assigned to this coordinator",
        )


async def _get_coordinator_attendance_session(
    session: AsyncSession,
    agency_id: uuid.UUID,
    session_id: uuid.UUID,
    coordinator_id: uuid.UUID,
    *,
    lock_for_scan: bool = False,
) -> AttendanceSessionModel:
    requested_session = aliased(
        AttendanceSessionModel,
        name="requested_attendance_session",
    )
    canonical_session = aliased(
        AttendanceSessionModel,
        name="canonical_attendance_session",
    )
    statement = (
        select(canonical_session)
        .join(
            requested_session,
            requested_session.canonical_session_id == canonical_session.id,
        )
        .join(ClientGroupModel, ClientGroupModel.id == canonical_session.group_id)
        .where(
            requested_session.id == session_id,
            requested_session.agency_id == agency_id,
            canonical_session.agency_id == agency_id,
            AuthorizationPolicy.coordinator_group_visibility_filter(
                coordinator_id,
                agency_id=agency_id,
            ),
        )
    )
    if lock_for_scan:
        # Shared scan locks remain concurrent with one another but serialize
        # against the manager's exclusive global-close lock.
        statement = statement.with_for_update(read=True, of=canonical_session)
    result = await session.execute(statement)
    attendance_session = result.scalar_one_or_none()
    if not attendance_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attendance activity was not found"
        )
    return attendance_session
