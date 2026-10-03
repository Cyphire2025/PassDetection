"""Fixed dashboard readers with canonical schemas and bounded field navigation."""

from __future__ import annotations

import importlib
import inspect
import json
from dataclasses import replace
from typing import Annotated, Any, get_type_hints
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.params import Depends, Param
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field, StrictInt, StrictStr, TypeAdapter, ValidationError
from pydantic_core import PydanticUndefined
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.permissions import current_device_read_access
from app.application.mcp.read_access import MCPReadSectionDenied
from app.application.mcp.read_context import MCPReadContext
from app.application.mcp.read_projection import ReadProjection
from app.core.config.settings import Settings
from app.domain.exceptions.exceptions import AuthorizationError
from app.domain.mcp_dashboard_reads import DASHBOARD_READS, DashboardRead
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.models import (
    AttendanceSessionModel,
    PassportSubmissionModel,
    RoomingHotelModel,
    WhatsAppBroadcastGroupModel,
)
from app.presentation.mcp.invocation import MCPInputError, invoke_read
from app.presentation.mcp.observational_session import observational_session

INJECTED = frozenset({"current_user", "session", "request", "response", "use_case"})


def dashboard_handler(definition: DashboardRead):
    if definition.handler.startswith("@"):
        module = importlib.import_module("app.presentation.mcp.dashboard_read_adapters")
        return getattr(module, definition.handler[1:])
    module_name, name = definition.handler.rsplit(".", 1)
    return getattr(importlib.import_module("app.presentation.api.v1.routes." + module_name), name)


def dashboard_parameters(definition: DashboardRead) -> dict[str, Any]:
    function = dashboard_handler(definition)
    hints = get_type_hints(function, include_extras=True)
    properties, required = {}, []
    for name, parameter in inspect.signature(function).parameters.items():
        if name in INJECTED:
            continue
        annotation = hints[name]
        default = parameter.default
        if isinstance(default, Param):
            annotation = Annotated[annotation, default]
            default = default.default
        if isinstance(default, Depends):
            raise RuntimeError("An unreviewed dependency entered the dashboard read catalog")
        properties[name] = TypeAdapter(annotation).json_schema()
        if default is inspect.Parameter.empty or default is PydanticUndefined:
            required.append(name)
        elif default is not None:
            properties[name]["default"] = default
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def validate_dashboard_parameters(definition: DashboardRead, parameters: dict[str, Any]) -> dict[str, Any]:
    if len(parameters) > 30 or len(json.dumps(parameters, default=str)) > 16000:
        raise ValueError("Dashboard parameters exceed the input limit")
    function = dashboard_handler(definition)
    signature = inspect.signature(function)
    if set(parameters) - (set(signature.parameters) - INJECTED):
        raise ValueError("Use only the documented dashboard view parameters")
    hints = get_type_hints(function, include_extras=True)
    arguments = {}
    for name, parameter in signature.parameters.items():
        if name in INJECTED:
            continue
        annotation, default = hints[name], parameter.default
        if isinstance(default, Param):
            annotation, default = Annotated[annotation, default], default.default
        if name not in parameters and (default is inspect.Parameter.empty or default is PydanticUndefined):
            raise ValueError("Provide the required parameters listed by list_dashboard_read_views")
        value = parameters.get(name, default)
        if isinstance(value, Depends):
            raise ValueError("This view has an unreviewed dependency")
        try:
            arguments[name] = TypeAdapter(annotation).validate_json(json.dumps(value, default=str), strict=True)
        except (ValidationError, ValueError, TypeError):
            raise ValueError("A dashboard parameter does not match its documented type or bounds") from None
        if name in {"limit", "page_size"} and arguments[name] > 100:
            raise ValueError("Dashboard read page sizes are limited to 100")
    return arguments


