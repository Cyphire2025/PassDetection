"""Read complete canonical Excel choices before selecting a specific export."""

from typing import Any

from fastapi import FastAPI, HTTPException
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.artifacts import ArtifactError
from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.excel_options import ExcelExportOptionsRequest, MCPExcelOptionsService
from app.application.mcp.exports import MCPExcelSupport
from app.core.config.settings import Settings
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.presentation.mcp.export_tools import excel_support
from app.presentation.mcp.invocation import MCPInputError, invoke_read

POLICY = MCPToolPolicy("inspect_excel_export_options", MCPCapability.EXPORT, frozenset({"read"}))


def excel_options_support() -> MCPExcelSupport:
    return excel_support()


def register_excel_options_tools(server: MCPServer, app: FastAPI, settings: Settings) -> None:
    @server.tool(
        meta={"capability": "mcp:export"},
        annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False,
                                    idempotent_hint=True, open_world_hint=False),
    )
    async def inspect_excel_export_options(selection: ExcelExportOptionsRequest) -> dict[str, Any]:
        """List all available Excel fields, grouping choices and defaults for explicit group IDs.

        Resolve names/ambiguity first. Single-group options include agency matching;
        selected_groups preserves the website's combined catalog and has no agency
        matching. Empty and imported-contact-only groups are supported. This returns
        no sample values, workbook, creation revision or history entry. After choosing
        options, use inspect_excel_export to obtain the exact export revision.
        """
        async def read(session: AsyncSession, principal: MCPPrincipal) -> dict[str, Any]:
            try:
                return await MCPExcelOptionsService(session, settings, excel_options_support()).inspect(
                    principal, selection,
                )
            except ArtifactError as exc:
                if exc.status_code == 503:
                    raise MCPInputError("export_options_busy", "Excel option sources are busy. Retry the same selection later.") from exc
                if exc.status_code == 413:
                    raise MCPInputError("export_options_limit", "The complete Excel options exceed the configured source or catalog limit. Select fewer groups.") from exc
                raise MCPInputError("export_options_unavailable", "One or more selected groups are unavailable for Excel options.") from exc
            except (HTTPException, ValidationError) as exc:
                raise MCPInputError("export_options_unavailable", "The complete Excel options are unavailable for this selection.") from exc
        return await invoke_read(app, settings, POLICY, read)
