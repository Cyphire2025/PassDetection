"""Dedicated MCP bearer-only file transport, mounted before the /mcp child app."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Literal

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Security
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import Receive, Scope, Send

from app.application.mcp.artifacts import ArtifactError, MCPArtifactService, transfer_slot
from app.application.mcp.authorization import MCPAuthorizationService, MCPPrincipal
from app.application.mcp.credentials import MCPAuthError
from app.application.use_cases.passports.complete_export_delivery import ExportDeliveryConflict
from app.domain.exceptions.exceptions import ImageValidationError, StorageError
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.security.upload_security import UploadSecurityEvidenceError
from app.infrastructure.security.upload_validator import (
    DocumentIngestionDisabledError,
    MalwareScannerConfigurationError,
    MalwareScannerUnavailableError,
)
from app.presentation.api.v1.schemas.mcp_transfer_schemas import (
    CONTENT_RESPONSES,
    DELIVERY_CONTRACT,
    TRANSFER_ERRORS,
    DeliveryAcknowledgement,
    MCPArtifactMetadata,
    MCPFileAuthority,
    upload_contract,
)

router = APIRouter(prefix="/mcp/artifacts", tags=["MCP artifacts"])
_PRIVATE = {"Cache-Control": "no-store", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff"}
_bearer_metadata = HTTPBearer(auto_error=False)


async def _principal(
    request: Request, session: AsyncSession = Depends(get_db_session),
    _documented_bearer: HTTPAuthorizationCredentials | None = Security(_bearer_metadata),
) -> MCPPrincipal:
    # The optional security dependency documents the existing bearer scheme only.
    # Authorization still requires the exact single raw header below.
    try:
        headers = request.headers.getlist("authorization")
        if len(headers) != 1 or not headers[0].startswith("Bearer "):
            raise MCPAuthError("invalid_token", 401)
        # Dashboard JWTs cannot satisfy verify_access's dedicated token format.
        principal = await MCPAuthorizationService(
            session, request.app.state.settings
        ).verify_access(headers[0][7:])
        # Release the verifier's last-used write before the service acquires
        # control -> grant -> identity locks for a mutation. The service then
        # revalidates current authority before creating or acknowledging a row.
        await session.commit()
        return principal
    except MCPAuthError as exc:
        await AuditLogRepository(session).record(
            action="mcp.artifact_access_denied",
            entity_type="mcp_artifact",
            result="denied",
            metadata={"reason": exc.error},
        )
        await session.commit()
        raise HTTPException(
            status_code=401 if exc.status_code == 400 else exc.status_code,
            detail=exc.error,
            headers={**_PRIVATE, "WWW-Authenticate": "Bearer"},
        ) from None


def _service(request: Request, session: AsyncSession) -> MCPArtifactService:
    return MCPArtifactService(
        session,
        request.app.state.settings,
        storage=getattr(request.app.state, "mcp_artifact_storage", None),
        security=getattr(request.app.state, "mcp_artifact_security", None),
    )


async def _failure(session: AsyncSession, principal: MCPPrincipal, exc: Exception) -> JSONResponse:
    await session.rollback()
    if isinstance(exc, MCPAuthError):
        code, message = (401 if exc.status_code == 400 else exc.status_code), exc.error
    elif isinstance(exc, ArtifactError):
        code, message = exc.status_code, str(exc)
    elif isinstance(exc, ExportDeliveryConflict):
        code, message = 409, str(exc)
    elif isinstance(
        exc,
        (
            MalwareScannerUnavailableError,
            UploadSecurityEvidenceError,
            DocumentIngestionDisabledError,
            MalwareScannerConfigurationError,
        ),
    ):
        code, message = 503, "Document security scanning is unavailable"
    elif isinstance(exc, ImageValidationError):
        code, message = 422, "Upload failed document validation or security scanning"
    elif isinstance(exc, TimeoutError):
        code, message = 408, "Transfer timed out"
    elif isinstance(exc, (ValidationError, json.JSONDecodeError, UnicodeDecodeError)):
        code, message = 422, "Invalid delivery acknowledgement"
    elif isinstance(exc, StorageError):
        code, message = 503, "Artifact storage is unavailable"
    else:
        code, message = 503, "Artifact transfer is unavailable"
    await AuditLogRepository(session).record(
        action="mcp.artifact_request_failed",
        entity_type="mcp_artifact",
        user_id=principal.user_id,
        result="denied" if code in {401, 403, 404} else "failed",
        metadata={"grant_id": str(principal.grant_id), "status": code},
    )
    await session.commit()
    return JSONResponse({"detail": message}, status_code=code, headers=_PRIVATE)


@router.get("/authority", response_model=MCPFileAuthority, responses=TRANSFER_ERRORS)
async def file_authority(
    request: Request,
    capability: Literal["mcp:upload", "mcp:export"] | None = None,
    principal: MCPPrincipal = Depends(_principal),
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Recheck current authority before the connector reveals or reads selected local files."""
    try:
        authorization = MCPAuthorizationService(session, request.app.state.settings)
        grant = await authorization.require_grant(principal.grant_id)
        available = sorted(set(grant.capabilities) & set(request.app.state.settings.mcp.enabled_capabilities)
                           & {"mcp:upload", "mcp:export"})
        if not available or capability is not None and capability not in available:
            raise MCPAuthError("insufficient_scope", 403)
        await AuditLogRepository(session).record(
            action="mcp.file_authority_checked", entity_type="mcp_connection",
            entity_id=str(grant.id), user_id=principal.user_id, result="success",
            metadata={"capability": capability})
        await session.commit()
        return JSONResponse({"authorized": True, "capabilities": available}, headers=_PRIVATE)
    except Exception as exc:
        return await _failure(session, principal, exc)


