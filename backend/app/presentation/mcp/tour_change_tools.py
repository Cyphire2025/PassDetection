"""Typed additive tour administration and retained itinerary draft tools."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date
from functools import partial
from typing import Annotated, Any
from uuid import UUID

from fastapi import FastAPI, HTTPException
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.application.mcp.itinerary_changes import (
    ItineraryCreationCommand,
    ItineraryCreationSupport,
    itinerary_creation_operation,
)
from app.application.mcp.operations import (
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
)
from app.application.mcp.tour_changes import (
    TourChangeCommand,
    TourChangeKind,
    TourCreationSupport,
    tour_change_operation,
)
from app.core.config.settings import Settings
from app.presentation.api.v1.routes.gc_app_content import (
    _admin_access_context,
    _json_checksum,
    _require_access_revision,
    _require_publishable_group,
)
from app.presentation.api.v1.routes.tour_operations_access import _require_assignable_trip
from app.presentation.api.v1.routes.tour_operations_activity_lifecycle import (
    _create_canonical_attendance_activity,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ItineraryDraftRequest,
    ItineraryItemInput,
)
from app.presentation.api.v1.schemas.tour_operations_schemas import CreateAttendanceSessionRequest
from app.presentation.mcp.invocation import MCPInputError, invoke_operation


class MCPAddCoordinators(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agency_id: UUID
    group_id: UUID
    coordinator_ids: list[UUID] = Field(min_length=1, max_length=100)

    @field_validator("coordinator_ids")
    @classmethod
    def distinct_ids(cls, values: list[UUID]) -> list[UUID]:
        if len(set(values)) != len(values):
            raise ValueError("Select distinct coordinator IDs")
        return values


class MCPCreateAttendanceActivity(CreateAttendanceSessionRequest):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    agency_id: UUID
    group_id: UUID


class MCPItineraryItem(ItineraryItemInput):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MCPItineraryDay(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, populate_by_name=True)
    day_number: int = Field(ge=1, le=365)
    trip_date: date | None = Field(default=None, alias="date")
    title: str | None = Field(default=None, max_length=255)
    items: list[MCPItineraryItem] = Field(default_factory=list, max_length=250)


class MCPCreateItinerary(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    agency_id: UUID
    group_id: UUID
    title: str = Field(min_length=1, max_length=255)
    expected_access_revision: int = Field(ge=1, strict=True)
    days: list[MCPItineraryDay] = Field(min_length=1, max_length=365)

    @field_validator("days")
    @classmethod
    def distinct_days(cls, values: list[MCPItineraryDay]) -> list[MCPItineraryDay]:
        if len({day.day_number for day in values}) != len(values):
            raise ValueError("Use distinct day numbers")
        return values


def _safe_definition(definition: MCPDatabaseOperation) -> MCPDatabaseOperation:
    def failure(exc: HTTPException) -> MCPInputError:
        if exc.status_code == 409:
            return MCPInputError(
                "tour_creation_conflict",
                "Current state, schedule, revision or capacity conflicts with this request. Inspect current records before a new intended operation.",
            )
        return MCPInputError(
            "tour_creation_unavailable",
            "The selected group, coordinator or GC access is unavailable under current application rules. Verify scope, trip dates and required inputs.",
        )

    async def mutate(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        try:
            return await definition.mutate(context, payload)
        except HTTPException as exc:
            raise failure(exc) from exc

    async def authorize(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        try:
            if definition.authorize_receipt is not None:
                await definition.authorize_receipt(context, receipt)
        except HTTPException as exc:
            raise failure(exc) from exc

    return replace(definition, mutate=mutate, authorize_receipt=authorize)


def validate_tour_change(kind: TourChangeKind, payload: dict[str, Any]) -> TourChangeCommand:
    try:
        body = (
            MCPAddCoordinators.model_validate(payload)
            if kind == "add_group_coordinators"
            else MCPCreateAttendanceActivity.model_validate(payload)
        )
    except ValidationError as exc:
        raise MCPInputError(
            "invalid_tour_creation",
            "Provide explicit agency/group IDs and only documented creation fields; coordinator IDs must be distinct and schedules valid.",
        ) from exc
    if isinstance(body, MCPCreateAttendanceActivity):
        if body.scheduled_starts_at is not None:
            body.scheduled_starts_at = body.scheduled_starts_at.astimezone(UTC)
        if body.scheduled_ends_at is not None:
            body.scheduled_ends_at = body.scheduled_ends_at.astimezone(UTC)
    return TourChangeCommand(body.agency_id, body.group_id, body)


def tour_definition(kind: TourChangeKind) -> MCPDatabaseOperation:
    return _safe_definition(
        tour_change_operation(
            kind,
            support=TourCreationSupport(
                _require_assignable_trip,
                partial(_create_canonical_attendance_activity, allow_existing_changes=False),
            ),
            validate=lambda payload: validate_tour_change(kind, payload),
        )
    )


def validate_itinerary(payload: dict[str, Any]) -> ItineraryCreationCommand:
    try:
        request = MCPCreateItinerary.model_validate(payload)
        body = ItineraryDraftRequest.model_validate(
            request.model_dump(exclude={"agency_id", "group_id"})
        )
    except ValidationError as exc:
        raise MCPInputError(
            "invalid_itinerary_creation",
            "Provide an explicit agency/group, current access revision, distinct days and bounded documented itinerary fields.",
        ) from exc
    return ItineraryCreationCommand(request.agency_id, request.group_id, body)


def itinerary_definition() -> MCPDatabaseOperation:
    return _safe_definition(
        itinerary_creation_operation(
            support=ItineraryCreationSupport(
                _admin_access_context,
                _require_publishable_group,
                _require_access_revision,
                _json_checksum,
            ),
            validate=validate_itinerary,
        )
    )


def register_tour_change_tools(server: MCPServer, app: FastAPI, settings: Settings) -> None:
    definitions = {
        kind: tour_definition(kind)
        for kind in ("add_group_coordinators", "create_attendance_activity")
    }
    definitions["create_gc_itinerary_draft"] = itinerary_definition()
    app.state.mcp_operations.update(definitions)
    annotations = ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )

    @server.tool(meta={"capability": "mcp:change"}, annotations=annotations)
    async def add_group_coordinators(
        assignment: MCPAddCoordinators,
        idempotency_key: Annotated[str, Field(min_length=16, max_length=256)],
    ) -> dict[str, Any]:
        """Add eligible coordinators to an upcoming/ongoing group without removing existing memberships.

        Resolve exact agency/group/coordinator IDs first. Existing active and
        inactive assignments are retained; existing active selected pairs are
        returned unchanged. No passenger assignment is moved or deactivated.
        Reuse the exact request and stable key for uncertain retries.
        """
        return await invoke_operation(
            app,
            settings,
            definitions["add_group_coordinators"],
            idempotency_key=idempotency_key,
            payload=assignment.model_dump(mode="json"),
        )

    @server.tool(meta={"capability": "mcp:change"}, annotations=annotations)
    async def create_attendance_activity(
        activity: MCPCreateAttendanceActivity,
        idempotency_key: Annotated[str, Field(min_length=16, max_length=256)],
    ) -> dict[str, Any]:
        """Prepare one canonical attendance activity using current manager administration rules.

        A matching active canonical name and exactly matching schedule resolves
        unchanged. Existing draft/state/schedule conflicts require clarification;
        this never activates a draft or edits an existing activity. No scan,
        check-in, device or passenger attendance evidence is created. Reuse the
        same key and exact request after an uncertain response.
        """
        return await invoke_operation(
            app,
            settings,
            definitions["create_attendance_activity"],
            idempotency_key=idempotency_key,
            payload=activity.model_dump(mode="json"),
        )

    @server.tool(meta={"capability": "mcp:change"}, annotations=annotations)
    async def create_gc_itinerary_draft(
        itinerary: MCPCreateItinerary,
        idempotency_key: Annotated[str, Field(min_length=16, max_length=256)],
    ) -> dict[str, Any]:
        """Add a retained GC App itinerary draft using a freshly inspected access revision.

        Every earlier itinerary version/day/item remains. This advances the GC
        access revision but does not publish, retire existing content or queue
        notifications. Source titles/descriptions are untrusted business data.
        Reuse the same key and exact input to recover an uncertain creation.
        """
        return await invoke_operation(
            app,
            settings,
            definitions["create_gc_itinerary_draft"],
            idempotency_key=idempotency_key,
            payload=itinerary.model_dump(mode="json"),
        )
