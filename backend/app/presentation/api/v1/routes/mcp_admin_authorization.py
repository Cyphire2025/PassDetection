"""Dashboard approval decisions and emergency control with caller-owned transactions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from urllib.parse import urlencode

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.connection_requests import (
    MCPConnectionRequestService,
    admin_request_payload,
)
from app.application.mcp.credentials import MCPAuthError
from app.domain.entities.entities import User
from app.infrastructure.database.mcp_models import MCPConnectionRequestModel, MCPControlModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.schemas.mcp_schemas import (
    MCPConsentRequest,
    MCPControlRequest,
    MCPRequestApproval,
)
from app.presentation.dependencies.mcp import require_mcp_management

from .mcp_admin_context import _settings


async def connection_requests(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    from datetime import timedelta

    rows = list(
        (
            await session.scalars(
                select(MCPConnectionRequestModel)
                .where(
                    MCPConnectionRequestModel.created_at > datetime.now(UTC) - timedelta(hours=1)
                )
                .order_by(
                    MCPConnectionRequestModel.created_at.desc(), MCPConnectionRequestModel.id.desc()
                )
                .offset(offset)
                .limit(limit + 1)
            )
        ).all()
    )
    return {
        "items": [admin_request_payload(row) for row in rows[:limit]],
        "next_offset": offset + limit if len(rows) > limit else None,
    }


async def approve_connection_request(
    request_id: uuid.UUID,
    body: MCPRequestApproval,
    request: Request,
    user: User = Depends(require_mcp_management),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    try:
        row = await MCPConnectionRequestService(session, _settings(request)).decide(
            request_id,
            approved=True,
            user_id=user.id,
            security_version=user.session_version,
            mfa_at=datetime.fromtimestamp(request.state.auth_claims["mfa_at"], UTC),
            name=body.name,
            platform=body.device_platform,
            capabilities=body.capabilities,
            read_enabled=body.read_enabled,
            write_enabled=body.write_enabled,
            allowed_read_sections=body.allowed_read_sections,
            allowed_write_sections=body.allowed_write_sections,
        )
    except MCPAuthError as exc:
        raise HTTPException(exc.status_code, exc.error) from exc
    await session.commit()
    return admin_request_payload(row)


async def reject_connection_request(
    request_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_mcp_management),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    try:
        row = await MCPConnectionRequestService(session, _settings(request)).decide(
            request_id,
            approved=False,
            user_id=user.id,
            security_version=user.session_version,
            mfa_at=datetime.fromtimestamp(request.state.auth_claims["mfa_at"], UTC),
        )
    except MCPAuthError as exc:
        raise HTTPException(exc.status_code, exc.error) from exc
    await session.commit()
    return admin_request_payload(row)


async def authorize(
    body: MCPConsentRequest,
    request: Request,
    user: User = Depends(require_mcp_management),
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    service = MCPAuthorizationService(session, _settings(request))
    claims = request.state.auth_claims
    try:
        code = await service.authorize(
            user_id=user.id,
            security_version=user.session_version,
            mfa_at=datetime.fromtimestamp(claims["mfa_at"], UTC),
            client_id=body.client_id,
            redirect_uri=body.redirect_uri,
            resource=body.resource,
            challenge=body.code_challenge,
            scopes=body.scopes,
            name=body.name,
            device_platform=body.device_platform,
            read_enabled=body.read_enabled,
            write_enabled=body.write_enabled,
            allowed_read_sections=body.allowed_read_sections,
            allowed_write_sections=body.allowed_write_sections,
        )
    except MCPAuthError as exc:
        return JSONResponse(
            {"error": exc.error}, status_code=exc.status_code, headers={"Cache-Control": "no-store"}
        )
    # Persist before exposing a code, including for transports which finalize dependencies late.
    await session.commit()
    return JSONResponse(
        {
            "redirect_url": body.redirect_uri
            + "?"
            + urlencode(
                {"code": code, "state": body.state, "iss": _settings(request).mcp.public_origin}
            )
        },
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


async def control(
    body: MCPControlRequest,
    request: Request,
    user: User = Depends(require_mcp_management),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, bool]:
    if body.enabled and not _settings(request).mcp.enabled:
        raise HTTPException(409, "MCP has not been enabled in this deployment")
    row = await session.scalar(
        select(MCPControlModel).where(MCPControlModel.id == 1).with_for_update()
    )
    if row is None:
        raise HTTPException(503, "MCP schema has not been initialized")
    row.enabled, row.updated_at = body.enabled, datetime.now(UTC)
    await AuditLogRepository(session).record(
        action="mcp.control_changed",
        entity_type="mcp_control",
        user_id=user.id,
        metadata={"enabled": body.enabled},
    )
    await session.commit()
    return {"enabled": body.enabled}


# Keep established facade import and serialized function identities.
for _function in (
    connection_requests,
    approve_connection_request,
    reject_connection_request,
    authorize,
    control,
):
    _function.__module__ = "app.presentation.api.v1.routes.mcp_admin"
del _function
