"""Bounded MCP dashboard overview, activity, inventory and operation projections."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.client_policy import DIRECT_CLIENT_NAMES, DIRECT_CLIENT_REDIRECTS
from app.application.mcp.read_access import current_read_access
from app.domain.mcp_policy import CAPABILITIES
from app.domain.mcp_read_sections import read_section_catalog
from app.infrastructure.database.mcp_models import MCPControlModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import AuditLogModel
from app.infrastructure.database.session import get_db_session
from app.presentation.mcp.inventory import deployed_inventory

from .mcp_admin_context import _settings


async def overview(
    request: Request, session: AsyncSession = Depends(get_db_session)
) -> dict[str, object]:
    settings = _settings(request)
    enabled = await session.scalar(select(MCPControlModel.enabled).where(MCPControlModel.id == 1))
    allowed, read_revision = await current_read_access(session)
    return {
        "enabled": enabled is True and settings.mcp.enabled,
        "deployment_enabled": settings.mcp.enabled,
        "emergency_disabled": enabled is not True,
        "resource": settings.mcp.resource,
        "capabilities": settings.mcp.effective_capabilities,
        "effective_capabilities": settings.mcp.effective_capabilities,
        "defined_capabilities": ["mcp:read"]
        if settings.mcp.read_only_mode
        else sorted(CAPABILITIES),
        "read_only_mode": settings.mcp.read_only_mode,
        "permission_controls_available": True,
        "allowed_read_sections": allowed,
        "read_access_revision": read_revision,
        "read_section_coverage": read_section_catalog(),
        "approved_clients": settings.mcp.approved_clients,
        "direct_clients": DIRECT_CLIENT_REDIRECTS,
        "client_names": DIRECT_CLIENT_NAMES,
        "environment": settings.app_env,
        "revision": settings.app_revision,
        "observed_at": datetime.now(UTC),
        "qualification": "in_progress",
    }


async def activity(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    search: str = Query(default="", max_length=120),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    statement = select(AuditLogModel).where(AuditLogModel.action.like("mcp.%"))
    if search:
        statement = statement.where(AuditLogModel.action.contains(search, autoescape=True))
    rows = list(
        (
            await session.scalars(
                statement.order_by(AuditLogModel.created_at.desc(), AuditLogModel.id.desc())
                .offset(offset)
                .limit(limit + 1)
            )
        ).all()
    )
    return {
        "items": [
            {
                "id": str(row.id),
                "action": row.action,
                "result": row.result,
                "entity_id": row.entity_id,
                "created_at": row.created_at,
            }
            for row in rows[:limit]
        ],
        "next_offset": offset + limit if len(rows) > limit else None,
    }


async def inventory(request: Request) -> dict[str, object]:
    return await deployed_inventory(request.app, _settings(request))


async def operations(
    request: Request,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    if _settings(request).mcp.read_only_mode:
        raise HTTPException(
            403, "MCP workflow controls are unavailable in this read-only deployment"
        )
    rows = list(
        (
            await session.scalars(
                select(MCPOperationModel)
                .order_by(MCPOperationModel.created_at.desc(), MCPOperationModel.id.desc())
                .offset(offset)
                .limit(limit + 1)
            )
        ).all()
    )
    return {
        "items": [
            {
                "id": str(row.id),
                "user_id": str(row.user_id),
                "connection_id": str(row.initial_grant_id),
                "operation": row.operation_name,
                "workflow_id": str(row.workflow_id),
                "status": row.status,
                "progress": row.progress,
                "stage": row.stage,
                "revision": row.revision,
                "created_entities": row.created_entities,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "completed_at": row.completed_at,
            }
            for row in rows[:limit]
        ],
        "next_offset": offset + limit if len(rows) > limit else None,
    }


# Keep established facade import and serialized function identities.
for _function in (
    overview,
    activity,
    inventory,
    operations,
):
    _function.__module__ = "app.presentation.api.v1.routes.mcp_admin"
del _function
