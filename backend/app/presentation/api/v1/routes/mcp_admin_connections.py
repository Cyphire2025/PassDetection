"""Dashboard device metadata, revocation and narrowing of existing MCP authority."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.credentials import utc
from app.domain.assistant_identity import ASSISTANT_CLIENT_ID
from app.domain.entities.entities import User
from app.infrastructure.database.mcp_models import MCPGrantModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.schemas.mcp_schemas import (
    MCPConnectionAccessRequest,
    MCPConnectionUpdate,
)
from app.presentation.dependencies.mcp import require_mcp_management

from .mcp_admin_connection_payload import connection_payload as connection_payload
from .mcp_admin_context import _settings


async def connections(
    request: Request,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    rows = list(
        (
            await session.scalars(
                select(MCPGrantModel)
                .where(MCPGrantModel.client_id != ASSISTANT_CLIENT_ID)
                # Explicitly removed entries retain their grant and workflow
                # provenance. Other revoked entries remain in the Devices list.
                .where(
                    or_(
                        MCPGrantModel.revoked_at.is_(None),
                        MCPGrantModel.revocation_reason.is_(None),
                        MCPGrantModel.revocation_reason != "administrator_removed",
                    )
                )
                .order_by(
                    MCPGrantModel.created_at.desc(),
                    MCPGrantModel.id.desc(),
                )
                .offset(offset)
                .limit(limit + 1)
            )
        ).all()
    )
    return {
        "items": [connection_payload(row, _settings(request)) for row in rows[:limit]],
        "next_offset": offset + limit if len(rows) > limit else None,
    }


async def revoke(
    connection_id: uuid.UUID,
    user: User = Depends(require_mcp_management),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, bool]:
    row = await session.scalar(
        select(MCPGrantModel).where(MCPGrantModel.id == connection_id).with_for_update()
    )
    if row is None or row.client_id == ASSISTANT_CLIENT_ID:
        raise HTTPException(404, "Connection not found")
    if row.revoked_at is None:
        row.revoked_at, row.revocation_reason = datetime.now(UTC), "administrator_revoked"
        await AuditLogRepository(session).record(
            action="mcp.revoked",
            entity_type="mcp_connection",
            entity_id=str(row.id),
            user_id=user.id,
        )
    await session.commit()
    return {"revoked": True}


async def set_connection_access(
    connection_id: uuid.UUID,
    body: MCPConnectionAccessRequest,
    request: Request,
    user: User = Depends(require_mcp_management),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    # Exchange, refresh and application operations serialize on the same row.
    row = await session.scalar(
        select(MCPGrantModel).where(MCPGrantModel.id == connection_id).with_for_update()
    )
    if row is None or row.client_id == ASSISTANT_CLIENT_ID:
        raise HTTPException(404, "Connection not found")
    if body.enabled and (row.revoked_at is not None or utc(row.expires_at) <= datetime.now(UTC)):
        raise HTTPException(409, "Reconnect to enable an expired or revoked connection")
    if row.enabled != body.enabled:
        row.enabled = body.enabled
        await AuditLogRepository(session).record(
            action="mcp.connection_access_changed",
            entity_type="mcp_connection",
            entity_id=str(row.id),
            user_id=user.id,
            metadata={"enabled": body.enabled},
        )
    await session.commit()
    return connection_payload(row, _settings(request))


async def delete_connection(
    connection_id: uuid.UUID,
    user: User = Depends(require_mcp_management),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, bool]:
    row = await session.scalar(
        select(MCPGrantModel)
        .where(MCPGrantModel.id == connection_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if row is None or row.client_id == ASSISTANT_CLIENT_ID:
        raise HTTPException(404, "Connection not found")
    if row.revoked_at is None or row.revocation_reason != "administrator_removed":
        previous_reason, revoked_now = row.revocation_reason, row.revoked_at is None
        if revoked_now:
            row.revoked_at = datetime.now(UTC)
        # Keep the grant and every linked workflow or credential row. The
        # Devices query hides this marker only when authority is also revoked.
        row.revocation_reason = "administrator_removed"
        await AuditLogRepository(session).record(
            action="mcp.connection_removed",
            entity_type="mcp_connection",
            entity_id=str(row.id),
            user_id=user.id,
            metadata={"previous_revocation_reason": previous_reason, "revoked_now": revoked_now},
        )
    await session.commit()
    return {"deleted": True}


async def update_connection(
    connection_id: uuid.UUID,
    body: MCPConnectionUpdate,
    request: Request,
    user: User = Depends(require_mcp_management),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    row = await session.scalar(
        select(MCPGrantModel).where(MCPGrantModel.id == connection_id).with_for_update()
    )
    if row is None or row.client_id == ASSISTANT_CLIENT_ID:
        raise HTTPException(404, "Connection not found")
    # A reconnect is necessary for expanded authority. Narrowing applies immediately.
    if set(body.capabilities) - set(_settings(request).mcp.effective_capabilities):
        raise HTTPException(409, "The deployment does not allow these capabilities")
    if set(body.capabilities) - set(row.capabilities):
        raise HTTPException(409, "Reconnect to authorize additional capabilities")
    row.name, row.capabilities = body.name, body.capabilities
    await AuditLogRepository(session).record(
        action="mcp.connection_changed",
        entity_type="mcp_connection",
        entity_id=str(row.id),
        user_id=user.id,
        metadata={"capabilities": body.capabilities},
    )
    await session.commit()
    return connection_payload(row, _settings(request))


# Keep established facade import and serialized function identities.
for _function in (
    connection_payload,
    connections,
    revoke,
    set_connection_access,
    delete_connection,
    update_connection,
):
    _function.__module__ = "app.presentation.api.v1.routes.mcp_admin"
del _function
