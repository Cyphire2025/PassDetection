"""Reviewed database-only edits with canonical validation and retained before-images."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from app.application.mcp.change_context import require_change_group
from app.application.mcp.credentials import utc
from app.application.mcp.operations import (
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
)
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.menu_models import (
    MealPlanEntryModel,
    MealPlanModel,
    MenuCategoryModel,
    MenuDishModel,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    RoomingAssignmentModel,
    RoomingHotelModel,
    RoomingHotelPassengerModel,
    RoomingRoomModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.routes import client_groups, menu, rooming
from app.presentation.api.v1.schemas.client_group_schemas import UpdateClientGroupRequest
from app.presentation.mcp.dashboard_edit_models import EDIT_MODELS, GROUP_CONFIGURATION_FIELDS
from app.presentation.mcp.dashboard_write_support import (
    MAX_RESULT_BYTES,
    PRIVATE_FIELDS,
    audit_request,
    lock_group_revision,
    public_failure,
    safe_result,
    scoped_actor,
)

TARGETS = {
    "configure_group_link": (ClientGroupModel, "group_id"),
    "update_menu_category": (MenuCategoryModel, "category_id"),
    "update_menu_dish": (MenuDishModel, "dish_id"),
    "update_meal_plan": (MealPlanModel, "plan_id"),
    "update_meal_plan_entry": (MealPlanModel, "plan_id"),
    "configure_rooming_hotel": (RoomingHotelModel, "hotel_id"),
    "select_rooming_passengers": (RoomingHotelModel, "hotel_id"),
    "set_rooming_vip": (RoomingHotelModel, "hotel_id"),
    "allocate_rooming_rooms": (RoomingHotelModel, "hotel_id"),
}


def validate_edit(name: str, payload: dict[str, Any]) -> BaseModel:
    try:
        return EDIT_MODELS[name].model_validate(payload)
    except ValidationError as exc:
        raise MCPOperationError("invalid_dashboard_edit") from exc


def row_snapshot(row: Any) -> dict[str, Any]:
    # Only statically reviewed tables reach this helper. No relationship loading,
    # file content, upload credentials or temporary URLs enter retained history.
    return safe_result(
        {
            column.key: getattr(row, column.key)
            for column in row.__table__.columns
            if column.key not in PRIVATE_FIELDS
        }
    )


def preserve_unspecified_edit(name: str, body: BaseModel, row: Any) -> BaseModel:
    fields = {
        "configure_group_link": GROUP_CONFIGURATION_FIELDS,
        "update_menu_dish": ("notes", "is_active"),
        "update_meal_plan": ("start_date",),
        "configure_rooming_hotel": ("city", "check_in_date", "check_out_date"),
    }.get(name, ())
    supplied = body.model_dump(mode="json", exclude_unset=True)
    current = {key: safe_result(getattr(row, key)) for key in fields if key not in supplied}
    merged = {**current, **supplied}
    try:
        if name == "configure_group_link":
            canonical = UpdateClientGroupRequest.model_validate(
                {key: merged[key] for key in GROUP_CONFIGURATION_FIELDS}
            )
            merged.update(canonical.model_dump(mode="json"))
        return EDIT_MODELS[name].model_validate(merged)
    except ValidationError as exc:
        raise MCPOperationError("invalid_dashboard_edit") from exc


async def target_row(context: MCPDatabaseContext, name: str, body: BaseModel, *, lock: bool):
    model, key = TARGETS[name]
    query = select(model).where(model.id == getattr(body, key))
    if model is MenuDishModel:
        query = query.join(MenuCategoryModel).where(MenuCategoryModel.agency_id == body.agency_id)
    else:
        query = query.where(model.agency_id == body.agency_id)
    if model is ClientGroupModel:
        query = query.where(model.deleted_at.is_(None), model.status != "deleted")
    if model is RoomingHotelModel:
        query = query.where(model.group_id == body.group_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await context.session.scalar(query)
    if row is None:
        raise MCPOperationError("workflow_resource_unavailable")
    return row


async def before_state(context: MCPDatabaseContext, name: str, body: BaseModel, row: Any):
    history: dict[str, Any] = {"target": row_snapshot(row)}
    if isinstance(row, RoomingHotelModel):
        # Group lock precedes hotel locks, matching canonical allocation order.
        for model, key in (
            (RoomingHotelModel, "hotels"),
            (RoomingHotelPassengerModel, "selections"),
        ):
            rows = list(
                (
                    await context.session.scalars(
                        select(model)
                        .where(
                            model.group_id == body.group_id,
                            model.agency_id == body.agency_id,
                        )
                        .order_by(model.id)
                        .limit(1001)
                        .with_for_update()
                    )
                ).all()
            )
            if len(rows) > 1000:
                raise MCPOperationError("workflow_history_limit")
            history[key] = [row_snapshot(item) for item in rows]
        hotel_ids = [UUID(item["id"]) for item in history["hotels"]]
        for model, key in ((RoomingRoomModel, "rooms"), (RoomingAssignmentModel, "assignments")):
            rows = list(
                (
                    await context.session.scalars(
                        select(model)
                        .where(model.hotel_id.in_(hotel_ids))
                        .order_by(model.id)
                        .limit(1001)
                        .with_for_update()
                    )
                ).all()
            )
            if len(rows) > 1000:
                raise MCPOperationError("workflow_history_limit")
            history[key] = [row_snapshot(item) for item in rows]
    elif isinstance(row, MealPlanModel):
        entries = list(
            (
                await context.session.scalars(
                    select(MealPlanEntryModel)
                    .where(MealPlanEntryModel.plan_id == row.id)
                    .order_by(MealPlanEntryModel.id)
                    .limit(1001)
                    .with_for_update()
                )
            ).all()
        )
        if len(entries) > 1000:
            raise MCPOperationError("workflow_history_limit")
        history["entries"] = [row_snapshot(item) for item in entries]
    if len(json.dumps(history, ensure_ascii=False).encode("utf-8")) > MAX_RESULT_BYTES:
        raise MCPOperationError("workflow_history_limit")
    return history


async def canonical_edit(context: MCPDatabaseContext, name: str, body: BaseModel, actor):
    common = {"current_user": actor, "session": context.session, "request": audit_request()}
    if name == "configure_group_link":
        return await client_groups.update_client_group(
            link_id=body.group_id,
            request=body,
            current_user=actor,
            session=context.session,
        )
    if name == "update_menu_category":
        return await menu.update_menu_category(category_id=body.category_id, body=body, **common)
    if name == "update_menu_dish":
        return await menu.update_menu_dish(dish_id=body.dish_id, body=body, **common)
    if name == "update_meal_plan":
        return await menu.update_meal_plan(plan_id=body.plan_id, body=body, **common)
    if name == "update_meal_plan_entry":
        return await menu.update_meal_plan_entry(
            plan_id=body.plan_id, entry_id=body.entry_id, body=body, **common
        )
    handlers = {
        "configure_rooming_hotel": rooming.update_rooming_hotel,
        "select_rooming_passengers": rooming.update_hotel_passenger_selection,
        "set_rooming_vip": rooming.update_hotel_vip_status,
        "allocate_rooming_rooms": rooming.auto_allocate_hotel_rooms,
    }
    return await handlers[name](hotel_id=body.hotel_id, body=body, **common)


def dashboard_edit_operation(name: str) -> MCPDatabaseOperation:
    if name not in EDIT_MODELS:
        raise ValueError("Unsupported dashboard edit")

    async def mutate(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        body = validate_edit(name, payload)
        actor = await scoped_actor(context, body.agency_id)
        if hasattr(body, "group_id"):
            await require_change_group(
                context, actor, body.group_id, body.agency_id, exclusive=True
            )
        if name == "configure_group_link":
            await lock_group_revision(
                context, body.agency_id, body.group_id, body.expected_configuration_revision
            )
        row = await target_row(context, name, body, lock=True)
        if name == "configure_rooming_hotel" and utc(row.updated_at) != utc(
            body.expected_updated_at
        ):
            raise MCPOperationError("workflow_revision_changed")
        body = preserve_unspecified_edit(name, body, row)
        history = await before_state(context, name, body, row)
        try:
            result = safe_result(await canonical_edit(context, name, body, actor))
        except HTTPException as exc:
            raise public_failure(exc) from exc
        # Do not retain whole rosters/room plans in operation responses. The
        # canonical dashboard provides the detailed current projection.
        if name.startswith(("select_rooming", "set_rooming", "allocate_rooming")):
            result = {
                key: result[key]
                for key in ("group_id", "changed", "current_revisions")
                if key in result
            }
        if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > MAX_RESULT_BYTES:
            raise MCPOperationError("workflow_result_limit")
        audit = await AuditLogRepository(context.session).record(
            action="mcp.dashboard_edit",
            entity_type=row.__tablename__,
            entity_id=str(row.id),
            agency_id=body.agency_id,
            user_id=actor.id,
            actor_email=actor.email,
            metadata={
                "mcp_operation_id": str(context.operation_id),
                "workflow": name,
                "retained_before": history,
            },
        )
        return MCPDatabaseResult(
            {
                "agency_id": str(body.agency_id) if body.agency_id else None,
                "target_id": str(row.id),
                "group_id": str(body.group_id) if hasattr(body, "group_id") else None,
                "workflow": name,
                "business_audit_id": str(audit.id),
                "result": result,
            }
        )

    async def authorize_receipt(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        data = receipt["data"]
        agency_id = UUID(data["agency_id"]) if data["agency_id"] else None
        actor = await scoped_actor(context, agency_id)
        model, key = TARGETS[name]
        query = select(model.id).where(model.id == UUID(data["target_id"]))
        if model is MenuDishModel:
            query = query.join(MenuCategoryModel).where(MenuCategoryModel.agency_id == agency_id)
        else:
            query = query.where(model.agency_id == agency_id)
        if data["group_id"]:
            await require_change_group(context, actor, UUID(data["group_id"]), agency_id)
            if model is RoomingHotelModel:
                query = query.where(model.group_id == UUID(data["group_id"]))
        if await context.session.scalar(query) is None:
            raise MCPOperationError("workflow_receipt_unavailable")

    return MCPDatabaseOperation(
        MCPToolPolicy(name, MCPCapability.CHANGE, frozenset({"edit_with_retained_history"})),
        mutate,
        authorize_receipt,
    )
