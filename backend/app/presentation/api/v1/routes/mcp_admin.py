"""Superadmin-only MCP management through the existing dashboard session and MFA."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.client_policy import DIRECT_CLIENT_NAMES, DIRECT_CLIENT_REDIRECTS
from app.application.mcp.connection_requests import (
    MCPConnectionRequestService,
    admin_request_payload,
)
from app.application.mcp.credentials import MCPAuthError, utc
from app.application.mcp.read_access import current_read_access
from app.core.config.settings import Settings
from app.domain.entities.entities import User
from app.domain.mcp_policy import CAPABILITIES
from app.domain.mcp_read_sections import read_section_catalog
from app.domain.mcp_section_permissions import WRITE_CAPABILITIES
from app.infrastructure.database.mcp_models import (
    MCPConnectionRequestModel,
    MCPControlModel,
    MCPGrantModel,
)
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import AuditLogModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.routes.mcp_admin_files import router as files_router
from app.presentation.api.v1.routes.mcp_permissions import router as permissions_router
from app.presentation.api.v1.schemas.mcp_schemas import (
    MCPConnectionAccessRequest,
    MCPConnectionUpdate,
    MCPConsentRequest,
    MCPControlRequest,
    MCPRequestApproval,
)
from app.presentation.dependencies.auth import require_recent_mfa
from app.presentation.dependencies.csrf import require_cookie_csrf
from app.presentation.dependencies.mcp import require_mcp_management
from app.presentation.mcp.inventory import deployed_inventory
from app.presentation.mcp.management_audit import MCPManagementAuditRoute

router = APIRouter(dependencies=[Depends(require_mcp_management)], route_class=MCPManagementAuditRoute)
router.include_router(files_router)
router.include_router(permissions_router)
_mutations = [Depends(require_cookie_csrf), Depends(require_recent_mfa)]


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def connection_payload(grant: MCPGrantModel, settings: Settings | None = None) -> dict[str, object]:
    effective = set(grant.capabilities) & set(settings.mcp.effective_capabilities) if settings else set(grant.capabilities)
    if grant.read_enabled is not True:
        effective.discard("mcp:read")
    if grant.write_enabled is not True:
        effective.difference_update(WRITE_CAPABILITIES)
    return {
        "id": str(grant.id),
        "user_id": str(grant.user_id),
        "client_id": grant.client_id,
        "name": grant.name,
        "enabled": grant.enabled,
        "read_enabled": grant.read_enabled,
        "write_enabled": grant.write_enabled,
        "allowed_read_sections": grant.allowed_read_sections,
        "allowed_write_sections": grant.allowed_write_sections,
        "permission_revision": grant.permission_revision,
        "device_platform": grant.device_platform,
        "capabilities": grant.capabilities,
        "effective_capabilities": sorted(effective),
        "created_at": grant.created_at,
        "expires_at": grant.expires_at,
        "last_used_at": grant.last_used_at,
        "revoked_at": grant.revoked_at,
        "status": "revoked"
        if grant.revoked_at
        else "expired"
        if utc(grant.expires_at) <= datetime.now(UTC)
        else "disabled"
        if not grant.enabled
        else "active",
    }


@router.get("")
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
        "defined_capabilities": ["mcp:read"] if settings.mcp.read_only_mode else sorted(CAPABILITIES),
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


@router.get("/connections")
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
                # Explicitly removed entries retain their grant and workflow
                # provenance. Other revoked entries remain in the Devices list.
                .where(or_(
                    MCPGrantModel.revoked_at.is_(None),
                    MCPGrantModel.revocation_reason.is_(None),
                    MCPGrantModel.revocation_reason != "administrator_removed",
                ))
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


@router.get("/connection-requests")
async def connection_requests(offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=100),
                              session: AsyncSession = Depends(get_db_session)) -> dict[str, object]:
    from datetime import timedelta

    rows = list((await session.scalars(select(MCPConnectionRequestModel).where(
        MCPConnectionRequestModel.created_at > datetime.now(UTC) - timedelta(hours=1)
    ).order_by(MCPConnectionRequestModel.created_at.desc(), MCPConnectionRequestModel.id.desc())
       .offset(offset).limit(limit + 1))).all())
    return {"items": [admin_request_payload(row) for row in rows[:limit]],
            "next_offset": offset + limit if len(rows) > limit else None}


@router.post("/connection-requests/{request_id}/approve", dependencies=_mutations)
async def approve_connection_request(request_id: uuid.UUID, body: MCPRequestApproval, request: Request,
                                     user: User = Depends(require_mcp_management),
                                     session: AsyncSession = Depends(get_db_session)) -> dict[str, object]:
    try:
        row = await MCPConnectionRequestService(session, _settings(request)).decide(request_id, approved=True,
            user_id=user.id, security_version=user.session_version,
            mfa_at=datetime.fromtimestamp(request.state.auth_claims["mfa_at"], UTC), name=body.name,
            platform=body.device_platform, capabilities=body.capabilities,
            read_enabled=body.read_enabled, write_enabled=body.write_enabled,
            allowed_read_sections=body.allowed_read_sections, allowed_write_sections=body.allowed_write_sections)
    except MCPAuthError as exc:
        raise HTTPException(exc.status_code, exc.error) from exc
    await session.commit()
    return admin_request_payload(row)


@router.post("/connection-requests/{request_id}/reject", dependencies=_mutations)
async def reject_connection_request(request_id: uuid.UUID, request: Request,
                                    user: User = Depends(require_mcp_management),
                                    session: AsyncSession = Depends(get_db_session)) -> dict[str, object]:
    try:
        row = await MCPConnectionRequestService(session, _settings(request)).decide(request_id, approved=False,
            user_id=user.id, security_version=user.session_version,
            mfa_at=datetime.fromtimestamp(request.state.auth_claims["mfa_at"], UTC))
    except MCPAuthError as exc:
        raise HTTPException(exc.status_code, exc.error) from exc
    await session.commit()
    return admin_request_payload(row)


@router.post("/authorize", dependencies=_mutations)
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
        {"redirect_url": body.redirect_uri + "?" + urlencode({"code": code, "state": body.state, "iss": _settings(request).mcp.public_origin})},
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


@router.put("/control", dependencies=_mutations)
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


@router.post("/connections/{connection_id}/revoke", dependencies=_mutations)
async def revoke(
    connection_id: uuid.UUID,
    user: User = Depends(require_mcp_management),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, bool]:
    row = await session.scalar(
        select(MCPGrantModel).where(MCPGrantModel.id == connection_id).with_for_update()
    )
    if row is None:
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


@router.patch("/connections/{connection_id}/access", dependencies=_mutations)
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
    if row is None:
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


@router.delete("/connections/{connection_id}", dependencies=_mutations)
async def delete_connection(
    connection_id: uuid.UUID,
    user: User = Depends(require_mcp_management),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, bool]:
    row = await session.scalar(
        select(MCPGrantModel).where(MCPGrantModel.id == connection_id)
        .execution_options(populate_existing=True).with_for_update()
    )
    if row is None:
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


@router.patch("/connections/{connection_id}", dependencies=_mutations)
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
    if row is None:
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


@router.get("/activity")
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


@router.get("/inventory")
async def inventory(request: Request) -> dict[str, object]:
    return await deployed_inventory(request.app, _settings(request))


@router.get("/operations")
async def operations(
    request: Request,
    offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    if _settings(request).mcp.read_only_mode:
        raise HTTPException(403, "MCP workflow controls are unavailable in this read-only deployment")
    rows = list((await session.scalars(select(MCPOperationModel)
        .order_by(MCPOperationModel.created_at.desc(), MCPOperationModel.id.desc())
        .offset(offset).limit(limit + 1))).all())
    return {"items": [{"id": str(row.id), "user_id": str(row.user_id),
        "connection_id": str(row.initial_grant_id), "operation": row.operation_name,
        "workflow_id": str(row.workflow_id), "status": row.status, "progress": row.progress,
        "stage": row.stage, "revision": row.revision, "created_entities": row.created_entities,
        "created_at": row.created_at, "updated_at": row.updated_at, "completed_at": row.completed_at}
        for row in rows[:limit]], "next_offset": offset + limit if len(rows) > limit else None}
