"""Passport response support: focused workflow boundary."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.application.dtos.passport_dtos import PassportSubmissionOutputDTO
from app.application.security.authorization_policy import AuthorizationPolicy
from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.domain.entities.entities import (
    OFFICE_VISIBLE_PASSPORT_STATUS_VALUES,
    PassportSubmission,
    User,
    UserRole,
)
from app.domain.exceptions.exceptions import StorageError
from app.domain.value_objects.passport_image_crop import (
    PassportImageCrop,
    PassportImageType,
    passport_image_storage_key,
)
from app.infrastructure.database.models import PassengerQRTokenModel, PassportSubmissionModel
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository
from app.infrastructure.qr.approved_passenger_qr_issuer import ensure_approved_passenger_qr
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.schemas.passport_schemas import PassportSubmissionResponse

logger = get_logger(__name__)


def _passport_image_api_url(
    submission_id: uuid.UUID,
    image_type: PassportImageType,
    *,
    original: bool = False,
    revision: int | None = None,
) -> str:
    suffix = "/original" if original else ""
    url = (
        f"{get_settings().api_v1_prefix}/passports/{submission_id}/images/"
        f"{image_type.value}{suffix}"
    )
    if not original and revision is not None:
        url = f"{url}?crop_revision={revision}"
    return url


def _passport_image_edit_source_api_url(
    submission_id: uuid.UUID,
    image_type: PassportImageType,
    *,
    revision: int,
) -> str:
    return (
        f"{get_settings().api_v1_prefix}/passports/{submission_id}/images/"
        f"{image_type.value}/edit-source?crop_revision={revision}"
    )


def _passport_visa_ai_library_image_api_url(
    submission_id: uuid.UUID,
    generation_id: uuid.UUID,
) -> str:
    return (
        f"{get_settings().api_v1_prefix}/passports/{submission_id}/images/"
        f"visa_photo/ai-library/{generation_id}/image"
    )


def _effective_crop(
    crop: PassportImageCrop | None,
    *,
    source_storage_key: str | None,
) -> PassportImageCrop | None:
    if (
        crop is None
        or not crop.active
        or not crop.derived_storage_key
        or crop.source_storage_key != source_storage_key
    ):
        return None
    return crop


def _staff_image_urls(
    submission: object,
    crops: dict[PassportImageType, PassportImageCrop] | None = None,
) -> dict[str, str | None]:
    crops = crops or {}
    result: dict[str, str | None] = {}
    response_fields = {
        PassportImageType.PASSPORT_FRONT: "image_url",
        PassportImageType.VISA_PHOTO: "passport_photo_url",
        PassportImageType.PASSPORT_BACK: "passport_back_url",
    }
    for image_type, response_field in response_fields.items():
        source_key = passport_image_storage_key(submission, image_type)
        if not source_key or (
            image_type is PassportImageType.PASSPORT_FRONT
            and source_key.startswith("excel-imports/")
        ):
            result[response_field] = None
            continue
        crop = crops.get(image_type)
        result[response_field] = _passport_image_api_url(
            getattr(submission, "id"),
            image_type,
            revision=crop.revision if crop else 0,
        )
    result.update(_staff_cover_urls(submission))
    return result


def _staff_cover_urls(submission: object) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for kind in ("cover", "back_cover"):
        key = getattr(submission, f"passport_{kind}_s3_key", None)
        result[f"passport_{kind}_url"] = (
            f"{get_settings().api_v1_prefix}/passports/{getattr(submission, 'id')}/covers/{kind}"
            if key else None
        )
    return result


def _owner_scope_for(user: User) -> uuid.UUID | None:
    return user.id if user.role == UserRole.AGENCY_STAFF else None


def _stream_binary_file(file_object, *, chunk_size: int = 1024 * 1024):  # type: ignore[no-untyped-def]
    try:
        while chunk := file_object.read(chunk_size):
            yield chunk
    finally:
        file_object.close()


def _submitted_statuses() -> tuple[str, ...]:
    return OFFICE_VISIBLE_PASSPORT_STATUS_VALUES


async def _safe_presigned_url(
    storage: MinioStorageRepository,
    key: str | None,
) -> str | None:
    if not key:
        return None
    try:
        return await storage.get_presigned_url(key)
    except StorageError as exc:
        logger.warning(
            "passport_presigned_url_unavailable",
            error_type=type(exc).__name__,
        )
        return None


def _apply_manager_visibility(
    stmt: Select[tuple[PassportSubmissionModel]],
    current_user: User,
) -> Select[tuple[PassportSubmissionModel]]:
    return cast(
        Select[tuple[PassportSubmissionModel]],
        AuthorizationPolicy.apply_passport_visibility_scope(stmt, current_user),
    )


async def _response_from_dto(
    result: PassportSubmissionOutputDTO,
    *,
    session: AsyncSession,
    include_document_urls: bool = True,
    use_staff_image_routes: bool = True,
) -> PassportSubmissionResponse:
    storage = MinioStorageRepository()
    document_urls: dict[str, str | None]
    if not include_document_urls:
        document_urls = {"image_url": None, "passport_photo_url": None, "passport_back_url": None}
    elif use_staff_image_routes:
        crop_rows = await PassportImageCropRepository(session).list_for_submissions([result.id])
        document_urls = _staff_image_urls(result, crop_rows.get(result.id))
    else:
        document_urls = {
            "image_url": await _safe_presigned_url(storage, result.image_s3_key),
            "passport_photo_url": await _safe_presigned_url(storage, result.passport_photo_s3_key),
            "passport_back_url": await _safe_presigned_url(storage, result.passport_back_s3_key),
            "passport_cover_url": await _safe_presigned_url(storage, result.passport_cover_s3_key),
            "passport_back_cover_url": await _safe_presigned_url(storage, result.passport_back_cover_s3_key),
        }
    payload = {
        **result.__dict__,
        **document_urls,
        "qr_status": await _passport_qr_status(session, result.id),
    }
    if not payload.get("processing_job_id"):
        job = await PassportProcessingJobRepository(session).latest_for_submission(result.id)
        if job:
            payload.update(
                {
                    "processing_job_id": job.id,
                    "processing_job_status": job.status.value,
                    "processing_progress": job.progress,
                    "processing_stage": job.current_stage,
                }
            )
    return PassportSubmissionResponse.model_validate(payload)


async def _response_from_submission(
    submission: PassportSubmission,
    *,
    session: AsyncSession,
) -> PassportSubmissionResponse:
    crop_rows = await PassportImageCropRepository(session).list_for_submissions([submission.id])
    payload = {
        **submission.__dict__,
        "status": submission.status.value,
        **_staff_image_urls(submission, crop_rows.get(submission.id)),
        "qr_status": await _passport_qr_status(session, submission.id),
    }
    job = await PassportProcessingJobRepository(session).latest_for_submission(submission.id)
    if job:
        payload.update(
            {
                "processing_job_id": job.id,
                "processing_job_status": job.status.value,
                "processing_progress": job.progress,
                "processing_stage": job.current_stage,
            }
        )
    return PassportSubmissionResponse.model_validate(payload)


async def _passport_qr_status(
    session: AsyncSession, passenger_id: uuid.UUID
) -> dict[str, object | None]:
    result = await session.execute(
        select(PassengerQRTokenModel)
        .where(PassengerQRTokenModel.passenger_id == passenger_id)
        .order_by(
            PassengerQRTokenModel.token_version.desc(), PassengerQRTokenModel.created_at.desc()
        )
        .limit(1)
    )
    token = result.scalar_one_or_none()
    if token is None:
        return {"status": "not_generated"}
    now = datetime.now(tz=UTC)
    if token.revoked_at is not None:
        token_status = "revoked"
    elif token.expires_at <= now:
        token_status = "expired"
    else:
        token_status = "active" if token.is_active else "inactive"
    return {
        "status": token_status,
        "token_version": token.token_version,
        "created_at": token.created_at,
        "expires_at": token.expires_at,
        "revoked_at": token.revoked_at,
    }


async def _ensure_submission_qr(
    session: AsyncSession,
    submission_id: uuid.UUID,
    created_by_user_id: uuid.UUID | None = None,
) -> None:
    await ensure_approved_passenger_qr(
        session,
        submission_id,
        created_by_user_id=created_by_user_id,
    )
