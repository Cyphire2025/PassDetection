"""Fixed bearer image transfer and owned ready-image recovery for MCP templates."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.artifacts import ArtifactError
from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.whatsapp_media_access import MCPWhatsAppMediaAccess
from app.application.mcp.whatsapp_media_uploads import MCPWhatsAppMediaUploads
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.mcp_artifacts import _PRIVATE, _failure, _principal
from app.presentation.api.v1.schemas.mcp_transfer_schemas import (
    TRANSFER_ERRORS,
    MCPHeaderAuthority,
    MCPHeaderMedia,
    upload_contract,
)

router = APIRouter(prefix="/mcp/whatsapp-media", tags=["MCP WhatsApp header images"])


@router.post(
    "/uploads",
    status_code=201,
    response_model=MCPHeaderMedia,
    responses=TRANSFER_ERRORS,
    openapi_extra=upload_contract(
        "image/jpeg", "image/png", maximum=5 * 1024 * 1024, idempotency=True
    ),
)
async def upload_header_image(
    request: Request,
    agency_id: uuid.UUID,
    broadcast_id: uuid.UUID,
    filename: str = Query(min_length=1, max_length=255),
    principal: MCPPrincipal = Depends(_principal),
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    try:
        sizes, checksums, keys = (
            request.headers.getlist(name)
            for name in (
                "x-artifact-size",
                "x-artifact-sha256",
                "idempotency-key",
            )
        )
        if (
            len(sizes) != 1
            or len(checksums) != 1
            or len(keys) != 1
            or not sizes[0].isascii()
            or not sizes[0].isdigit()
            or len(sizes[0]) > 12
        ):
            raise ArtifactError("Provide one size, checksum and stable idempotency key", 422)
        result = await MCPWhatsAppMediaUploads(
            session,
            request.app.state.settings,
            storage=getattr(request.app.state, "mcp_whatsapp_media_storage", None),
            security=getattr(request.app.state, "mcp_whatsapp_media_security", None),
        ).upload(
            principal,
            agency_id=agency_id,
            broadcast_id=broadcast_id,
            filename=filename,
            media_type=request.headers.get("content-type", "").split(";", 1)[0],
            expected_size=int(sizes[0]),
            expected_sha256=checksums[0],
            idempotency_key=keys[0],
            body=request.stream(),
        )
        return JSONResponse(result, status_code=201, headers=_PRIVATE)
    except Exception as exc:
        return await _failure(session, principal, exc)


@router.get("/authority", response_model=MCPHeaderAuthority, responses=TRANSFER_ERRORS)
async def header_image_authority(
    request: Request,
    agency_id: uuid.UUID,
    broadcast_id: uuid.UUID,
    principal: MCPPrincipal = Depends(_principal),
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    try:
        access = MCPWhatsAppMediaAccess(session, request.app.state.settings)
        await access.authority(principal)
        await access.scope(agency_id, broadcast_id)
        return JSONResponse(
            {
                "authorized": True,
                "capabilities": ["mcp:upload", "mcp:communicate"],
                "agency_id": str(agency_id),
                "broadcast_id": str(broadcast_id),
            },
            headers=_PRIVATE,
        )
    except Exception as exc:
        return await _failure(session, principal, exc)


@router.get("/{handle}", response_model=MCPHeaderMedia, responses=TRANSFER_ERRORS)
async def inspect_header_image(
    handle: str,
    request: Request,
    principal: MCPPrincipal = Depends(_principal),
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    try:
        result = await MCPWhatsAppMediaAccess(session, request.app.state.settings).observe(
            principal, handle
        )
        await session.commit()
        return JSONResponse(result, headers=_PRIVATE)
    except Exception as exc:
        return await _failure(session, principal, exc)


@router.post(
    "/{media_artifact_id}/recover", response_model=MCPHeaderMedia, responses=TRANSFER_ERRORS
)
async def recover_header_image(
    media_artifact_id: uuid.UUID,
    request: Request,
    principal: MCPPrincipal = Depends(_principal),
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    try:
        result = await MCPWhatsAppMediaAccess(session, request.app.state.settings).recover(
            principal, media_artifact_id
        )
        await session.commit()
        return JSONResponse(result, headers=_PRIVATE)
    except Exception as exc:
        return await _failure(session, principal, exc)
