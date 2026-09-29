"""Describe only tools actually registered in the running release."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from app.core.config.settings import Settings


async def deployed_inventory(app: FastAPI, settings: Settings) -> dict[str, Any]:
    tools = await app.state.mcp_server.list_tools()
    return {
        "tools": [{"name": tool.name, "description": tool.description,
                   "capability": (tool.meta or {}).get("capability", "not_declared"),
                   "deployment_available": settings.mcp.enabled and ((tool.meta or {}).get("capability") in settings.mcp.enabled_capabilities or (tool.meta or {}).get("capability") == "original_operation_capability"),
                   "read_only": bool(tool.annotations and tool.annotations.read_only_hint),
                   "qualification": "in_progress"} for tool in tools],
        "tool_count": len(tools), "environment": settings.app_env,
        "revision": settings.app_revision, "qualification": "in_progress",
        "enabled_capabilities": settings.mcp.enabled_capabilities,
        "notice": "This is the running tool inventory. Local test evidence does not establish full workflow or production qualification.",
        "file_transports": [
            {"name": "stage_pdf_upload", "capability": "mcp:upload", "business_ingestion": False},
            {"name": "stage_contact_workbook", "capability": "mcp:upload", "business_ingestion": False},
            {"name": "prepare_whatsapp_header_image", "capability": "mcp:upload", "required_capabilities": ["mcp:upload", "mcp:communicate"], "business_ingestion": False},
            {"name": "download_prepared_artifact", "capability": "mcp:export"},
            {"name": "acknowledge_verified_delivery", "capability": "mcp:export"},
        ],
    }
