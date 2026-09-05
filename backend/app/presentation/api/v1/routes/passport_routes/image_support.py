"""Passport image support: focused workflow boundary."""

from __future__ import annotations

import asyncio
import mimetypes
import uuid
from functools import lru_cache
from typing import Literal, cast

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.domain.entities.entities import PassportSubmission, User
from app.domain.exceptions.exceptions import AuthorizationError, StorageError
from app.domain.value_objects.passport_image_crop import (
    PassportImageCrop,
    PassportImageType,
    passport_image_storage_key,
)
from app.infrastructure.imaging.passport_image_cropper import (
    PassportImageCropError,
    render_saved_passport_image_crop,
)
from app.infrastructure.imaging.passport_thumbnail_cache import PassportThumbnailCache
from app.infrastructure.repositories.passport_image_library_repository import (
    PassportImageLibraryRepository,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportImageCropCoordinates,
    PassportImageCropResponse,
)

from .response_support import (
    _effective_crop,
    _passport_image_api_url,
    _passport_image_edit_source_api_url,
)

logger = get_logger(__name__)


async def _authorized_staff_passport_image(
    *,
    submission_id: uuid.UUID,
    image_type: PassportImageType,
    current_user: User,
    session: AsyncSession,
    require_editor: bool,
) -> tuple[PassportSubmission, str]:
    submission = await PassportSubmissionRepository(session).get_by_id(submission_id)
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Passport submission was not found"
        )
    try:
        policy = AuthorizationPolicy(session)
        if require_editor:
            await policy.require_confirm_passport(current_user, submission)
        else:
            await policy.require_view_passport(current_user, submission)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message) from exc
    storage_key = passport_image_storage_key(submission, image_type)
    if not storage_key or (
        image_type is PassportImageType.PASSPORT_FRONT and storage_key.startswith("excel-imports/")
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="The requested image was not uploaded."
        )
    return submission, storage_key


def _crop_response(
    *,
    submission_id: uuid.UUID,
    image_type: PassportImageType,
    crop_row: PassportImageCrop | None,
    source_storage_key: str,
    source_width: int | None = None,
    source_height: int | None = None,
) -> PassportImageCropResponse:
    effective = _effective_crop(crop_row, source_storage_key=source_storage_key)
    revision = crop_row.revision if crop_row else 0
    coordinates = None
    if effective:
        coordinates = PassportImageCropCoordinates(
            x=effective.x,
            y=effective.y,
            width=effective.width,
            height=effective.height,
            rotation_degrees=effective.rotation_degrees,
            sharpness=effective.sharpness,
        )
        source_width = effective.source_width
        source_height = effective.source_height
    sharpness_algorithm_version = effective.sharpness_algorithm_version if effective else 1
    if sharpness_algorithm_version not in {1, 2}:
        raise RuntimeError("Unsupported passport crop sharpness algorithm version.")
    return PassportImageCropResponse(
        image_type=image_type.value,
        original_url=_passport_image_api_url(submission_id, image_type, original=True),
        editable_source_url=_passport_image_edit_source_api_url(
            submission_id,
            image_type,
            revision=revision,
        ),
        cropped_url=_passport_image_api_url(submission_id, image_type, revision=revision),
        crop=coordinates,
        source_width=source_width,
        source_height=source_height,
        sharpness=effective.sharpness if effective else 1.0,
        sharpness_algorithm_version=cast(Literal[1, 2], sharpness_algorithm_version),
        ai_edited=bool(effective and effective.edit_source_storage_key),
        revision=revision,
    )


async def _delete_crop_derivative_best_effort(
    storage: MinioStorageRepository,
    key: str | None,
    *,
    submission_id: uuid.UUID,
) -> None:
    if not key:
        return
    try:
        await storage.delete_files([key])
    except StorageError as exc:
        logger.warning(
            "passport_crop_derivative_cleanup_deferred",
            submission_id=str(submission_id),
            error_type=type(exc).__name__,
        )


async def _delete_ephemeral_edit_source_best_effort(
    *,
    session: AsyncSession,
    storage: MinioStorageRepository,
    key: str | None,
    submission_id: uuid.UUID,
) -> None:
    if not key:
        return
    if await PassportImageLibraryRepository(session).contains_storage_key(key):
        return
    await _delete_crop_derivative_best_effort(
        storage,
        key,
        submission_id=submission_id,
    )


async def _delete_unreferenced_passport_image_keys_best_effort(
    *,
    session: AsyncSession,
    storage: MinioStorageRepository,
    keys: list[str],
    group_id: uuid.UUID,
) -> None:
    unique_keys = list(dict.fromkeys(key for key in keys if key))
    if not unique_keys:
        return
    try:
        referenced_keys = await PassportImageLibraryRepository(session).referenced_storage_keys(
            unique_keys
        )
        deletable_keys = [key for key in unique_keys if key not in referenced_keys]
        if deletable_keys:
            await storage.delete_files(deletable_keys)
    except Exception as exc:
        logger.warning(
            "passport_import_replaced_object_cleanup_deferred",
            group_id=str(group_id),
            object_count=len(unique_keys),
            error_type=type(exc).__name__,
        )


@lru_cache(maxsize=1)
def _dashboard_thumbnail_cache() -> PassportThumbnailCache:
    return PassportThumbnailCache(
        max_bytes=get_settings().dashboard_thumbnail_cache_max_bytes,
    )


async def _load_effective_passport_image(
    *,
    storage: MinioStorageRepository,
    source_key: str,
    effective_crop: PassportImageCrop | None,
) -> tuple[bytes, str, str]:
    content_type = mimetypes.guess_type(source_key)[0] or "image/jpeg"
    extension = mimetypes.guess_extension(content_type) or ".jpg"
    if effective_crop and effective_crop.derived_storage_key:
        try:
            content = await storage.get_file(effective_crop.derived_storage_key)
            return content, "image/jpeg", ".jpg"
        except StorageError:
            try:
                edit_source_key = effective_crop.edit_source_storage_key or source_key
                original = await storage.get_file(edit_source_key)
                rendered = await asyncio.to_thread(
                    render_saved_passport_image_crop,
                    original,
                    effective_crop,
                )
            except StorageError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=exc.message,
                ) from exc
            except PassportImageCropError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=str(exc),
                ) from exc
            return rendered.content, rendered.content_type, rendered.extension
    try:
        content = await storage.get_file(source_key)
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        ) from exc
    return content, content_type, extension


def _visa_ai_input_storage_key(
    *,
    source_key: str,
    effective_crop: PassportImageCrop | None,
) -> str:
    """Use the exact effective image staff currently see as the Visa AI input."""

    if effective_crop and effective_crop.derived_storage_key:
        return effective_crop.derived_storage_key
    return source_key
