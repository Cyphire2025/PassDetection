"""First-party calls to the reviewed observational dashboard readers."""

from __future__ import annotations

import importlib
import inspect
import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import Request, Response
from sqlalchemy import select

from app.application.assistant.contracts import AssistantError
from app.application.mcp.read_projection import ReadProjection
from app.core.config.settings import get_settings
from app.domain.entities.entities import User, UserRole
from app.domain.mcp_dashboard_reads import DASHBOARD_READS
from app.infrastructure.database.models import (
    AgencyModel,
    AttendanceSessionModel,
    ClientGroupModel,
    PassportSubmissionModel,
    RoomingHotelModel,
    WhatsAppBroadcastGroupModel,
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.mcp.dashboard_read_tools import (
    dashboard_handler,
    dashboard_parameters,
    validate_dashboard_parameters,
)
from app.presentation.mcp.observational_session import observational_session


async def fresh_actor(user: User) -> User:
    async with AsyncSessionFactory() as session:
        actor = await UserRepository(session).get_by_id(user.id)
    if (
        actor is None
        or not actor.is_active
        or actor.role != UserRole.SUPER_ADMIN
        or user.role != UserRole.SUPER_ADMIN
        or actor.session_version != user.session_version
    ):
        raise AssistantError(
            "access_denied", "Sign in with your administrator account to use the assistant.", 403
        )
    return actor


def data_catalog(query: str = "", *, offset: int = 0) -> dict[str, Any]:
    terms = query.casefold().split()[:8]
    views = [
        (name, definition)
        for name, definition in DASHBOARD_READS.items()
        if not terms
        or any(
            term in f"{name} {definition.description} {' '.join(definition.sections)}".casefold()
            for term in terms
        )
    ]
    selected = views[offset : offset + 8]
    return {
        "views": [
            {
                "name": name,
                "description": definition.description,
                "parameters": dashboard_parameters(definition),
            }
            for name, definition in selected
        ],
        "has_more": len(views) > offset + 8,
        "next_offset": offset + 8 if len(views) > offset + 8 else None,
    }


class DashboardReader:
    def __init__(self, request: Request, user: User):
        self.request = request
        self.user = user

    async def overview(self) -> dict[str, Any]:
        actor = await fresh_actor(self.user)
        async with AsyncSessionFactory() as session:
            async with observational_session(session):
                agencies = (
                    await session.execute(select(AgencyModel.id, AgencyModel.name).limit(100))
                ).all()
        return {
            "agencies": [{"id": str(row.id), "name": row.name} for row in agencies],
            "account": actor.full_name,
            "observed_at": datetime.now(UTC).isoformat(),
            "access": "read_only",
            "possibly_more_agencies": len(agencies) == 100,
            "notice": "Choose the relevant agency and discover a view before querying. At most 100 agencies are shown. Results are current at the observation time.",
        }

    async def read(
        self,
        view: str,
        parameters: dict[str, Any],
        *,
        agency_id: str | None = None,
        data_path: list[str | int] | None = None,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        definition = DASHBOARD_READS.get(view)
        if definition is None:
            raise AssistantError("unknown_view", "Choose a documented dashboard view.", 422)
        actor = await fresh_actor(self.user)
        arguments = validate_dashboard_parameters(definition, parameters)
        selected_agency = (
            UUID(agency_id) if agency_id else arguments.get("agency_id") or actor.agency_id
        )
        async with AsyncSessionFactory() as session:
            if definition.group_parameter and arguments.get(definition.group_parameter) is not None:
                group = await session.get(ClientGroupModel, arguments[definition.group_parameter])
                if (
                    group is None
                    or selected_agency is not None
                    and selected_agency != group.agency_id
                ):
                    raise AssistantError(
                        "scope_mismatch", "This group is unavailable in the selected agency.", 422
                    )
                selected_agency = group.agency_id
            resource_model = (
                PassportSubmissionModel
                if view.startswith("passport_") and "submission_id" in arguments
                else RoomingHotelModel
                if view == "hotel_checkins"
                else AttendanceSessionModel
                if view == "my_tour_session"
                else WhatsAppBroadcastGroupModel
                if view
                in {
                    "whatsapp_tracking",
                    "whatsapp_broadcast_details",
                    "whatsapp_source_contacts",
                    "whatsapp_broadcast_stored",
                    "whatsapp_broadcast_records",
                }
                else None
            )
            if resource_model is not None:
                key = (
                    "submission_id"
                    if resource_model is PassportSubmissionModel
                    else "hotel_id"
                    if resource_model is RoomingHotelModel
                    else "session_id"
                    if resource_model is AttendanceSessionModel
                    else "group_id"
                )
                resource_agency = await session.scalar(
                    select(resource_model.agency_id).where(resource_model.id == arguments[key])
                )
                if (
                    resource_agency is None
                    or selected_agency is not None
                    and selected_agency != resource_agency
                ):
                    raise AssistantError(
                        "scope_mismatch", "This record is unavailable in the selected agency.", 422
                    )
                selected_agency = resource_agency
            if selected_agency is not None:
                agency = await session.get(AgencyModel, selected_agency)
                if agency is None:
                    raise AssistantError("not_found", "This agency is unavailable.", 404)
                actor = replace(actor, agency_id=selected_agency)
                if "agency_id" in arguments and arguments["agency_id"] is None:
                    arguments["agency_id"] = selected_agency
            if arguments.get("agency_id") is not None and selected_agency != arguments["agency_id"]:
                raise AssistantError(
                    "scope_mismatch", "Choose one agency for this dashboard query.", 422
                )
            function = dashboard_handler(definition)
            injected = {
                "current_user": actor,
                "session": session,
                "request": self.request,
                "response": Response(),
            }
            if "use_case" in inspect.signature(function).parameters:
                if view != "group_links":
                    raise AssistantError(
                        "unsupported_view", "This view is unavailable to the assistant.", 422
                    )
                module = importlib.import_module("app.presentation.api.v1.routes.client_groups")
                injected["use_case"] = module._get_list_use_case(session)
            async with observational_session(session):
                value = await function(
                    **arguments,
                    **{
                        name: item
                        for name, item in injected.items()
                        if name in inspect.signature(function).parameters
                    },
                )
            # Only the canonical readers' sensitive-read audit may be committed.
            await session.commit()
        if isinstance(value, Response):
            if value.status_code >= 400:
                raise AssistantError("query_rejected", "The dashboard rejected these filters.", 422)
            value = json.loads(bytes(value.body))
        result = ReadProjection(get_settings().app_secret_key).page(
            value,
            binding={
                "actor": str(actor.id),
                "view": view,
                "parameters": parameters,
                "agency_id": str(selected_agency),
                "surface": "first_party_assistant_v1",
            },
            data_path=data_path or [],
            page_size=50,
            cursor=cursor,
        )
        source = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        source_page = (
            {
                key: source[key]
                for key in (
                    "has_more",
                    "next_cursor",
                    "next_offset",
                    "page",
                    "page_size",
                    "total_pages",
                    "total",
                    "total_count",
                    "incomplete",
                    "truncated",
                )
                if key in source
            }
            if isinstance(source, dict)
            else {}
        )
        if isinstance(source, list) and "limit" in arguments:
            source_page = {
                "returned_count": len(source),
                "limit": arguments["limit"],
                "possibly_more": len(source) >= arguments["limit"],
            }
        if source_page:
            result["website_pagination"] = source_page
            if (
                source_page.get("has_more")
                or source_page.get("next_cursor")
                or source_page.get("next_offset") is not None
                or source_page.get("incomplete")
                or source_page.get("possibly_more")
                or source_page.get("truncated")
                or source_page.get("page", 1) < source_page.get("total_pages", 1)
            ):
                result["completeness"] = "partial"
        if view == "document_delivery_summary":
            result["count_notice"] = (
                "The sent counter includes provider acceptance. Only delivered/read confirm delivery. Report partial stored delivery previews honestly."
            )
            if isinstance(source, dict) and source.get("counts", {}).get("total", 0) > len(
                source.get("deliveries", [])
            ):
                result["completeness"] = "partial"
        return {
            **result,
            "view": view,
            "source": "dashboard",
            "observed_at": datetime.now(UTC).isoformat(),
            "notice": "Stored dashboard observations only. Pagination and partial results must be reported accurately.",
        }
