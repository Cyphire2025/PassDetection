"""Discovery metadata from live policy; invocation still authorizes every request."""

from dataclasses import dataclass
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.types import ListToolsResult, Tool
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.permissions import current_permission_control
from app.core.config.settings import Settings
from app.domain.mcp_read_sections import READ_TOOL_SECTIONS, validate_read_sections
from app.domain.mcp_section_permissions import (
    DYNAMIC_WRITE_TOOL_SECTIONS,
    WRITE_CAPABILITIES,
    WRITE_TOOL_SECTIONS,
    validate_write_sections,
)
from app.infrastructure.database.mcp_models import MCPGrantModel
from app.presentation.mcp.diagnostic_tools import DIAGNOSTIC_TOOL_NAMES

DYNAMIC_TOOL_CAPABILITIES = {
    "create_workforce_account": "mcp:change",
    "create_native_upload": "mcp:upload",
    "create_native_download": "mcp:export",
    "read_native_artifact": "mcp:export",
}
UPLOAD_SOURCE_TOOLS = {
    "document_delivery": "upload_document_pdf",
    "group_excel_imports": "upload_group_workbook",
    "whatsapp_broadcasts": "upload_contact_workbook",
}
EXPORT_PREPARATION_TOOLS = {
    "passport_excel": "prepare_excel_export",
    "passport_images": "prepare_image_export",
    "tracking_excel": "prepare_tracking_export",
    "rooming_excel": "prepare_rooming_export",
    "document_assignments_excel": "prepare_document_assignment_export",
}


@dataclass(frozen=True)
class ToolAccessSnapshot:
    """A policy ceiling, never a grant or a promise of tenant/resource access."""

    capabilities: frozenset[str]
    read_enabled: bool
    write_enabled: bool
    read_sections: frozenset[str]
    write_sections: frozenset[str]
    write_tools: frozenset[str]
    global_read_enabled: bool
    global_write_enabled: bool
    device_read_enabled: bool | None
    device_write_enabled: bool | None
    read_access_revision: int
    device_permission_revision: int | None
    native_upload_sections: frozenset[str]
    native_export_available: bool

    def section_choices(self, name: str) -> frozenset[str]:
        capability = DYNAMIC_TOOL_CAPABILITIES.get(name)
        if capability is not None and capability not in self.capabilities:
            return frozenset()
        choices = DYNAMIC_WRITE_TOOL_SECTIONS.get(name, frozenset()) & self.write_sections
        if name == "create_native_upload":
            choices &= self.native_upload_sections
        if (
            name in {"create_native_download", "read_native_artifact", "inspect_native_transfer"}
            and not self.native_export_available
        ):
            choices -= frozenset({"exports"})
        if name == "inspect_native_transfer":
            if "mcp:upload" not in self.capabilities:
                choices -= DYNAMIC_WRITE_TOOL_SECTIONS["create_native_upload"]
            if "mcp:export" not in self.capabilities:
                choices -= frozenset({"exports"})
        return choices

    def allows(self, tool: Tool) -> bool:
        name, capability = tool.name, (tool.meta or {}).get("capability")
        if name == "inspect_operation":
            return bool(
                self.write_enabled
                and self.write_sections
                and self.capabilities & WRITE_CAPABILITIES
            )
        if name == "inspect_native_transfer":
            scope_allowed = bool(self.capabilities & {"mcp:upload", "mcp:export"})
        else:
            scope_allowed = capability in self.capabilities
        if not scope_allowed:
            return False
        if capability == "mcp:diagnose":
            return self.read_enabled and name in DIAGNOSTIC_TOOL_NAMES
        if capability == "mcp:read":
            return (
                self.read_enabled
                and name in READ_TOOL_SECTIONS
                and READ_TOOL_SECTIONS[name] <= self.read_sections
            )
        if not self.write_enabled or name not in self.write_tools:
            return False
        if name in DYNAMIC_WRITE_TOOL_SECTIONS:
            return bool(self.section_choices(name))
        return name in WRITE_TOOL_SECTIONS and WRITE_TOOL_SECTIONS[name] <= self.write_sections

    def filter_tools(self, tools: list[Tool]) -> list[Tool]:
        available = [tool for tool in tools if self.allows(tool)]
        if not any(
            (tool.meta or {}).get("capability") in self.capabilities & WRITE_CAPABILITIES
            for tool in available
            if tool.name != "inspect_native_transfer"
        ):
            available = [tool for tool in available if tool.name != "inspect_operation"]
        return available

    def available_capabilities(self, tools: list[Tool]) -> list[str]:
        """Scopes with a currently discoverable adapter, not the stored OAuth envelope."""
        available = self.filter_tools(tools)
        capabilities = {
            (tool.meta or {}).get("capability")
            for tool in available
            if tool.name != "inspect_native_transfer"
        } & self.capabilities
        if any(tool.name == "inspect_native_transfer" for tool in available):
            choices = self.section_choices("inspect_native_transfer")
            if choices & DYNAMIC_WRITE_TOOL_SECTIONS["create_native_upload"]:
                capabilities.add("mcp:upload")
            if "exports" in choices:
                capabilities.add("mcp:export")
        return sorted(capabilities)


