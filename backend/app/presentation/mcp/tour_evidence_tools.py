"""Native existing-QR image output and bounded canonical attendance history."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.tour_evidence_reads import MCPTourEvidenceReadService
from app.core.config.settings import Settings
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.presentation.mcp.invocation import MCPInputError, invoke_read


def qr_image_result(result: dict[str, Any]) -> CallToolResult:
    metadata = dict(result)
    image = metadata.pop("qr_image_png", None)
    content: list[Any] = [TextContent(type="text", text=json.dumps(metadata, sort_keys=True))]
    if image is not None and "error" not in metadata:
        content.append(ImageContent(type="image", mime_type="image/png", data=image))
    return CallToolResult(content=content, is_error="error" in metadata)


def register_tour_evidence_tools(server: MCPServer, app: FastAPI, settings: Settings) -> None:
    annotations = ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )

    async def dispatch(name: str, parameters: dict[str, Any]) -> dict[str, Any]:
        async def read(session: AsyncSession, principal: MCPPrincipal) -> dict[str, Any]:
            service = MCPTourEvidenceReadService(session, settings)
            try:
                async with asyncio.timeout(5):
                    return await (
                        service.qr(principal, **parameters)
                        if name == "get_passenger_qr"
                        else service.attendance(principal, **parameters)
                    )
            except TimeoutError as exc:
                raise MCPInputError(
                    "tour_evidence_timeout",
                    "The bounded evidence observation timed out. Retry the same scope without changing business records.",
                ) from exc
            except ValueError as exc:
                raise MCPInputError(
                    "tour_evidence_unavailable",
                    "Inspect the exact agency, group, passenger/activity IDs and keep all signed page filters unchanged. Existing evidence is unavailable under current scope.",
                ) from exc

        return await invoke_read(
            app, settings, MCPToolPolicy(name, MCPCapability.READ, frozenset({"read"})), read
        )

    @server.tool(meta={"capability": "mcp:read"}, annotations=annotations)
    async def get_passenger_qr(
        agency_id: UUID, group_id: UUID, passenger_id: UUID
    ) -> CallToolResult:
        """Show one person's existing attendance QR as a native PNG image, with lifecycle metadata.

        Resolve exact agency/group/passenger IDs first. Returns the existing active
        or inactive QR without generating, regenerating, activating or revoking it.
        Revoked, expired or missing credentials return metadata without an image.
        QR possession never proves a person's presence. No raw payload is included
        in the text or audit receipt; share the credential image only as requested.
        """
        return qr_image_result(
            await dispatch(
                "get_passenger_qr",
                dict(agency_id=agency_id, group_id=group_id, passenger_id=passenger_id),
            )
        )

    @server.tool(meta={"capability": "mcp:read"}, annotations=annotations)
    async def list_attendance_activity_records(
        agency_id: UUID,
        group_id: UUID,
        activity_id: UUID,
        page_size: Annotated[int, Field(ge=1, le=100)] = 50,
        cursor: Annotated[str | None, Field(max_length=2048)] = None,
    ) -> dict[str, Any]:
        """Read retained scan evidence across one canonical activity and its aliases.

        Resolve IDs from attendance summary. Follow the signed cursor with all
        scope/page filters unchanged. Recorded events retain their source and
        scan time; multiple aliases can record the same person. These event rows
        do not replace canonical distinct-present counts and never create scans,
        device identities, checkpoints, completion or physical attendance claims.
        """
        return await dispatch(
            "list_attendance_activity_records",
            dict(
                agency_id=agency_id,
                group_id=group_id,
                activity_id=activity_id,
                page_size=page_size,
                cursor=cursor,
            ),
        )