async def read_dashboard(app: FastAPI, settings: Settings, session: AsyncSession,
    principal: MCPPrincipal, *, view: str, parameters: dict[str, Any], agency_id: UUID | None,
    data_path: list[str | int], page_size: int, cursor: str | None) -> dict[str, Any]:
    definition = DASHBOARD_READS.get(view)
    if definition is None:
        raise MCPInputError("unknown_dashboard_view", "Choose a view from list_dashboard_read_views")
    allowed, revision = await current_device_read_access(session, principal.grant_id, lock=True)
    if definition.sections - set(allowed):
        # The generic tool has no static business domain; every selected view
        # separately enforces its complete live section union before loading.
        raise MCPReadSectionDenied(definition.sections)
    try:
        arguments = validate_dashboard_parameters(definition, parameters)
        context = MCPReadContext(session, cursor_secret=settings.app_secret_key, namespace="mcp-dashboard-v1")
        actor = await context._actor(principal.user_id, page_size)
        explicit_agency = arguments.get("agency_id")
        if agency_id is not None and explicit_agency is not None and agency_id != explicit_agency:
            raise ValueError("The agency context and view agency must agree")
        selected_agency = agency_id or explicit_agency
        await context._agency(selected_agency)
        if definition.group_parameter and arguments.get(definition.group_parameter) is not None:
            identifier = arguments[definition.group_parameter]
            group = await context._group(actor, identifier, selected_agency, include_deleted=True)
            selected_agency = group.agency_id
        resource_model = (PassportSubmissionModel if view.startswith("passport_") and "submission_id" in arguments
            else RoomingHotelModel if view == "hotel_checkins" else AttendanceSessionModel if view == "my_tour_session" else None)
        if resource_model is not None:
            resource_key = "submission_id" if resource_model is PassportSubmissionModel else "hotel_id" if resource_model is RoomingHotelModel else "session_id"
            resource_agency = await session.scalar(select(resource_model.agency_id).where(resource_model.id == arguments[resource_key]))
            if resource_agency is None or selected_agency is not None and selected_agency != resource_agency:
                raise ValueError("The resource was not found in the requested agency")
            selected_agency = resource_agency
        if view in {"whatsapp_tracking", "whatsapp_broadcast_details", "whatsapp_source_contacts", "whatsapp_broadcast_stored", "whatsapp_broadcast_records"}:
            statement = select(WhatsAppBroadcastGroupModel.agency_id).where(WhatsAppBroadcastGroupModel.id == arguments["group_id"])
            broadcast_agency = await session.scalar(statement)
            if broadcast_agency is None or selected_agency is not None and broadcast_agency != selected_agency:
                raise ValueError("The broadcast was not found in the requested agency")
            selected_agency = broadcast_agency
        if selected_agency is not None:
            actor = replace(actor, agency_id=selected_agency)
            if "agency_id" in arguments and arguments["agency_id"] is None:
                arguments["agency_id"] = selected_agency
        function = dashboard_handler(definition)
        injected = {"current_user": actor, "session": session,
            "response": Response(), "request": Request({"type": "http", "method": "GET",
                "path": "/mcp/dashboard-read", "headers": [], "query_string": b"",
                "app": app, "client": ("127.0.0.1", 0)})}
        if "use_case" in inspect.signature(function).parameters:
            if view != "group_links":
                raise RuntimeError("Unreviewed read dependency")
            module = importlib.import_module("app.presentation.api.v1.routes.client_groups")
            injected["use_case"] = module._get_list_use_case(session)
        async with observational_session(session):
            try:
                value = await function(**arguments, **{key: item for key, item in injected.items()
                    if key in inspect.signature(function).parameters})
            except ValueError:
                raise MCPInputError("dashboard_query_rejected", "The website rejected this dashboard query; review its documented filters and resource scope") from None
        if isinstance(value, Response):
            if value.status_code >= 400:
                raise ValueError("The website rejected this dashboard query; review its documented parameters")
            value = json.loads(value.body)
        result = ReadProjection(settings.app_secret_key).page(value,
            binding={"actor": str(principal.user_id), "view": view, "parameters": parameters,
                "agency_id": str(selected_agency), "read_access_revision": revision},
            data_path=data_path, page_size=page_size, cursor=cursor)
        result.update(view=view, required_sections=sorted(definition.sections),
            source="reviewed_dashboard_read", read_access_revision=revision)
        source = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        source_page = {}
        if isinstance(source, dict):
            source_page = {key: source[key] for key in ("has_more", "next_cursor", "next_offset", "page", "page_size", "total_pages", "total", "total_count", "incomplete", "truncated") if key in source}
        if isinstance(source, list) and "limit" in arguments:
            source_page = {"returned_count": len(source), "limit": arguments["limit"],
                "possibly_more": len(source) >= arguments["limit"]}
        if source_page:
            result["website_pagination"] = source_page
            if (source_page.get("has_more") or source_page.get("next_cursor") or source_page.get("next_offset") is not None or source_page.get("incomplete") or source_page.get("possibly_more") or source_page.get("truncated")
                    or source_page.get("page", 1) < source_page.get("total_pages", 1)):
                result["completeness"] = "partial"
        if view == "document_delivery_summary":
            result["count_notice"] = "The website's sent counter combines submitted/provider acceptance and sent. Only delivered/read confirm delivery. list_delivery_records returns the distinct stored attempt statuses."
            result["full_history_tool"] = "list_delivery_records"
            if isinstance(source, dict) and source.get("counts", {}).get("total", 0) > len(source.get("deliveries", [])):
                result["completeness"] = "partial"
        return result
    except MCPInputError:
        raise
    except ValueError as exc:
        raise MCPInputError("invalid_dashboard_read", str(exc)) from exc
    except AuthorizationError:
        raise MCPAuthError("access_denied", 403) from None
    except HTTPException as exc:
        if exc.status_code in {401, 403}:
            raise MCPAuthError("access_denied", 403) from None
        raise MCPInputError("dashboard_view_unavailable", "The requested dashboard view is unavailable in this scope or requires different parameters") from None


