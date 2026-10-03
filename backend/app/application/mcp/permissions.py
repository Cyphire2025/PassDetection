"""Live global/device permissions, serialized before any business effects."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.credentials import MCPAuthError, utc
from app.core.config.settings import Settings
from app.domain.mcp_read_sections import validate_read_sections
from app.domain.mcp_section_permissions import (
    DYNAMIC_WRITE_TOOL_SECTIONS,
    WRITE_CAPABILITIES,
    WRITE_TOOL_SECTIONS,
    validate_write_sections,
    validate_write_tools,
)
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel


def validate_device_permissions(settings: Settings, capabilities: list[str], *, read_enabled: bool,
                                write_enabled: bool, allowed_read_sections: list[str] | None,
                                allowed_write_sections: list[str]) -> None:
    if type(read_enabled) is not bool or type(write_enabled) is not bool:
        raise MCPAuthError("invalid_request", 400)
    try:
        if allowed_read_sections is not None:
            validate_read_sections(allowed_read_sections)
        validate_write_sections(allowed_write_sections)
    except (TypeError, ValueError):
        raise MCPAuthError("invalid_request", 400) from None
    if read_enabled and "mcp:read" not in capabilities:
        raise MCPAuthError("reauthorization_required", 409)
    if write_enabled and not (set(capabilities) & WRITE_CAPABILITIES):
        raise MCPAuthError("reauthorization_required", 409)
    if write_enabled and (settings.mcp.read_only_mode or not (set(capabilities) & WRITE_CAPABILITIES & set(settings.mcp.effective_capabilities))):
        raise MCPAuthError("write_unavailable", 409)


async def current_permission_control(session: AsyncSession, *, lock: bool = False) -> MCPControlModel:
    statement = select(MCPControlModel).where(MCPControlModel.id == 1).execution_options(populate_existing=True)
    if lock:
        statement = statement.with_for_update(read=True)
    control = await session.scalar(statement)
    if control is None:
        raise MCPAuthError("temporarily_unavailable", 503)
    try:
        if type(control.read_enabled) is not bool or type(control.write_enabled) is not bool:
            raise ValueError("Invalid permission toggle")
        if type(control.read_access_revision) is not int or control.read_access_revision < 1:
            raise ValueError("Invalid permission revision")
        for values, validator in ((control.allowed_read_sections, validate_read_sections),
                                  (control.allowed_write_sections, validate_write_sections),
                                  (control.allowed_write_tools, validate_write_tools)):
            if type(values) is not list:
                raise ValueError("Invalid section policy")
            validator(values)
    except (TypeError, ValueError):
        raise MCPAuthError("temporarily_unavailable", 503) from None
    return control


async def require_permission_capability(session: AsyncSession, settings: Settings, grant: MCPGrantModel,
                                        capability: str, *, lock: bool = True) -> None:
    control = await current_permission_control(session, lock=lock)
    if capability == "mcp:read":
        if control.read_enabled is not True or grant.read_enabled is not True:
            raise MCPAuthError("read_access_denied", 403)
    elif capability in WRITE_CAPABILITIES:
        if settings.mcp.read_only_mode or control.write_enabled is not True or grant.write_enabled is not True:
            raise MCPAuthError("write_access_denied", 403)


async def current_device_read_access(session: AsyncSession, grant_id: UUID, *, lock: bool = False) -> tuple[list[str], int]:
    control = await current_permission_control(session, lock=lock)
    grant = await session.scalar(select(MCPGrantModel).where(MCPGrantModel.id == grant_id)
                                .execution_options(populate_existing=True))
    if grant is None or grant.read_enabled is not True or control.read_enabled is not True:
        raise MCPAuthError("read_access_denied", 403)
    allowed = set(control.allowed_read_sections)
    if grant.allowed_read_sections is not None:
        try:
            if type(grant.allowed_read_sections) is not list:
                raise ValueError("Invalid device read sections")
            allowed.intersection_update(validate_read_sections(grant.allowed_read_sections))
        except (TypeError, ValueError):
            raise MCPAuthError("access_denied", 403) from None
    return sorted(allowed), control.read_access_revision


async def require_tool_access(session: AsyncSession, settings: Settings, grant_id: UUID, name: str,
                              capability: str, *, lock: bool = True, required_sections: frozenset[str] | None = None) -> None:
    """Use code-owned adapter names, including preparation, retries and file handoff.

    OAuth envelope is checked independently by the authorization service. This
    function never expands it and must run inside the effect's transaction.
    """
    control = await current_permission_control(session, lock=lock)
    grant = await session.scalar(select(MCPGrantModel).where(MCPGrantModel.id == grant_id)
                                .execution_options(populate_existing=True))
    if (grant is None or grant.enabled is not True or grant.revoked_at is not None
            or utc(grant.expires_at) <= datetime.now(UTC) or control.enabled is not True or not settings.mcp.enabled):
        raise MCPAuthError("access_denied", 403)
    if capability not in grant.capabilities or capability not in settings.mcp.effective_capabilities:
        raise MCPAuthError("insufficient_scope", 403)
    await require_permission_capability(session, settings, grant, capability, lock=False)
    if capability not in WRITE_CAPABILITIES:
        return
    required = WRITE_TOOL_SECTIONS.get(name)
    if required is None or name not in control.allowed_write_tools:
        raise MCPAuthError("write_tool_denied", 403)
    if name in DYNAMIC_WRITE_TOOL_SECTIONS:
        if not required_sections or required_sections - DYNAMIC_WRITE_TOOL_SECTIONS[name]:
            raise MCPAuthError("write_section_denied", 403)
        required = required_sections
    elif required_sections is not None:
        # Overrides can only strengthen the fixed reviewed boundary.
        required = required | required_sections
    try:
        if type(grant.allowed_write_sections) is not list:
            raise ValueError("Invalid device write sections")
        selected = set(validate_write_sections(grant.allowed_write_sections))
    except (TypeError, ValueError):
        raise MCPAuthError("access_denied", 403) from None
    if required - set(control.allowed_write_sections) or required - selected:
        raise MCPAuthError("write_section_denied", 403)
