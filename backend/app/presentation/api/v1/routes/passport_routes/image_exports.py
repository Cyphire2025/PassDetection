"""Passport image exports: focused workflow boundary."""

from __future__ import annotations

import io
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.passports.prepare_image_export import (
    ImagePreparationError,
    ImagePreparationSupport,
    prepare_image_export,
)
from app.core.logging.logger import get_logger
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import AuthorizationError, StorageError
from app.infrastructure.database.session import get_db_session
from app.infrastructure.export.passport_image_zip_exporter import (
    MissingPassportImagesError,
    PassportImageExportLimitError,
    PassportImageZipExporter,
    safe_download_filename,
)
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_export_history_repository import (
    PassportExportHistoryRepository,
    PassportExportMode,
)
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.response_contracts import binary_responses
from app.presentation.api.v1.schemas.passport_schemas import ExportSelectedPassportImagesRequest
from app.presentation.dependencies.auth import get_current_active_user

from .constants import (
    SELECTED_PASSPORT_IMAGE_EXPORT_MAX_BYTES,
    _export_people_snapshot,
    _export_zone_names,
)
from .export_context import (
    _current_group_export_submissions,
    _require_new_export_request,
    _resolve_group_export_payload,
)
from .response_support import _owner_scope_for, _stream_binary_file

router = APIRouter()

logger = get_logger(__name__)


def image_export_support() -> ImagePreparationSupport:
    return ImagePreparationSupport(
        _current_group_export_submissions, _resolve_group_export_payload,
        _owner_scope_for, PassportImageCropRepository, _export_zone_names, _export_people_snapshot,
    )


@router.get(
    "/groups/{group_id}/export-images",
    status_code=status.HTTP_200_OK,
    summary="Export a client group's current cropped passport images as ZIP",
response_class=Response, responses=binary_responses("application/zip"))
async def export_passport_images_by_group(
    group_id: uuid.UUID,
    export_mode: PassportExportMode = Query(default="all", alias="mode"),
    baseline_export_id: uuid.UUID | None = Query(default=None),
    request_id: uuid.UUID | None = Query(default=None),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    group = await ClientGroupRepository(session).get_by_id(group_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client group was not found"
        )
    try:
        await AuthorizationPolicy(session).require_export_data(current_user, group)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)

    resolved_request_id = request_id or uuid.uuid4()
    await _require_new_export_request(
        session, group_id=group_id, agency_id=current_user.agency_id,
        export_kind="passport_images", request_id=resolved_request_id,
        created_by_user_id=_owner_scope_for(current_user),
    )
    try:
        prepared = await prepare_image_export(
            session, support=image_export_support(), current_user=current_user,
            agency_id=current_user.agency_id, group=group, export_mode=export_mode,
            baseline_export_id=baseline_export_id,
        )
        spool, image_count, uncompressed_bytes = await prepared.render(
            storage=MinioStorageRepository(), exporter=PassportImageZipExporter(),
        )
    except ImagePreparationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except MissingPassportImagesError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except PassportImageExportLimitError as exc:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc))
    except StorageError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="One or more current images could not be read from secure storage.",
        )

    spool.seek(0, io.SEEK_END)
    archive_size = spool.tell()
    spool.seek(0)
    try:
        async with session.begin_nested():
            history = await PassportExportHistoryRepository(session).record(
                **prepared.history_fields,
                request_id=resolved_request_id,
                artifact_metadata={
                    "image_count": image_count,
                    "uncompressed_bytes": uncompressed_bytes,
                    "archive_bytes": archive_size,
                },
            )
    except IntegrityError as exc:
        spool.close()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This download request was already prepared by another "
                "request. Open download history or start a new download."
            ),
        ) from exc
    try:
        await session.commit()
    except Exception:
        spool.close()
        raise

    filename = safe_download_filename(group.name)
    return StreamingResponse(
        _stream_binary_file(spool),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(archive_size),
            "X-Passport-Export-History-ID": str(history.id),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/groups/{group_id}/export-images/selected",
    status_code=status.HTTP_200_OK,
    summary="Export selected current passport images from a client group as ZIP",
response_class=Response, responses=binary_responses("application/zip"))
async def export_selected_passport_images_by_group(
    group_id: uuid.UUID,
    body: ExportSelectedPassportImagesRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    group = await ClientGroupRepository(session).get_by_id(group_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client group was not found",
        )
    try:
        await AuthorizationPolicy(session).require_export_data(current_user, group)
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        )

    try:
        prepared = await prepare_image_export(
            session, support=image_export_support(), current_user=current_user,
            agency_id=current_user.agency_id, group=group,
            selected_submission_ids=body.submission_ids,
            selected_maximum_bytes=SELECTED_PASSPORT_IMAGE_EXPORT_MAX_BYTES,
        )
        spool, image_count, uncompressed_bytes = await prepared.render(
            storage=MinioStorageRepository(), exporter=PassportImageZipExporter(),
        )
    except ImagePreparationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except MissingPassportImagesError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except PassportImageExportLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="One or more selected images could not be read from secure storage.",
        ) from exc

    spool.seek(0, io.SEEK_END)
    archive_size = spool.tell()
    spool.seek(0)
    logger.info(
        "passport_selected_images_export_prepared",
        group_id=str(group_id),
        agency_id=str(current_user.agency_id),
        actor_user_id=str(current_user.id),
        submission_count=len(prepared.submissions),
        image_count=image_count,
        uncompressed_bytes=uncompressed_bytes,
        archive_bytes=archive_size,
    )
    return StreamingResponse(
        _stream_binary_file(spool),
        media_type="application/zip",
        headers={
            "Content-Disposition": (f'attachment; filename="{safe_download_filename(group.name)}"'),
            "Content-Length": str(archive_size),
            "X-Content-Type-Options": "nosniff",
        },
    )
