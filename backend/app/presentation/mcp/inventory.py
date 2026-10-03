"""Describe only tools actually registered in the running release."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from app.core.config.settings import Settings
from app.domain.mcp_read_sections import READ_TOOL_SECTIONS, read_section_catalog
from app.domain.mcp_section_permissions import (
    DYNAMIC_WRITE_TOOL_SECTIONS,
    WRITE_CAPABILITIES,
    WRITE_TOOL_SECTIONS,
)
from app.presentation.mcp.permission_listing import tool_access_snapshot


async def deployed_inventory(app: FastAPI, settings: Settings) -> dict[str, Any]:
    tools = await app.state.mcp_server.list_tools()
    async with app.state.mcp_session_factory() as session:
        access = await tool_access_snapshot(session, settings)
    available = access.filter_tools(tools)
    available_names = {tool.name for tool in available}
    deployment_scopes = set(settings.mcp.effective_capabilities)

    def deployed(tool) -> bool:
        capability = (tool.meta or {}).get("capability")
        if tool.name == "inspect_native_transfer":
            return settings.mcp.enabled and bool(deployment_scopes & {"mcp:upload", "mcp:export"})
        if tool.name == "inspect_operation":
            return (
                settings.mcp.enabled
                and not settings.mcp.read_only_mode
                and bool(deployment_scopes & WRITE_CAPABILITIES)
            )
        return settings.mcp.enabled and capability in deployment_scopes

    return {
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "capability": (tool.meta or {}).get("capability", "not_declared"),
                "deployment_available": deployed(tool),
                "required_read_sections": sorted(READ_TOOL_SECTIONS.get(tool.name, frozenset())),
                "required_write_sections": sorted(WRITE_TOOL_SECTIONS.get(tool.name, frozenset())),
                "available_section_choices": sorted(access.section_choices(tool.name)),
                "section_access_allowed": tool.name in available_names,
                "available": tool.name in available_names,
                "read_only": bool(tool.annotations and tool.annotations.read_only_hint),
                "qualification": "in_progress",
            }
            for tool in tools
        ],
        "tool_count": len(tools),
        "available_tool_count": len(available),
        "environment": settings.app_env,
        "revision": settings.app_revision,
        "qualification": "in_progress",
        "enabled_capabilities": settings.mcp.effective_capabilities,
        "effective_capabilities": access.available_capabilities(tools),
        "read_only_mode": settings.mcp.read_only_mode,
        "permission_scope": "global_deployment",
        "read_enabled": access.read_enabled,
        "write_enabled": access.write_enabled,
        "allowed_read_sections": sorted(access.read_sections),
        "allowed_write_sections": sorted(access.write_sections),
        "allowed_write_tools": sorted(
            tool.name
            for tool in available
            if (tool.meta or {}).get("capability")
            in WRITE_CAPABILITIES | {"original_operation_capability"}
        ),
        "read_access_revision": access.read_access_revision,
        "read_section_coverage": read_section_catalog(),
        "notice": "Global deployment policy only. Each connection additionally requires its current OAuth scopes, device permissions and canonical application access. Local tests do not establish full production qualification.",
        "file_transports": [
            {
                "name": tool.name,
                "capability": (tool.meta or {}).get("capability"),
                "available_section_choices": sorted(access.section_choices(tool.name)),
                "business_ingestion": False,
            }
            for tool in available
            if tool.name in DYNAMIC_WRITE_TOOL_SECTIONS and tool.name != "create_workforce_account"
        ],
    }
