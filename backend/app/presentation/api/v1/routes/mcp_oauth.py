"""OAuth authorization-server boundary; no dashboard passwords or JWT forwarding."""

from __future__ import annotations

from typing import cast
from urllib.parse import parse_qsl, urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.client_policy import validate_client, validate_resource
from app.application.mcp.credentials import PKCE_CHALLENGE, MCPAuthError
from app.core.config.settings import Settings
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository

router = APIRouter()
_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


@router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
async def metadata(request: Request) -> dict[str, object]:
    origin = _settings(request).mcp.public_origin
    return {
        "issuer": origin,
        "authorization_endpoint": f"{origin}/oauth/mcp/authorize",
        "token_endpoint": f"{origin}/oauth/mcp/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": _settings(request).mcp.effective_capabilities,
    }


@router.get("/oauth/mcp/authorize", include_in_schema=False, response_model=None)
async def authorization_start(request: Request) -> RedirectResponse | JSONResponse:
    settings = _settings(request)
    params = request.query_params
    try:
        if len(params.multi_items()) != len(params) or len(str(params)) > 4096:
            raise MCPAuthError("invalid_request")
        validate_client(settings.mcp, params.get("client_id", ""), params.get("redirect_uri", ""))
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
    approved = {
        key: params[key]
        for key in (
            "client_id",
            "redirect_uri",
            "resource",
            "response_type",
            "code_challenge_method",
            "code_challenge",
            "state",
            "scope",
        )
    }
    return RedirectResponse(
        f"{settings.mcp.frontend_origin}/admin/mcp/connect?{urlencode(approved)}",
        status_code=303,
        headers=_NO_STORE,
    )


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
