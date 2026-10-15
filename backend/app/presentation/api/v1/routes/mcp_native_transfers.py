"""Limited bearer transport for one prepared native file; no dashboard authority."""

import json
import uuid

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.artifacts import ArtifactError, MCPArtifactService
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.native_transfer_runtime import (
    acknowledge_delivery,
    download_content,
    prepare_download,
    upload_content,
)
from app.application.mcp.native_transfers import MCPNativeTransferService
from app.domain.contact_workbook import ContactWorkbookValidationError
from app.domain.exceptions.exceptions import ImageValidationError, StorageError
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.security.upload_security import UploadSecurityEvidenceError
from app.infrastructure.security.upload_validator import (
    DocumentIngestionDisabledError,
    MalwareScannerConfigurationError,
    MalwareScannerUnavailableError,
)
from app.presentation.api.v1.routes.mcp_artifacts import _BoundedResponse
from app.presentation.api.v1.schemas.mcp_native_transfer_schemas import MCPNativeDeliveryRequest

router = APIRouter(prefix="/mcp/native-transfers", tags=["MCP native transfers"])
PRIVATE = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def native_service(app: FastAPI, session: AsyncSession) -> MCPNativeTransferService:
    return MCPNativeTransferService(
        session,
        app.state.settings,
        artifacts=MCPArtifactService(
            session,
            app.state.settings,
            storage=getattr(app.state, "mcp_artifact_storage", None),
            security=getattr(app.state, "mcp_artifact_security", None),
        ),
        contact_storage=getattr(
            app.state, "mcp_contact_storage", getattr(app.state, "mcp_artifact_storage", None)
        ),
        contact_security=getattr(app.state, "mcp_contact_security", None),
    )


def credential(request: Request) -> str:
    headers = request.headers.getlist("authorization")
    origins = request.headers.getlist("origin")
    if len(headers) != 1 or not headers[0].startswith("Bearer ") or request.query_params:
        raise MCPAuthError("invalid_token", 401)
    settings = request.app.state.settings
    if origins and (
        len(origins) != 1
        or origins[0] not in {settings.mcp.frontend_origin, settings.mcp.public_origin}
    ):
        raise MCPAuthError("access_denied", 403)
    return headers[0][7:]


async def failure(session: AsyncSession, error: Exception) -> JSONResponse:
    await session.rollback()
    if isinstance(error, MCPAuthError):
        status, message = error.status_code, error.error
    elif isinstance(error, ArtifactError):
        status, message = error.status_code, str(error)
    elif isinstance(error, (ImageValidationError, ContactWorkbookValidationError)):
        status, message = 422, "File validation or security scanning rejected this upload"
    elif isinstance(error, (ValidationError, ValueError, UnicodeDecodeError)):
        status, message = 422, "Invalid transfer acknowledgement"
    elif isinstance(error, TimeoutError):
        status, message = 408, "Transfer timed out"
    elif isinstance(
        error,
        (
            MalwareScannerUnavailableError,
            UploadSecurityEvidenceError,
            DocumentIngestionDisabledError,
            MalwareScannerConfigurationError,
            StorageError,
        ),
    ):
        status, message = 503, "File security scanning or storage is unavailable"
    else:
        status, message = 503, "Native file transfer is unavailable"
    await AuditLogRepository(session).record(
        action="mcp.native_transfer_request_failed",
        entity_type="mcp_native_transfer",
        result="denied" if status in {401, 403, 404} else "failed",
        metadata={"status": status},
    )
    await session.commit()
    return JSONResponse({"detail": message}, status_code=status, headers=PRIVATE)


@router.get("/{transfer_id}")
async def metadata(
    transfer_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_db_session)
) -> JSONResponse:
    try:
        service = native_service(request.app, session)
        row, _ = await service.limited(
            transfer_id, credential(request), name="inspect_native_transfer"
        )
        result = await service.metadata(row)
        await session.commit()
        return JSONResponse(result, headers=PRIVATE)
    except Exception as error:
        return await failure(session, error)


@router.put("/{transfer_id}/content")
async def upload(
    transfer_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_db_session)
) -> JSONResponse:
    try:
        service, secret = native_service(request.app, session), credential(request)
        row, _ = await service.limited(transfer_id, secret, name="create_native_upload")
        if request.headers.get("content-type", "").split(";", 1)[0] != row.media_type:
            raise ArtifactError("The content type must match this prepared transfer", 415)
        lengths = request.headers.getlist("content-length")
        if lengths and (
            len(lengths) != 1
            or len(lengths[0]) > 12
            or not lengths[0].isascii()
            or not lengths[0].isdigit()
            or int(lengths[0]) != row.byte_size
        ):
            raise ArtifactError("The content length must match this prepared transfer", 422)
        result = await upload_content(service, transfer_id, secret, request.stream())
        await session.commit()
        return JSONResponse(result, headers=PRIVATE)
    except Exception as error:
        return await failure(session, error)


@router.get("/{transfer_id}/content", response_model=None, response_class=StreamingResponse)
async def download(
    transfer_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_db_session)
) -> StreamingResponse | JSONResponse:
    try:
        if request.headers.get("range") is not None:
            raise ArtifactError("Partial downloads are not supported", 416)
        service, secret = native_service(request.app, session), credential(request)
        row, principal, artifact = await prepare_download(service, transfer_id, secret)
    except Exception as error:
        return await failure(session, error)
    return _BoundedResponse(
        download_content(service, transfer_id, secret, principal, artifact),
        media_type=row.media_type,
        headers={
            **PRIVATE,
            "Content-Length": str(row.byte_size),
            "Content-Disposition": f'attachment; filename="{row.filename}"',
            "X-Artifact-SHA256": row.sha256,
            "X-Artifact-Size": str(row.byte_size),
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.post("/{transfer_id}/delivery")
async def delivery(
    transfer_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_db_session)
) -> JSONResponse:
    try:
        secret = credential(request)
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise ArtifactError("JSON acknowledgement is required", 415)
        raw = bytearray()
        async for part in request.stream():
            if len(raw) + len(part) > 1024:
                raise ArtifactError("Acknowledgement is too large", 413)
            raw.extend(part)
        payload = MCPNativeDeliveryRequest.model_validate(json.loads(raw))
        result = await acknowledge_delivery(
            native_service(request.app, session),
            transfer_id,
            secret,
            byte_size=payload.byte_size,
            sha256=payload.sha256,
        )
        await session.commit()
        return JSONResponse(result, headers=PRIVATE)
    except Exception as error:
        return await failure(session, error)
