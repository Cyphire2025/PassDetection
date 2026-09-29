"""Additive coordinator membership and manager-owned attendance preparation."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select

from app.application.mcp.change_context import require_change_actor, require_change_group
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.operations import (
    MCPCreatedEntity,
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
)
from app.application.mobile.sync_journal import append_attendance_realtime_invalidation
from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import AuthorizationError
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.models import (
    AttendanceSessionModel,
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
    UserModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository

TourChangeKind = Literal["add_group_coordinators", "create_attendance_activity"]


@dataclass(frozen=True, slots=True)
class TourCreationSupport:
    require_assignable_trip: Callable[[ClientGroupModel], None]
    create_activity: Callable[..., Awaitable[tuple[AttendanceSessionModel, str]]]


@dataclass(frozen=True, slots=True)
class TourChangeCommand:
    agency_id: uuid.UUID
    group_id: uuid.UUID
    body: Any


async def _scope(
    context: MCPDatabaseContext, agency_id: uuid.UUID, group_id: uuid.UUID
) -> tuple[User, ClientGroupModel]:
    actor = await require_change_actor(context, agency_id)
    group = await require_change_group(context, actor, group_id, agency_id, exclusive=True)
    try:
        await AuthorizationPolicy(context.session).require_assign_coordinator(actor, group)
    except AuthorizationError as exc:
        raise MCPAuthError("access_denied", 403) from exc
    return actor, group


async def _add_coordinators(
    context: MCPDatabaseContext, command: TourChangeCommand
) -> tuple[list[CoordinatorGroupAssignmentModel], list[CoordinatorGroupAssignmentModel]]:
    ids = command.body.coordinator_ids
    users = set(
        (
            await context.session.scalars(
                select(UserModel.id)
                .where(
                    UserModel.id.in_(ids),
                    UserModel.agency_id == command.agency_id,
                    UserModel.role == "agency_coordinator",
                    UserModel.is_active.is_(True),
                    UserModel.deleted_at.is_(None),
                )
                .order_by(UserModel.id)
                .with_for_update(read=True)
            )
        ).all()
    )
    if users != set(ids):
        raise MCPOperationError("tour_coordinator_unavailable")
    existing = list(
        (
            await context.session.scalars(
                select(CoordinatorGroupAssignmentModel)
                .where(
                    CoordinatorGroupAssignmentModel.group_id == command.group_id,
                    CoordinatorGroupAssignmentModel.coordinator_user_id.in_(ids),
                    CoordinatorGroupAssignmentModel.active.is_(True),
                )
                .with_for_update()
            )
        ).all()
    )
    if any(row.agency_id != command.agency_id for row in existing):
        raise MCPOperationError("tour_assignment_scope_conflict")
    present = {row.coordinator_user_id for row in existing}
    now = datetime.now(UTC)
    added = [
        CoordinatorGroupAssignmentModel(
            agency_id=command.agency_id,
            group_id=command.group_id,
            coordinator_user_id=coordinator_id,
            assigned_by_user_id=context.principal.user_id,
            active=True,
            assigned_at=now,
        )
        for coordinator_id in ids
        if coordinator_id not in present
    ]
    context.session.add_all(added)
    await context.session.flush()
    return added, existing


def tour_change_operation(
    kind: TourChangeKind,
    *,
    support: TourCreationSupport,
    validate: Callable[[dict[str, Any]], TourChangeCommand],
) -> MCPDatabaseOperation:
    if kind not in {"add_group_coordinators", "create_attendance_activity"}:
        raise ValueError("Unsupported tour operation")

    async def mutate(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        command = validate(payload)
        actor, group = await _scope(context, command.agency_id, command.group_id)
        data: dict[str, Any] = {"agency_id": str(group.agency_id), "group_id": str(group.id)}
        if kind == "add_group_coordinators":
            support.require_assignable_trip(group)
            added, existing = await _add_coordinators(context, command)
            data.update(
                added_assignment_ids=[str(row.id) for row in added],
                existing_assignment_ids=[str(row.id) for row in existing],
                coordinator_ids=[str(value) for value in command.body.coordinator_ids],
                passenger_assignments_changed=0,
            )
            entities = tuple(
                MCPCreatedEntity(
                    "coordinator_group_assignment",
                    str(row.id),
                    f"/tour-operations/groups/{group.id}",
                )
                for row in added
            )
            action, entity_type, entity_id = "tour.coordinators_added", "client_group", group.id
        else:
            activity, outcome = await support.create_activity(
                context.session,
                agency_id=group.agency_id,
                group_id=group.id,
                name=command.body.name,
                created_by_user_id=actor.id,
                scheduled_starts_at=command.body.scheduled_starts_at,
                scheduled_ends_at=command.body.scheduled_ends_at,
                schedule_timezone=command.body.schedule_timezone,
            )
            if outcome not in {"created", "existing"}:
                raise MCPOperationError("tour_activity_not_additive")
            if outcome == "created":
                await append_attendance_realtime_invalidation(
                    context.session,
                    agency_id=group.agency_id,
                    group_id=group.id,
                    entity_type="attendance_session",
                    entity_id=activity.id,
                    changed_by_user_id=actor.id,
                    occurred_at=activity.updated_at,
                )
            data.update(activity_id=str(activity.id), outcome=outcome, scan_records_created=0)
            entities = (
                (
                    MCPCreatedEntity(
                        "attendance_session",
                        str(activity.id),
                        f"/tour-operations/groups/{group.id}/attendance",
                    ),
                )
                if outcome == "created"
                else ()
            )
            action, entity_type, entity_id = (
                "attendance.activity_prepared",
                "attendance_session",
                activity.id,
            )
        audit = await AuditLogRepository(context.session).record(
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            agency_id=group.agency_id,
            user_id=actor.id,
            actor_email=actor.email,
            metadata={**data, "mcp_operation_id": str(context.operation_id)},
        )
        data["business_audit_id"] = str(audit.id)
        return MCPDatabaseResult(data, created_entities=entities)

    async def authorize_receipt(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        data = receipt["data"]
        _, group = await _scope(context, uuid.UUID(data["agency_id"]), uuid.UUID(data["group_id"]))
        if kind == "create_attendance_activity":
            activity_id = uuid.UUID(data["activity_id"])
            found = await context.session.scalar(
                select(AttendanceSessionModel.id).where(
                    AttendanceSessionModel.id == activity_id,
                    AttendanceSessionModel.canonical_session_id == activity_id,
                    AttendanceSessionModel.group_id == group.id,
                    AttendanceSessionModel.agency_id == group.agency_id,
                )
            )
            if found is None:
                raise MCPOperationError("tour_receipt_unavailable")
        else:
            ids = {
                uuid.UUID(value)
                for value in data["added_assignment_ids"] + data["existing_assignment_ids"]
            }
            current = set(
                (
                    await context.session.scalars(
                        select(CoordinatorGroupAssignmentModel.id)
                        .join(
                            UserModel,
                            UserModel.id == CoordinatorGroupAssignmentModel.coordinator_user_id,
                        )
                        .where(
                            CoordinatorGroupAssignmentModel.id.in_(ids),
                            CoordinatorGroupAssignmentModel.group_id == group.id,
                            CoordinatorGroupAssignmentModel.agency_id == group.agency_id,
                            CoordinatorGroupAssignmentModel.active.is_(True),
                            UserModel.agency_id == group.agency_id,
                            UserModel.is_active.is_(True),
                            UserModel.deleted_at.is_(None),
                            UserModel.role == "agency_coordinator",
                        )
                    )
                ).all()
            )
            if current != ids:
                raise MCPOperationError("tour_receipt_unavailable")

    return MCPDatabaseOperation(
        MCPToolPolicy(kind, MCPCapability.CHANGE, frozenset({kind})), mutate, authorize_receipt
    )
