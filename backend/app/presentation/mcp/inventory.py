"""Describe only tools actually registered in the running release."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from app.application.mcp.read_access import current_read_access
from app.core.config.settings import Settings
from app.domain.mcp_read_sections import READ_TOOL_SECTIONS, read_section_catalog


async def deployed_inventory(app: FastAPI, settings: Settings) -> dict[str, Any]:
    tools = await app.state.mcp_server.list_tools()
    allowed: list[str] = []
    read_revision: int | None = None
    if settings.mcp.read_only_mode:
        async with app.state.mcp_session_factory() as session:
            allowed, read_revision = await current_read_access(session)
    return {
        "tools": [{"name": tool.name, "description": tool.description,
                   "capability": (tool.meta or {}).get("capability", "not_declared"),
                   "deployment_available": settings.mcp.enabled and ((tool.meta or {}).get("capability") in settings.mcp.effective_capabilities or (not settings.mcp.read_only_mode and (tool.meta or {}).get("capability") == "original_operation_capability")),
                   "required_read_sections": sorted(READ_TOOL_SECTIONS.get(tool.name, frozenset())),
                   "section_access_allowed": not settings.mcp.read_only_mode or (tool.name in READ_TOOL_SECTIONS and not READ_TOOL_SECTIONS[tool.name] - set(allowed)),
                   "read_only": bool(tool.annotations and tool.annotations.read_only_hint),
                   "qualification": "in_progress"} for tool in tools],
        "tool_count": len(tools), "environment": settings.app_env,
        "revision": settings.app_revision, "qualification": "in_progress",
        "enabled_capabilities": settings.mcp.effective_capabilities,
        "effective_capabilities": settings.mcp.effective_capabilities,
        "read_only_mode": settings.mcp.read_only_mode,
        "allowed_read_sections": allowed,
        "read_access_revision": read_revision,
        "read_section_coverage": read_section_catalog(),
        "notice": "This is the running tool inventory. Local test evidence does not establish full workflow or production qualification.",
        "file_transports": [] if settings.mcp.read_only_mode else [
            {"name": "stage_pdf_upload", "capability": "mcp:upload", "business_ingestion": False},
            {"name": "stage_contact_workbook", "capability": "mcp:upload", "business_ingestion": False},
            {"name": "prepare_whatsapp_header_image", "capability": "mcp:upload", "required_capabilities": ["mcp:upload", "mcp:communicate"], "business_ingestion": False},
            {"name": "download_prepared_artifact", "capability": "mcp:export"},
            {"name": "acknowledge_verified_delivery", "capability": "mcp:export"},
        ],
    }
