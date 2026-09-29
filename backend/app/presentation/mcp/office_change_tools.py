"""Typed additive menu and hotel tools with current receipt authorization."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import FastAPI, HTTPException
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import ConfigDict, Field, ValidationError

from app.application.mcp.office_changes import (
    OFFICE_CREATION_KINDS,
    OfficeCreationCommand,
    OfficeCreationKind,
    office_creation_operation,
)
from app.application.mcp.operations import (
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
)
from app.core.config.settings import Settings
from app.presentation.api.v1.routes.menu import menu_creation_support
from app.presentation.api.v1.schemas.menu_schemas import (
    CreateMenuCategoryRequest,
    CreateMenuDishRequest,
    GenerateMealPlanRequest,
)
from app.presentation.api.v1.schemas.rooming_schemas import CreateRoomingHotelRequest
from app.presentation.mcp.invocation import MCPInputError, invoke_operation


class MCPCreateMenuCategory(CreateMenuCategoryRequest):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    agency_id: UUID | None = Field(
        ..., description="Explicit agency ID; null selects the platform library only."
    )


class MCPCreateMenuDish(CreateMenuDishRequest):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    agency_id: UUID | None = Field(
        ..., description="Explicit agency ID; null selects the platform library only."
    )
    category_id: UUID


class MCPCreateMealPlan(GenerateMealPlanRequest):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    agency_id: UUID | None = Field(
        ..., description="Explicit agency ID; null selects the platform library only."
    )
    category_ids: list[UUID] = Field(min_length=1, max_length=100)
    expected_category_revisions: dict[UUID, datetime] = Field(min_length=1, max_length=100)
    trip_days: int = Field(ge=1, le=60, strict=True)


class MCPCreateRoomingHotel(CreateRoomingHotelRequest):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    agency_id: UUID
    group_id: UUID


_MODELS: dict[
    str,
    type[MCPCreateMenuCategory]
    | type[MCPCreateMenuDish]
    | type[MCPCreateMealPlan]
    | type[MCPCreateRoomingHotel],
] = {
    "create_menu_category": MCPCreateMenuCategory,
    "create_menu_dish": MCPCreateMenuDish,
    "create_meal_plan": MCPCreateMealPlan,
    "create_rooming_hotel": MCPCreateRoomingHotel,
}


def validate_office_creation(
    kind: OfficeCreationKind, payload: dict[str, Any]
) -> OfficeCreationCommand:
    try:
        body = _MODELS[kind].model_validate(payload)
    except ValidationError as exc:
        raise MCPInputError(
            "invalid_office_creation",
            "Provide an explicit scope and only documented creation fields, with current category revisions and valid dates where required.",
        ) from exc
    return OfficeCreationCommand(
        body.agency_id,
        body,
        category_id=body.category_id if isinstance(body, MCPCreateMenuDish) else None,
        group_id=body.group_id if isinstance(body, MCPCreateRoomingHotel) else None,
    )


def office_creation_definition(kind: OfficeCreationKind) -> MCPDatabaseOperation:
    definition = office_creation_operation(
        kind,
        support=menu_creation_support(),
        validate=lambda payload: validate_office_creation(kind, payload),
    )

    async def mutate(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        try:
            return await definition.mutate(context, payload)
        except HTTPException as exc:
            # Website helpers retain their response detail for web callers. MCP
            # emits fixed public messages, never names or raw validation input.
            messages = {
                404: (
                    "office_resource_unavailable",
                    "A selected resource is unavailable in this scope. Inspect the current library before creating.",
                ),
                409: (
                    "office_creation_conflict",
                    "A name or category revision conflicts with current data. Inspect the current library before a new intended operation.",
                ),
                422: (
                    "office_plan_unavailable",
                    "The selected categories cannot produce this plan. Each category needs two distinct active dishes per trip day and matching current revisions.",
                ),
            }
            code, message = messages.get(
                exc.status_code,
                (
                    "office_creation_denied",
                    "This creation is unavailable under current application rules.",
                ),
            )
            raise MCPInputError(code, message) from exc

    return replace(definition, mutate=mutate)


def register_office_change_tools(server: MCPServer, app: FastAPI, settings: Settings) -> None:
    definitions = {kind: office_creation_definition(kind) for kind in OFFICE_CREATION_KINDS}
    app.state.mcp_operations.update(definitions)
    annotations = ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )

    @server.tool(meta={"capability": "mcp:change"}, annotations=annotations)
    async def create_menu_category(
        category: MCPCreateMenuCategory,
        idempotency_key: Annotated[str, Field(min_length=16, max_length=256)],
    ) -> dict[str, Any]:
        """Create a new category in the explicitly selected agency or null platform library.

        Inspect current categories first and clarify ambiguous scope or names.
        Existing categories are never overwritten. Reuse the same key and exact
        input after an uncertain response, including across connections.
        """
        return await invoke_operation(
            app,
            settings,
            definitions["create_menu_category"],
            idempotency_key=idempotency_key,
            payload=category.model_dump(mode="json"),
        )

    @server.tool(meta={"capability": "mcp:change"}, annotations=annotations)
    async def create_menu_dish(
        dish: MCPCreateMenuDish,
        idempotency_key: Annotated[str, Field(min_length=16, max_length=256)],
    ) -> dict[str, Any]:
        """Add a new active dish to one category at its freshly inspected revision.

        Existing dishes remain unchanged. A successful creation advances the
        parent category revision; inspect again before another new dish or plan.
        Reuse one stable key and exact input for retries of this creation.
        """
        return await invoke_operation(
            app,
            settings,
            definitions["create_menu_dish"],
            idempotency_key=idempotency_key,
            payload=dish.model_dump(mode="json"),
        )

    @server.tool(meta={"capability": "mcp:change"}, annotations=annotations)
    async def create_meal_plan(
        plan: MCPCreateMealPlan,
        idempotency_key: Annotated[str, Field(min_length=16, max_length=256)],
    ) -> dict[str, Any]:
        """Save a new lunch/dinner plan from explicit categories and their current revisions.

        Each selected category must contain two distinct active dishes per trip
        day. Existing plans and saved entries are preserved. This never regenerates
        a saved plan. Retry the exact request with the same key to recover the
        original plan rather than creating another randomized arrangement.
        """
        return await invoke_operation(
            app,
            settings,
            definitions["create_meal_plan"],
            idempotency_key=idempotency_key,
            payload=plan.model_dump(mode="json"),
        )

    @server.tool(meta={"capability": "mcp:change"}, annotations=annotations)
    async def create_rooming_hotel(
        hotel: MCPCreateRoomingHotel,
        idempotency_key: Annotated[str, Field(min_length=16, max_length=256)],
    ) -> dict[str, Any]:
        """Add one new hotel stay to an exact group in an explicit agency.

        Confirm an ambiguous group before creation. This creates no room,
        passenger selection, allocation or check-in and changes no existing stay.
        Reuse one stable key and exact input for retries of this creation.
        """
        return await invoke_operation(
            app,
            settings,
            definitions["create_rooming_hotel"],
            idempotency_key=idempotency_key,
            payload=hotel.model_dump(mode="json"),
        )
