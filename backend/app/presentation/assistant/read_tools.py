"""Identical live authorization for typed and native-audio dashboard tools."""

from typing import Any

from app.application.assistant.contracts import AssistantError
from app.domain.entities.entities import User
from app.presentation.assistant.reads import DashboardReader, data_catalog, fresh_actor


async def run_read_tool(
    reader: DashboardReader, user: User, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    if name == "get_workspace_overview":
        return await reader.overview()
    if name == "list_dashboard_views":
        actor = await fresh_actor(user)
        return data_catalog(
            str(arguments.get("query", ""))[:120],
            offset=max(0, min(200, int(arguments.get("offset", 0)))),
            actor=actor,
        )
    if name == "read_dashboard":
        return await reader.read(**arguments)
    raise AssistantError("query_rejected", "This assistant tool is unavailable.", 422)