def register_dashboard_read_tools(server: MCPServer, app: FastAPI, settings: Settings) -> None:
    annotations = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)

    @server.tool(annotations=annotations, meta={"capability": "mcp:read"})
    async def list_dashboard_read_views(section: str | None = None,
        view: str | None = None,
        offset: Annotated[int, Field(ge=0, le=1000)] = 0,
        page_size: Annotated[int, Field(ge=1, le=25)] = 10) -> dict[str, Any]:
        """Discover complete dashboard read views, descriptions, parameter schemas and live section permissions.

        Use read_dashboard_view for fields absent from a summary tool: staff codes,
        passport expiry alerts, document delivery, WhatsApp unidentified uploads,
        rooming remarks, custom answers, settings and audit history. Metadata is
        not business read authority; each chosen view independently rechecks it.
        """
        async def read(session: AsyncSession, _principal: MCPPrincipal):
            allowed, revision = await current_device_read_access(session, _principal.grant_id)
            selected = [(name, definition) for name, definition in sorted(DASHBOARD_READS.items())
                if (section is None or section in definition.sections) and (view is None or view == name)]
            if view is not None and view not in DASHBOARD_READS:
                raise MCPInputError("unknown_dashboard_view", "Choose a documented dashboard view")
            following = offset + page_size
            more = following < len(selected)
            return {"views": [{"name": name, "description": definition.description,
                "required_sections": sorted(definition.sections),
                "enabled": not bool(definition.sections - set(allowed)),
                "parameters_schema": dashboard_parameters(definition)}
                for name, definition in selected[offset:following]],
                "total": len(selected), "offset": offset, "has_more": more,
                "next_offset": following if more else None,
                "read_access_revision": revision, "completeness": "partial" if more else "complete"}
        return await invoke_read(app, settings, MCPToolPolicy("list_dashboard_read_views",
            MCPCapability.READ, frozenset({"read"})), read)

    @server.tool(annotations=annotations, meta={"capability": "mcp:read"})
    async def read_dashboard_view(
        view: Annotated[str, Field(min_length=1, max_length=100)],
        parameters: dict[str, Any] | None = None,
        agency_id: UUID | None = None,
        data_path: list[StrictStr | StrictInt] | None = None,
        page_size: Annotated[int, Field(ge=1, le=100)] = 25,
        cursor: Annotated[str | None, Field(max_length=2048)] = None,
    ) -> dict[str, Any]:
        """Read a catalogued dashboard view using its exact website semantics, including full nested details.

        First discover the view and parameter schema with list_dashboard_read_views.
        parameters contains the website filters/IDs and its native page/cursor.
        data_path is an array of exact object keys and numeric array indexes.
        Follow this tool's next_cursor and every _mcp_read_reference data_path
        to obtain complete data; never claim a partial preview is a full roster.
        Passport expiry alerts: passport_view with data_path=['expiry_alerts'].
        WhatsApp unidentified: whatsapp_tracking; inspect counts and items whose
        kind is unidentified (unmatched passport uploads, not active recipients).
        No file capabilities, preparation, provider refresh or business writes.
        """
        async def read(session: AsyncSession, principal: MCPPrincipal):
            return await read_dashboard(app, settings, session, principal, view=view,
                parameters=parameters or {}, agency_id=agency_id, data_path=data_path or [],
                page_size=page_size, cursor=cursor)
        return await invoke_read(app, settings, MCPToolPolicy("read_dashboard_view",
            MCPCapability.READ, frozenset({"read"})), read)