@router.post("/uploads", status_code=201, response_model=MCPArtifactMetadata,
             responses=TRANSFER_ERRORS, openapi_extra=upload_contract("application/pdf"))
async def upload_pdf(
    request: Request,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    filename: str = Query(min_length=1, max_length=255),
    principal: MCPPrincipal = Depends(_principal),
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    try:
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/pdf":
            raise ArtifactError("This upload lane accepts PDF documents only", 415)
        raw_size = request.headers.get("x-artifact-size", "")
        if not raw_size.isascii() or not raw_size.isdigit() or len(raw_size) > 12:
            raise ArtifactError("Upload size is required", 422)
        result = await _service(request, session).stage_pdf(
            principal,
            agency_id=agency_id,
            group_id=group_id,
            filename=filename,
            expected_size=int(raw_size),
            expected_sha256=request.headers.get("x-artifact-sha256", ""),
            body=request.stream(),
        )
        await session.commit()
        return JSONResponse(result, status_code=201, headers=_PRIVATE)
    except Exception as exc:
        return await _failure(session, principal, exc)


@router.get("/{handle}", response_model=MCPArtifactMetadata, responses=TRANSFER_ERRORS)
async def artifact_metadata(
    request: Request,
    handle: str,
    principal: MCPPrincipal = Depends(_principal),
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    try:
        service = _service(request, session)
        row = await service.get(principal, handle)
        await service.audit("metadata_read", row)
        result = await service.describe(row, handle)
        await session.commit()
        return JSONResponse(result, headers=_PRIVATE)
    except Exception as exc:
        return await _failure(session, principal, exc)


class _BoundedResponse(StreamingResponse):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Acquire in the same request before any response headers are sent.
        try:
            async with transfer_slot():
                await super().__call__(scope, receive, send)
        except ArtifactError as exc:
            # Only saturation is raised before streaming; stream errors must
            # propagate as an interrupted response, never a second response.
            if exc.status_code != 503:
                raise
            await JSONResponse({"detail": str(exc)}, status_code=503, headers=_PRIVATE)(
                scope, receive, send
            )


@router.get("/{handle}/content", response_model=None, response_class=StreamingResponse, responses=CONTENT_RESPONSES)
async def artifact_content(
    request: Request,
    handle: str,
    principal: MCPPrincipal = Depends(_principal),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse | JSONResponse:
    service = _service(request, session)
    try:
        if request.headers.get("range") is not None:
            raise ArtifactError("Partial downloads are not supported", 416)
        row = await service.get(principal, handle)
        await service.validate_storage(row)
        await service.audit("download_started", row)
        await session.commit()
    except Exception as exc:
        return await _failure(session, principal, exc)

    async def body() -> AsyncIterator[bytes]:
        try:
            async for part in service.stream(principal, handle, row):
                yield part
            await session.commit()
        except BaseException:
            # No completion marker survives cancellation, transport failure,
            # checksum mismatch, expiry, or a revoked grant at stream end.
            with anyio.CancelScope(shield=True):
                await session.rollback()
            raise

    return _BoundedResponse(
        body(),
        media_type=row.media_type,
        headers={
            **_PRIVATE,
            "Content-Length": str(row.byte_size),
            "Content-Disposition": f'attachment; filename="{row.filename}"',
            "X-Artifact-SHA256": row.sha256,
            "X-Artifact-Size": str(row.byte_size),
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.post("/{handle}/delivery", response_model=MCPArtifactMetadata,
             responses=TRANSFER_ERRORS, openapi_extra=DELIVERY_CONTRACT)
async def acknowledge_delivery(
    request: Request,
    handle: str,
    principal: MCPPrincipal = Depends(_principal),
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    try:
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise ArtifactError("JSON acknowledgement is required", 415)
        raw = bytearray()
        async for part in request.stream():
            if len(raw) + len(part) > 1024:
                raise ArtifactError("Acknowledgement is too large", 413)
            raw.extend(part)
        payload = DeliveryAcknowledgement.model_validate(json.loads(raw))
        result = await _service(request, session).acknowledge(
            principal,
            handle,
            byte_size=payload.byte_size,
            sha256=payload.sha256,
        )
        await session.commit()
        return JSONResponse(result, headers=_PRIVATE)
    except Exception as exc:
        return await _failure(session, principal, exc)
