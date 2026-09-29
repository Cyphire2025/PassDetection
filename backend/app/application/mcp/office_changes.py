"""Additive office configuration through shared website creation use cases."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select

from app.application.mcp.change_context import require_change_actor as _actor
from app.application.mcp.change_context import require_change_group as _group
from app.application.mcp.credentials import utc
from app.application.mcp.operations import (
    MCPCreatedEntity,
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
)
from app.application.use_cases.menu.create_menu import (
    MenuCreationSupport,
    create_category,
    create_dish,
    create_plan,
)
from app.application.use_cases.rooming.create_hotel import create_hotel
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.menu_models import MealPlanModel, MenuCategoryModel, MenuDishModel
from app.infrastructure.database.models import (
    RoomingHotelModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository

OfficeCreationKind = Literal[
    "create_menu_category", "create_menu_dish", "create_meal_plan", "create_rooming_hotel"
]
OFFICE_CREATION_KINDS: tuple[OfficeCreationKind, ...] = (
    "create_menu_category",
    "create_menu_dish",
    "create_meal_plan",
    "create_rooming_hotel",
)


@dataclass(frozen=True, slots=True)
class OfficeCreationCommand:
    agency_id: uuid.UUID | None
    body: Any
    category_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None




def office_creation_operation(
    kind: OfficeCreationKind,
    *,
    support: MenuCreationSupport,
    validate: Callable[[dict[str, Any]], OfficeCreationCommand],
) -> MCPDatabaseOperation:
    if kind not in OFFICE_CREATION_KINDS:
        raise ValueError("Unsupported office creation")
    policy = MCPToolPolicy(kind, MCPCapability.CHANGE, frozenset({kind}))

    async def create(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        command = validate(payload)
        actor = await _actor(context, command.agency_id)
        common = {
            "session": context.session,
            "support": support,
            "agency_id": command.agency_id,
            "actor_id": actor.id,
            "body": command.body,
        }
        data: dict[str, Any] = {"agency_id": str(command.agency_id) if command.agency_id else None}
        entity: MenuCategoryModel | MenuDishModel | MealPlanModel | RoomingHotelModel
        if kind == "create_menu_category":
            category = await create_category(**common)
            entity, action, path = category, "menu.category_created", "/menu"
            entity_type = "menu_category"
            data.update(
                category_id=str(category.id), updated_at=utc(category.updated_at).isoformat()
            )
        elif kind == "create_menu_dish":
            if command.category_id is None:
                raise MCPOperationError("office_category_required")
            dish, category = await create_dish(**common, category_id=command.category_id)
            entity, action, path = dish, "menu.dish_created", "/menu"
            entity_type = "menu_dish"
            data.update(
                dish_id=str(dish.id),
                category_id=str(category.id),
                category_updated_at=utc(category.updated_at).isoformat(),
            )
        elif kind == "create_meal_plan":
            plan, entries = await create_plan(**common)
            entity, action, path = plan, "menu.meal_plan_generated", "/menu"
            entity_type = "meal_plan"
            data.update(
                plan_id=str(plan.id),
                entry_count=len(entries),
                updated_at=utc(plan.updated_at).isoformat(),
            )
        else:
            if command.agency_id is None or command.group_id is None:
                raise MCPOperationError("office_group_required")
            group = await _group(context, actor, command.group_id, command.agency_id)
            hotel = await create_hotel(
                context.session,
                agency_id=group.agency_id,
                group_id=group.id,
                actor_id=actor.id,
                body=command.body,
            )
            entity, action, path = hotel, "rooming.hotel_created", f"/rooming/{group.id}"
            entity_type = "rooming_hotel"
            data.update(
                hotel_id=str(hotel.id),
                group_id=str(group.id),
                rooms_created=0,
                passenger_selections_created=0,
                allocations_created=0,
            )
        audit = await AuditLogRepository(context.session).record(
            action=action,
            entity_type=entity_type,
            entity_id=str(entity.id),
            agency_id=command.agency_id,
            user_id=actor.id,
            actor_email=actor.email,
            metadata={"mcp_operation_id": str(context.operation_id), **data},
        )
        data["business_audit_id"] = str(audit.id)
        return MCPDatabaseResult(
            data, created_entities=(MCPCreatedEntity(entity_type, str(entity.id), path),)
        )

    async def authorize_receipt(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        data = receipt["data"]
        agency_id = uuid.UUID(data["agency_id"]) if data["agency_id"] is not None else None
        actor = await _actor(context, agency_id)
        session = context.session
        # Query predicates recheck the current association; a retained receipt is
        # not authority to disclose an entity moved or deleted after creation.
        if kind == "create_menu_category":
            entity_id = await session.scalar(
                select(MenuCategoryModel.id).where(
                    MenuCategoryModel.id == uuid.UUID(data["category_id"]),
                    MenuCategoryModel.agency_id == agency_id,
                )
            )
        elif kind == "create_menu_dish":
            entity_id = await session.scalar(
                select(MenuDishModel.id)
                .join(MenuCategoryModel)
                .where(
                    MenuDishModel.id == uuid.UUID(data["dish_id"]),
                    MenuDishModel.category_id == uuid.UUID(data["category_id"]),
                    MenuCategoryModel.agency_id == agency_id,
                )
            )
        elif kind == "create_meal_plan":
            entity_id = await session.scalar(
                select(MealPlanModel.id).where(
                    MealPlanModel.id == uuid.UUID(data["plan_id"]),
                    MealPlanModel.agency_id == agency_id,
                )
            )
        else:
            if agency_id is None:
                raise MCPOperationError("office_receipt_unavailable")
            group = await _group(context, actor, uuid.UUID(data["group_id"]), agency_id)
            entity_id = await session.scalar(
                select(RoomingHotelModel.id).where(
                    RoomingHotelModel.id == uuid.UUID(data["hotel_id"]),
                    RoomingHotelModel.group_id == group.id,
                    RoomingHotelModel.agency_id == agency_id,
                )
            )
        if entity_id is None:
            raise MCPOperationError("office_receipt_unavailable")

    return MCPDatabaseOperation(policy, create, authorize_receipt)