async def tool_access_snapshot(
    session: AsyncSession, settings: Settings, *, grant: MCPGrantModel | None = None
) -> ToolAccessSnapshot:
    """Global inventory omits a grant; native discovery supplies its live grant."""
    control = await current_permission_control(session)
    read, write = set(control.allowed_read_sections), set(control.allowed_write_sections)
    capabilities = set(settings.mcp.effective_capabilities)
    if grant is not None:
        try:
            if type(grant.read_enabled) is not bool or type(grant.write_enabled) is not bool:
                raise ValueError("Invalid permission toggle")
            if type(grant.permission_revision) is not int or grant.permission_revision < 1:
                raise ValueError("Invalid device revision")
            if grant.allowed_read_sections is not None:
                if type(grant.allowed_read_sections) is not list:
                    raise ValueError("Invalid read policy")
                read.intersection_update(validate_read_sections(grant.allowed_read_sections))
            if type(grant.allowed_write_sections) is not list:
                raise ValueError("Invalid write policy")
            write.intersection_update(validate_write_sections(grant.allowed_write_sections))
            if type(grant.capabilities) is not list:
                raise ValueError("Invalid OAuth scope")
            capabilities.intersection_update(grant.capabilities)
        except (TypeError, ValueError):
            raise MCPAuthError("access_denied", 403) from None
    active = (
        settings.mcp.enabled
        and control.enabled is True
        and (grant is None or grant.enabled is True)
    )
    read_enabled = bool(
        active
        and control.read_enabled
        and (grant is None or grant.read_enabled)
        and "mcp:read" in capabilities
    )
    write_enabled = bool(
        active
        and not settings.mcp.read_only_mode
        and control.write_enabled
        and (grant is None or grant.write_enabled)
        and capabilities & WRITE_CAPABILITIES
    )
    if not read_enabled:
        capabilities.discard("mcp:read")
    if not write_enabled:
        capabilities.difference_update(WRITE_CAPABILITIES)
    return ToolAccessSnapshot(
        frozenset(capabilities),
        read_enabled,
        write_enabled,
        frozenset(read) if read_enabled else frozenset(),
        frozenset(write) if write_enabled else frozenset(),
        frozenset(control.allowed_write_tools) if write_enabled else frozenset(),
        control.read_enabled,
        control.write_enabled,
        grant.read_enabled if grant else None,
        grant.write_enabled if grant else None,
        control.read_access_revision,
        grant.permission_revision if grant else None,
        frozenset(
            section
            for section, tool in UPLOAD_SOURCE_TOOLS.items()
            if tool in control.allowed_write_tools
        ),
        "download_export" in control.allowed_write_tools
        and any(
            EXPORT_PREPARATION_TOOLS[family] in control.allowed_write_tools
            for family in settings.mcp.export_families
        ),
    )


class PermissionListingMiddleware:
    def __init__(self, app, settings):
        self.app, self.settings = app, settings

    async def __call__(
        self, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        result = await call_next(ctx)
        if ctx.method != "tools/list":
            return result
        # SDK 2.2 serializes the handler result before invoking outer middleware.
        # Keep the native wire envelope while filtering the same typed tool rows.
        typed_result = (
            result
            if isinstance(result, ListToolsResult)
            else ListToolsResult.model_validate(result)
        )
        token = get_access_token()
        async with self.app.state.mcp_session_factory() as session:
            try:
                if token is None:
                    raise MCPAuthError("invalid_token", 401)
                auth = MCPAuthorizationService(session, self.settings)
                principal = await auth.verify_access(token.token)
                grant = await auth.require_grant(principal.grant_id)
                snapshot = await tool_access_snapshot(session, self.settings, grant=grant)
                tools = snapshot.filter_tools(typed_result.tools)
                await session.commit()
            except MCPAuthError:
                await session.rollback()
                tools = []
        if isinstance(result, ListToolsResult):
            return result.model_copy(update={"tools": tools})
        return {
            **result,
            "tools": [
                tool.model_dump(mode="json", by_alias=True, exclude_none=True) for tool in tools
            ],
        }
