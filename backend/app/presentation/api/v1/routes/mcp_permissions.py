"""Optimistic global and per-device permission saves through dashboard MFA."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.credentials import MCPAuthError, utc
from app.application.mcp.permissions import current_permission_control, validate_device_permissions
from app.domain.entities.entities import User
from app.domain.mcp_section_permissions import (
    WRITE_CAPABILITIES,
    section_permission_catalog,
    write_tool_requirements,
)
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.schemas.mcp_permission_schemas import (
    MCPConnectionPermissionsUpdate,
    MCPPermissionsUpdate,
)
from app.presentation.dependencies.auth import require_recent_mfa
from app.presentation.dependencies.csrf import require_cookie_csrf
from app.presentation.dependencies.mcp import require_mcp_management
from app.presentation.mcp.management_audit import MCPManagementAuditRoute

router = APIRouter(dependencies=[Depends(require_mcp_management)], route_class=MCPManagementAuditRoute)
_mutations = [Depends(require_cookie_csrf), Depends(require_recent_mfa)]


def permission_payload(row: MCPControlModel, request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    return {
        "read_enabled": row.read_enabled, "write_enabled": row.write_enabled,
        "allowed_read_sections": row.allowed_read_sections,
        "allowed_write_sections": row.allowed_write_sections, "allowed_write_tools": row.allowed_write_tools,
        "permission_revision": row.read_access_revision, "read_access_revision": row.read_access_revision,
        "section_catalog": section_permission_catalog(), "write_tool_requirements": write_tool_requirements(),
        "read_only_mode": settings.mcp.read_only_mode, "effective_capabilities": settings.mcp.effective_capabilities,
        "write_available": not settings.mcp.read_only_mode and bool(WRITE_CAPABILITIES & set(settings.mcp.effective_capabilities)),
        "permission_controls_available": True,
    }


@router.get("/permissions")
async def get_permissions(request: Request, session: AsyncSession = Depends(get_db_session)) -> dict[str, object]:
    try:
        row = await current_permission_control(session)
    except MCPAuthError:
        raise HTTPException(503, "MCP permissions are unavailable") from None
    return permission_payload(row, request)


@router.put("/permissions", dependencies=_mutations)
async def set_permissions(body: MCPPermissionsUpdate, request: Request,
                          user: User = Depends(require_mcp_management),
                          session: AsyncSession = Depends(get_db_session)) -> dict[str, object]:
    row = await session.scalar(select(MCPControlModel).where(MCPControlModel.id == 1)
                               .execution_options(populate_existing=True).with_for_update())
    if row is None:
        raise HTTPException(503, "MCP permissions are unavailable")
    if row.read_access_revision != body.expected_revision:
        raise HTTPException(409, "Permissions changed. Reload current permissions before saving.")
    settings = request.app.state.settings
    if body.write_enabled and (settings.mcp.read_only_mode or not WRITE_CAPABILITIES & set(settings.mcp.effective_capabilities)):
        raise HTTPException(409, "Write access is unavailable in this deployment")
    for field in ("read_enabled", "write_enabled", "allowed_read_sections", "allowed_write_sections", "allowed_write_tools"):
        setattr(row, field, getattr(body, field))
    row.read_access_revision += 1
    row.updated_at = datetime.now(UTC)
    await AuditLogRepository(session).record(action="mcp.permissions_changed", entity_type="mcp_control", user_id=user.id,
        metadata={"read_enabled": row.read_enabled, "write_enabled": row.write_enabled,
                  "allowed_read_sections": row.allowed_read_sections, "allowed_write_sections": row.allowed_write_sections,
                  "allowed_write_tools": row.allowed_write_tools, "revision": row.read_access_revision})
    await session.commit()
    return permission_payload(row, request)


@router.put("/connections/{connection_id}/permissions", dependencies=_mutations)
async def set_connection_permissions(connection_id: uuid.UUID, body: MCPConnectionPermissionsUpdate, request: Request,
                                     user: User = Depends(require_mcp_management),
                                     session: AsyncSession = Depends(get_db_session)) -> dict[str, object]:
    # All permission/control saves share the control -> grant ordering used by
    # actual operations, pause, exchange and refresh.
    await current_permission_control(session, lock=True)
    row = await session.scalar(select(MCPGrantModel).where(MCPGrantModel.id == connection_id)
                               .execution_options(populate_existing=True).with_for_update())
    if row is None:
        raise HTTPException(404, "Connection not found")
    if row.permission_revision != body.expected_revision:
        raise HTTPException(409, "Connection permissions changed. Reload before saving.")
    if row.revoked_at is not None or utc(row.expires_at) <= datetime.now(UTC):
        raise HTTPException(409, "A revoked or expired connection cannot receive permissions")
    try:
        validate_device_permissions(request.app.state.settings, row.capabilities,
            read_enabled=body.read_enabled, write_enabled=body.write_enabled,
            allowed_read_sections=body.allowed_read_sections, allowed_write_sections=body.allowed_write_sections)
    except MCPAuthError as exc:
        raise HTTPException(exc.status_code, "Reconnect to authorize additional capabilities" if exc.error == "reauthorization_required" else exc.error) from None
    for field in ("read_enabled", "write_enabled", "allowed_read_sections", "allowed_write_sections"):
        setattr(row, field, getattr(body, field))
    row.permission_revision += 1
    await AuditLogRepository(session).record(action="mcp.connection_permissions_changed", entity_type="mcp_connection",
        entity_id=str(row.id), user_id=user.id,
        metadata={"read_enabled": row.read_enabled, "write_enabled": row.write_enabled,
                  "allowed_read_sections": row.allowed_read_sections, "allowed_write_sections": row.allowed_write_sections,
                  "revision": row.permission_revision})
    await session.commit()
    from app.presentation.api.v1.routes.mcp_admin import connection_payload

    return connection_payload(row, request.app.state.settings)
