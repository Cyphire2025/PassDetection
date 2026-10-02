"""OAuth authorization-server boundary; no dashboard passwords or JWT forwarding."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import cast
from urllib.parse import parse_qsl, urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.client_policy import validate_authorization_client, validate_resource
from app.application.mcp.connection_requests import (
    MCPConnectionRequestService,
    public_request_payload,
    request_cookie_name,
)
from app.application.mcp.credentials import PKCE_CHALLENGE, MCPAuthError
from app.core.config.settings import Settings
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.schemas.mcp_schemas import MCPRequestLabels
from app.presentation.security.client_ip import trusted_client_ip

router = APIRouter()
_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache", "Referrer-Policy": "no-referrer"}


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


@router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
async def metadata(request: Request) -> dict[str, object]:
    origin = _settings(request).mcp.public_origin
    return {
        "issuer": origin,
        "authorization_response_iss_parameter_supported": True,
        "client_id_metadata_document_supported": True,
        "authorization_endpoint": f"{origin}/oauth/mcp/authorize",
        "token_endpoint": f"{origin}/oauth/mcp/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": _settings(request).mcp.effective_capabilities,
    }


@router.get("/oauth/mcp/authorize", include_in_schema=False, response_model=None)
async def authorization_start(request: Request, session: AsyncSession = Depends(get_db_session)) -> RedirectResponse | JSONResponse:
    settings = _settings(request)
    params = request.query_params
    try:
        if len(params.multi_items()) != len(params) or len(str(params)) > 4096:
            raise MCPAuthError("invalid_request")
        await validate_authorization_client(settings.mcp, params.get("client_id", ""), params.get("redirect_uri", ""))
        validate_resource(settings.mcp, params.get("resource", ""))
        if (
            params.get("response_type") != "code"
            or params.get("code_challenge_method") != "S256"
            or not PKCE_CHALLENGE.fullmatch(params.get("code_challenge", ""))
            or not 16 <= len(params.get("state", "")) <= 512
            or not set(params.get("scope", "").split()) <= set(settings.mcp.effective_capabilities)
            or not params.get("scope", "").strip()
        ):
            raise MCPAuthError("invalid_request")
    except MCPAuthError as exc:
        # Invalid redirects never receive a redirect, including OAuth errors.
        return JSONResponse({"error": exc.error}, status_code=exc.status_code, headers=_NO_STORE)
    resume = {}
    for name, value in list(request.cookies.items())[:40]:
        match = re.fullmatch(r"gc_mcp_request_([a-f0-9]{32})", name)
        if match and value.startswith("gcmcp_request_") and len(value) <= 128:
            resume[uuid.UUID(hex=match[1])] = value
    agent = request.headers.get("user-agent", "")[:512]
    platform = "Windows" if "Windows" in agent else "macOS" if "Macintosh" in agent or "Mac OS X" in agent else "Other"
    try:
        row, secret = await MCPConnectionRequestService(session, settings).create(
            client_id=params["client_id"], redirect_uri=params["redirect_uri"], resource=params["resource"],
            state=params["state"], challenge=params["code_challenge"], scopes=params["scope"].split(),
            platform=platform, source=trusted_client_ip(request, settings=settings) or "unknown", resume=resume,
        )
        await session.commit()
    except MCPAuthError as exc:
        await session.rollback()
        return JSONResponse({"error": exc.error}, status_code=exc.status_code, headers=_NO_STORE)
    response = RedirectResponse(f"{settings.mcp.frontend_origin}/mcp/connect?{urlencode({'request_id': str(row.id)})}",
        status_code=303, headers=_NO_STORE)
    lifetime = max(0, int((row.expires_at.replace(tzinfo=UTC) if row.expires_at.tzinfo is None else row.expires_at).timestamp() - datetime.now(UTC).timestamp()))
    # The request capability is scoped to its public route. A second HttpOnly
    # authorize-only cookie permits exact-parameter resume without URL secrets.
    for path in (f"/oauth/mcp/requests/{row.id}", "/oauth/mcp/authorize"):
        response.set_cookie(request_cookie_name(row.id), secret, max_age=lifetime,
            httponly=True, secure=settings.mcp.public_origin.startswith("https://"), samesite="lax", path=path)
    return response


def _request_credential(request: Request, identifier: uuid.UUID, *, mutation: bool = False) -> str:
    if request.headers.get("X-MCP-Request") != str(identifier):
        raise MCPAuthError("request_unavailable", 404)
    if mutation:
        origin = request.headers.get("origin")
        if origin not in {_settings(request).mcp.frontend_origin, _settings(request).mcp.public_origin}:
            raise MCPAuthError("access_denied", 403)
    return request.cookies.get(request_cookie_name(identifier), "")


@router.get("/oauth/mcp/requests/{request_id}", include_in_schema=False)
async def request_status(request_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_db_session)) -> JSONResponse:
    from fastapi.encoders import jsonable_encoder

    try:
        row = await MCPConnectionRequestService(session, _settings(request)).requester(
            request_id, _request_credential(request, request_id))
    except MCPAuthError as exc:
        return JSONResponse({"error": exc.error}, status_code=exc.status_code, headers=_NO_STORE)
    return JSONResponse(jsonable_encoder(public_request_payload(row)), headers=_NO_STORE)


@router.patch("/oauth/mcp/requests/{request_id}", include_in_schema=False)
async def request_labels(request_id: uuid.UUID, body: MCPRequestLabels, request: Request,
                         session: AsyncSession = Depends(get_db_session)) -> JSONResponse:
    from fastapi.encoders import jsonable_encoder

    service = MCPConnectionRequestService(session, _settings(request))
    try:
        row = await service.requester(request_id, _request_credential(request, request_id, mutation=True), lock=True)
        await service.update_labels(row, name=body.name, platform=body.device_platform)
        await session.commit()
    except MCPAuthError as exc:
        await session.rollback()
        return JSONResponse({"error": exc.error}, status_code=exc.status_code, headers=_NO_STORE)
    return JSONResponse(jsonable_encoder(public_request_payload(row)), headers=_NO_STORE)


@router.post("/oauth/mcp/requests/{request_id}/finalize", include_in_schema=False)
async def request_finalize(request_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_db_session)) -> JSONResponse:
    try:
        result = await MCPConnectionRequestService(session, _settings(request)).finalize(
            request_id, _request_credential(request, request_id, mutation=True))
        await session.commit()
    except MCPAuthError as exc:
        await session.rollback()
        return JSONResponse({"error": exc.error}, status_code=exc.status_code, headers=_NO_STORE)
    response = JSONResponse(result, headers=_NO_STORE)
    for path in (f"/oauth/mcp/requests/{request_id}", "/oauth/mcp/authorize"):
        response.delete_cookie(request_cookie_name(request_id), path=path, httponly=True,
            secure=_settings(request).mcp.public_origin.startswith("https://"), samesite="lax")
    return response


async def _token_form(request: Request) -> dict[str, str]:
    if (
        request.headers.get("content-type", "").split(";", 1)[0]
        != "application/x-www-form-urlencoded"
    ):
        raise MCPAuthError("invalid_request")
    raw = bytearray()
    async for part in request.stream():
        raw.extend(part)
        if len(raw) > 16384:
            raise MCPAuthError("invalid_request", 413)
    try:
        fields = parse_qsl(
            raw.decode("utf-8"), keep_blank_values=True, strict_parsing=True, max_num_fields=12
        )
    except (ValueError, UnicodeDecodeError) as exc:
        raise MCPAuthError("invalid_request") from exc
    form = dict(fields)
    if len(form) != len(fields):
        raise MCPAuthError("invalid_request")
    return form


@router.post("/oauth/mcp/token", include_in_schema=False)
async def token(request: Request, session: AsyncSession = Depends(get_db_session)) -> JSONResponse:
    service = MCPAuthorizationService(session, _settings(request))
    try:
        form = await _token_form(request)
        grant_type = form.get("grant_type")
        if grant_type == "authorization_code":
            result = await service.exchange_code(
                code=form.get("code", ""),
                verifier=form.get("code_verifier", ""),
                client_id=form.get("client_id", ""),
                redirect_uri=form.get("redirect_uri", ""),
                resource=form.get("resource", ""),
            )
        elif grant_type == "refresh_token":
            result = await service.refresh(
                token=form.get("refresh_token", ""),
                client_id=form.get("client_id", ""),
                resource=form.get("resource", ""),
            )
        else:
            raise MCPAuthError("unsupported_grant_type")
    except MCPAuthError as exc:
        await AuditLogRepository(session).record(
            action="mcp.token_denied",
            entity_type="mcp_connection",
            result="denied",
            metadata={"reason": exc.error},
        )
        # Reuse revocation and the denied audit must survive this rejected exchange.
        await session.commit()
        return JSONResponse({"error": exc.error}, status_code=exc.status_code, headers=_NO_STORE)
    await session.commit()
    return JSONResponse(result, headers=_NO_STORE)
