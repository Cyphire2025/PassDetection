"""Dedicated bearer-only XLSX body upload before any broadcast exists."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.artifacts import ArtifactError
from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.contact_uploads import MCPContactUploadService
from app.infrastructure.database.session import get_db_session
from app.infrastructure.security.contact_spreadsheet_security import XLSX_MEDIA
from app.presentation.api.v1.routes.mcp_artifacts import _PRIVATE, _failure, _principal
from app.presentation.api.v1.schemas.mcp_transfer_schemas import (
    TRANSFER_ERRORS,
    MCPContactUpload,
    upload_contract,
)

router = APIRouter(prefix="/mcp/contact-imports", tags=["MCP contact imports"])


@router.post(
    "/uploads",
    status_code=201,
    response_model=MCPContactUpload,
    responses=TRANSFER_ERRORS,
    openapi_extra=upload_contract(XLSX_MEDIA, maximum=5 * 1024 * 1024),
)
async def upload_contacts(
    request: Request,
    agency_id: uuid.UUID,
    filename: str = Query(min_length=1, max_length=255),
    principal: MCPPrincipal = Depends(_principal),
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    try:
        if request.headers.get("content-type", "").split(";", 1)[0] != XLSX_MEDIA:
            raise ArtifactError("This upload lane accepts XLSX workbooks only", 415)
        raw_size = request.headers.get("x-artifact-size", "")
        if not raw_size.isascii() or not raw_size.isdigit() or len(raw_size) > 12:
            raise ArtifactError("Upload size is required", 422)
        result = await MCPContactUploadService(
            session,
            request.app.state.settings,
            storage=getattr(request.app.state, "mcp_contact_import_storage", None),
            security=getattr(request.app.state, "mcp_contact_import_security", None),
        ).stage(
            principal,
            agency_id=agency_id,
            filename=filename,
            expected_size=int(raw_size),
            expected_sha256=request.headers.get("x-artifact-sha256", ""),
            body=request.stream(),
        )
        await session.commit()
        return JSONResponse(result, status_code=201, headers=_PRIVATE)
    except Exception as exc:
        return await _failure(session, principal, exc)
