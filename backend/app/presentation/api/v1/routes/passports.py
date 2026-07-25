"""
Passport Routes — /api/v1/passports
===================================
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import mimetypes
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.passport_dtos import (
    PassportSubmissionOutputDTO,
    passport_submission_output_from_entity,
)
from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.passports.client_submit_passport_use_case import (
    ClientSubmitPassportUseCase,
)
from app.application.use_cases.passports.confirm_passport_submission_use_case import (
    ConfirmPassportSubmissionUseCase,
)
from app.application.use_cases.passports.get_passport_submission_use_case import (
    GetPassportSubmissionUseCase,
)
from app.application.use_cases.passports.list_passport_group_summaries_use_case import (
    ListPassportGroupSummariesUseCase,
)
from app.application.use_cases.passports.list_passport_submissions_by_group_use_case import (
    ListPassportSubmissionsByGroupUseCase,
)
from app.application.use_cases.passports.list_passport_submissions_use_case import (
    ListPassportSubmissionsUseCase,
)
from app.application.use_cases.passports.reconcile_passport_upload_use_case import (
    ReconcilePassportUploadUseCase,
)
from app.application.use_cases.passports.reextract_passport_submission_use_case import (
    ReextractPassportSubmissionUseCase,
)
from app.application.use_cases.passports.retry_post_submission_verification_use_case import (
    RetryPostSubmissionVerificationUseCase,
)
from app.application.use_cases.passports.retry_public_passport_extraction_use_case import (
    RetryPublicPassportExtractionUseCase,
)
from app.application.use_cases.passports.staff_approve_passport_use_case import (
    StaffApprovalResult,
    StaffApprovePassportUseCase,
)
from app.application.use_cases.passports.submission_view import (
    build_submission_view,
)
from app.application.use_cases.passports.submit_passport_use_case import SubmitPassportUseCase
from app.application.use_cases.whatsapp.group_submission_matching import (
    RecipientForComparison,
    SubmissionForComparison,
    SubmissionMatchRow,
    compare_group_submissions,
)
from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.core.security.passport_ai_edit_token import (
    PassportAiEditTokenError,
    issue_passport_ai_edit_token,
    verify_passport_ai_edit_token,
)
from app.core.security.upload_session import upload_session_matches_identifier
from app.domain.entities.entities import (
    OFFICE_VISIBLE_PASSPORT_STATUS_VALUES,
    ClientGroup,
    PassportSubmission,
    StaffApprovalOutcome,
    User,
    UserRole,
)
from app.domain.exceptions.exceptions import (
    AuthorizationError,
    EntityNotFoundError,
    PassDetectionError,
    StaffApprovalStaleError,
    StaffApprovalUnavailableError,
    StorageError,
)
from app.domain.value_objects.passport_image_crop import (
    PassportImageCrop,
    PassportImageType,
    passport_image_storage_key,
)
from app.domain.value_objects.passport_visa_ai_image import PassportVisaAiImage
from app.domain.value_objects.passport_visa_ai_image_job import (
    PassportVisaAiImageJob,
)
from app.infrastructure.ai.gemini_visa_image_edit_service import (
    GeminiVisaImageEditError,
    GeminiVisaImageEditNotConfigured,
    GeminiVisaImageEditProviderRejected,
    GeminiVisaImageEditProviderUnavailable,
    GeminiVisaImageEditRejected,
    GeminiVisaImageEditService,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    NotificationModel,
    PassengerQRTokenModel,
    PassportExportHistoryModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.export.passport_excel_exporter import (
    PassportExcelExporter,
    passport_age_group,
)
from app.infrastructure.export.passport_image_zip_exporter import (
    MissingPassportImagesError,
    PassportImageExportLimitError,
    PassportImageZipExporter,
    safe_download_filename,
)
from app.infrastructure.imaging.passport_image_cropper import (
    PassportImageCropError,
    render_passport_image_crop,
    render_passport_image_thumbnail,
    render_saved_passport_image_crop,
)
from app.infrastructure.imaging.passport_thumbnail_cache import PassportThumbnailCache
from app.infrastructure.imports.passport_document_importer import (
    PassportDocumentFile,
    PassportDocumentImporter,
    RejectedPassportDocument,
)
from app.infrastructure.imports.passport_excel_importer import PassportExcelImporter
from app.infrastructure.observability.operational_events import (
    OperationalEvent,
    record_operational_event,
)
from app.infrastructure.processing.dispatcher import (
    PassportProcessingDispatcher,
    queued_job_needs_redelivery,
)
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository
from app.infrastructure.qr.approved_passenger_qr_issuer import (
    ensure_approved_passenger_qr,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.notification_repository import NotificationRepository
from app.infrastructure.repositories.passport_export_history_repository import (
    PassportExportHistoryRepository,
    PassportExportKind,
    PassportExportMode,
    PassportExportPersonSnapshot,
    validated_export_people_snapshot,
)
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository,
    PassportImageCropRevisionConflict,
)
from app.infrastructure.repositories.passport_image_library_repository import (
    PassportImageLibraryRepository,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.repositories.passport_visa_ai_image_job_repository import (
    PassportVisaAiImageJobRepository,
)
from app.infrastructure.repositories.passport_visa_ai_image_repository import (
    PassportVisaAiImageRepository,
)
from app.infrastructure.repositories.qualifier_selection_repository import (
    QualifierSelectionRepository,
)
from app.infrastructure.security.upload_validator import UploadValidator
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.infrastructure.storage.passport_object_keys import passport_storage_keys
from app.infrastructure.verification.dispatcher import (
    PostSubmissionVerificationDispatcher,
)
from app.infrastructure.verification.job_repository import (
    PostSubmissionVerificationJobRepository,
)
from app.infrastructure.visa_ai_image_jobs.dispatcher import (
    dispatch_visa_ai_image_job,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    BulkDeletePassportSubmissionsRequest,
    BulkDeletePassportSubmissionsResponse,
    ClientSubmitPassportRequest,
    ConfirmPassportSubmissionRequest,
    ExportSelectedGroupsRequest,
    ExportSelectedPassportsRequest,
    ImportPassportGroupResponse,
    PassportDocumentImportItem,
    PassportDocumentImportPreviewResponse,
    PassportDocumentImportSaveResponse,
    PassportExpiryAlertResponse,
    PassportExportFieldOptionResponse,
    PassportExportFieldOptionsResponse,
    PassportExportGroupingOptionResponse,
    PassportExportHistoryCompletionResponse,
    PassportExportHistoryDetailResponse,
    PassportExportHistoryItemResponse,
    PassportExportHistoryListResponse,
    PassportExportHistorySubmissionResponse,
    PassportGroupSummaryResponse,
    PassportImageCropCoordinates,
    PassportImageCropResetRequest,
    PassportImageCropResponse,
    PassportImageCropUpdateRequest,
    PassportSubmissionResponse,
    PassportSubmissionsViewResponse,
    PassportSubmissionViewItemResponse,
    PassportVisaAiImageJobResponse,
    PassportVisaAiImageListResponse,
    PassportVisaAiImageResponse,
    PassportVisaAiImageUseRequest,
    PassportVisaAiPreviewRequest,
    ReconcilePassportUploadRequest,
    ReconcilePassportUploadResponse,
    StaffApprovePassportRequest,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()
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
    return result


def _owner_scope_for(user: User) -> uuid.UUID | None:
    return user.id if user.role == UserRole.AGENCY_STAFF else None


def _stream_binary_file(file_object, *, chunk_size: int = 1024 * 1024):  # type: ignore[no-untyped-def]
    try:
        while chunk := file_object.read(chunk_size):
            yield chunk
    finally:
        file_object.close()


def _validated_export_history_ids(
    history: PassportExportHistoryModel,
    *,
    field_name: Literal[
        "snapshot_submission_ids",
        "exported_submission_ids",
    ],
) -> set[uuid.UUID]:
    raw_ids = list(getattr(history, field_name) or [])
    parsed_ids: list[uuid.UUID] = []
    for value in raw_ids:
        try:
            parsed_ids.append(uuid.UUID(str(value)))
        except (TypeError, ValueError, AttributeError):
            logger.warning(
                "passport_export_history_invalid_submission_id",
                history_id=str(history.id),
                field_name=field_name,
                value=str(value),
            )
            raise ValueError("The export history entry contains an invalid ID.")
    expected_count = (
        history.total_available_count
        if field_name == "snapshot_submission_ids"
        else history.exported_count
    )
    if len(parsed_ids) != expected_count or len(set(parsed_ids)) != expected_count:
        raise ValueError("The export history entry failed its integrity check.")
    return set(parsed_ids)


def _export_people_snapshot(
    submissions: list[PassportSubmission],
) -> list[PassportExportPersonSnapshot]:
    people: list[PassportExportPersonSnapshot] = []
    for submission in submissions:
        fields = submission.confirmed_fields or submission.extracted_fields or {}
        passport_number = fields.get("passport_number")
        people.append(
            {
                "submission_id": str(submission.id),
                "client_name": submission.client_name,
                "client_phone": submission.client_phone,
                "client_email": submission.client_email,
                "passport_number": (
                    str(passport_number).strip() if passport_number else None
                ),
            }
        )
    return people


def _validated_export_history_people(
    history: PassportExportHistoryModel,
) -> list[PassportExportPersonSnapshot]:
    _validated_export_history_ids(
        history,
        field_name="exported_submission_ids",
    )
    ordered_ids = [
        uuid.UUID(str(value))
        for value in (history.exported_submission_ids or [])
    ]
    return validated_export_people_snapshot(
        history.exported_people_snapshot,
        exported_submission_ids=ordered_ids,
    )


async def _active_roster_resolution_references(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
) -> set[uuid.UUID]:
    """Return submissions whose deletion would corrupt an active roster decision."""

    result = await session.execute(
        select(PassportRosterResolutionModel).where(
            PassportRosterResolutionModel.client_group_id == group_id,
            PassportRosterResolutionModel.agency_id == agency_id,
            PassportRosterResolutionModel.status == "active",
        )
    )
    referenced_ids: set[uuid.UUID] = set()
    for resolution in result.scalars().all():
        referenced_ids.add(resolution.submission_id)
        for value in resolution.excluded_submission_ids or []:
            try:
                referenced_ids.add(uuid.UUID(str(value)))
            except (TypeError, ValueError, AttributeError):
                logger.warning(
                    "passport_roster_resolution_invalid_excluded_submission",
                    resolution_id=str(resolution.id),
                    value=str(value),
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "An active replacement record failed its integrity "
                        "check. Restore it before deleting passport uploads."
                    ),
                )
    return referenced_ids


async def _without_rejected_roster_submissions(
    session: AsyncSession,
    submissions: list[PassportSubmission],
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
) -> list[PassportSubmission]:
    if not submissions:
        return []
    result = await session.execute(
        select(PassportRosterResolutionModel).where(
            PassportRosterResolutionModel.client_group_id == group_id,
            PassportRosterResolutionModel.agency_id == agency_id,
            PassportRosterResolutionModel.status == "active",
        )
    )
    excluded_ids: set[uuid.UUID] = set()
    for resolution in result.scalars().all():
        if resolution.resolution_type == "rejected":
            excluded_ids.add(resolution.submission_id)
            continue
        for value in resolution.excluded_submission_ids or []:
            try:
                excluded_ids.add(uuid.UUID(str(value)))
            except (TypeError, ValueError, AttributeError):
                logger.warning(
                    "passport_roster_resolution_invalid_excluded_submission",
                    resolution_id=str(resolution.id),
                    value=str(value),
                )
    return [submission for submission in submissions if submission.id not in excluded_ids]


async def _current_group_export_submissions(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    current_user: User,
) -> list[PassportSubmission]:
    submissions = await PassportSubmissionRepository(session).list_by_group(
        agency_id,
        group_id,
        limit=PassportImageZipExporter.MAX_SUBMISSIONS + 1,
        exclude_archived_groups=True,
        created_by_user_id=_owner_scope_for(current_user),
        visible_to_user=current_user,
    )
    if len(submissions) > PassportImageZipExporter.MAX_SUBMISSIONS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                "A single export is limited to "
                f"{PassportImageZipExporter.MAX_SUBMISSIONS} passengers."
            ),
        )
    return await _without_rejected_roster_submissions(
        session,
        submissions,
        group_id=group_id,
        agency_id=agency_id,
    )


async def _resolve_group_export_payload(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    export_kind: PassportExportKind,
    export_mode: PassportExportMode,
    baseline_export_id: uuid.UUID | None,
    submissions: list[PassportSubmission],
    created_by_user_id: uuid.UUID | None,
) -> tuple[list[PassportSubmission], PassportExportHistoryModel | None]:
    if export_mode == "all":
        if baseline_export_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A baseline download can only be used for an incremental export.",
            )
        return submissions, None
    if baseline_export_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose a previous download to export uploads added after it.",
        )

    baseline = await PassportExportHistoryRepository(session).get_compatible_baseline(
        history_id=baseline_export_id,
        group_id=group_id,
        agency_id=agency_id,
        export_kind=export_kind,
        created_by_user_id=created_by_user_id,
    )
    if baseline is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The selected download history entry was not found for this group.",
        )

    try:
        baseline_ids = _validated_export_history_ids(
            baseline,
            field_name="snapshot_submission_ids",
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The selected download history entry failed its integrity check "
                "and cannot be used as a baseline."
            ),
        )
    payload = [submission for submission in submissions if submission.id not in baseline_ids]
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="There are no new uploads after the selected download.",
        )
    return payload, baseline


async def _require_new_export_request(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    export_kind: PassportExportKind,
    request_id: uuid.UUID,
    created_by_user_id: uuid.UUID | None,
) -> None:
    existing = await PassportExportHistoryRepository(session).get_by_request(
        group_id=group_id,
        agency_id=agency_id,
        export_kind=export_kind,
        request_id=request_id,
        created_by_user_id=created_by_user_id,
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This download request was already prepared or completed. "
                "Start a new download."
            ),
        )


def _submitted_statuses() -> tuple[str, ...]:
    return OFFICE_VISIBLE_PASSPORT_STATUS_VALUES


def _require_public_upload_credential(
    submission: object,
    upload_session_id: str,
) -> None:
    """Require a per-upload capability that is independent of the public UUID."""

    expected = getattr(submission, "upload_idempotency_key", None)
    if not isinstance(expected, str) or not upload_session_matches_identifier(
        upload_session_id,
        expected,
    ):
        # Use the same response as an unknown submission so this check does
        # not become a capability-validation oracle.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Passport submission was not found",
        )


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


async def _cleanup_uncommitted_promotions(
    result: PassportSubmissionOutputDTO | None,
) -> None:
    if not result or not result.promoted_storage_keys:
        return
    try:
        await MinioStorageRepository().delete_files(list(result.promoted_storage_keys))
    except StorageError as exc:
        logger.warning(
            "passport_promotion_rollback_cleanup_failed",
            submission_id=str(result.id),
            object_count=len(result.promoted_storage_keys),
            error_type=type(exc).__name__,
        )


def _apply_manager_visibility(stmt, current_user: User):  # type: ignore[no-untyped-def]
    return AuthorizationPolicy.apply_passport_visibility_scope(stmt, current_user)


async def _response_from_dto(
    result: PassportSubmissionOutputDTO,
    *,
    session: AsyncSession,
    include_document_urls: bool = True,
    use_staff_image_routes: bool = True,
) -> PassportSubmissionResponse:
    storage = MinioStorageRepository()
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
    submission,
    *,
    session: AsyncSession,
) -> PassportSubmissionResponse:  # type: ignore[no-untyped-def]
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


def _international_airport_is_enabled(
    group: ClientGroup | ClientGroupModel,
) -> bool:
    """Honor the current option and legacy groups that already stored choices."""

    return group.nearest_international_airport_enabled or bool(
        group.departure_cities
    )


def _group_export_details(
    group: ClientGroup | ClientGroupModel,
) -> dict[str, Any]:
    return {
        "name": group.name,
        "destination": group.destination,
        "travel_date": group.travel_date.isoformat() if group.travel_date else None,
        "return_date": group.return_date.isoformat() if group.return_date else None,
        "package_name": group.package_name,
        "nearest_international_airport_enabled": (
            _international_airport_is_enabled(group)
        ),
        "ask_nearest_domestic_airport": group.ask_nearest_domestic_airport,
        "base_city_enabled": group.base_city_enabled,
        "staff_code_enabled": group.staff_code_enabled,
        "agent_employee_code_enabled": group.agent_employee_code_enabled,
        "meal_preference_enabled": group.meal_preference_enabled,
        "relation_with_qualifier_enabled": (group.relation_with_qualifier_enabled),
        "designation_enabled": group.designation_enabled,
        "agency_dealership_name_enabled": (
            group.agency_dealership_name_enabled
        ),
        "custom_questions": list(group.custom_questions or []),
        "custom_details": list(group.custom_details or []),
    }


async def _export_group_details(
    session: AsyncSession,
    group_ids: list[uuid.UUID],
) -> dict[uuid.UUID, dict[str, Any]]:
    if not group_ids:
        return {}
    result = await session.execute(
        select(ClientGroupModel).where(ClientGroupModel.id.in_(set(group_ids)))
    )
    return {group.id: _group_export_details(group) for group in result.scalars().all()}


def _normalized_imported_field_key(value: str) -> str:
    return "_".join(
        part
        for part in "".join(
            character.casefold() if character.isalnum() else " " for character in value
        ).split()
        if part
    )


def _imported_zone_name(fields: dict[str, str]) -> str | None:
    for key, value in fields.items():
        if _normalized_imported_field_key(str(key)) not in {
            "zone_name",
            "zonename",
            "zone",
        }:
            continue
        normalized = " ".join(str(value or "").strip().split())
        if normalized and normalized.casefold() not in {"null", "none", "n/a", "na"}:
            return normalized
    return None


async def _export_whatsapp_match_rows(
    session: AsyncSession,
    submissions: list[PassportSubmission],
    *,
    groups: list[ClientGroup] | None = None,
) -> dict[uuid.UUID, list[SubmissionMatchRow]]:
    """Build one production-grade recipient/submission comparison per group."""
    submissions_by_group: dict[uuid.UUID, list[PassportSubmission]] = {
        group.id: [] for group in (groups or [])
    }
    agency_ids: set[uuid.UUID] = set()
    for group in groups or []:
        if group.agency_id:
            agency_ids.add(group.agency_id)
    for submission in submissions:
        submissions_by_group.setdefault(submission.group_id, []).append(submission)
        if submission.agency_id:
            agency_ids.add(submission.agency_id)
    if not submissions_by_group or not agency_ids:
        return {}

    linked_result = await session.execute(
        select(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id,
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
            WhatsAppBroadcastGroupModel.name,
        )
        .join(
            WhatsAppBroadcastGroupModel,
            WhatsAppBroadcastGroupModel.id
            == ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
        )
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id.in_(set(submissions_by_group)),
            ClientGroupWhatsAppBroadcastLinkModel.agency_id.in_(agency_ids),
            WhatsAppBroadcastGroupModel.agency_id.in_(agency_ids),
        )
    )
    linked_by_group: dict[uuid.UUID, dict[uuid.UUID, str]] = {}
    for group_id, broadcast_id, broadcast_name in linked_result.all():
        linked_by_group.setdefault(group_id, {})[broadcast_id] = broadcast_name
    broadcast_ids = {
        broadcast_id for broadcasts in linked_by_group.values() for broadcast_id in broadcasts
    }
    if not broadcast_ids:
        return {}

    recipient_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel).where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(broadcast_ids),
            WhatsAppBroadcastRecipientModel.agency_id.in_(agency_ids),
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        )
    )
    recipients_by_broadcast: dict[
        uuid.UUID,
        list[WhatsAppBroadcastRecipientModel],
    ] = {}
    for recipient in recipient_result.scalars().all():
        recipients_by_broadcast.setdefault(
            recipient.broadcast_group_id,
            [],
        ).append(recipient)

    rows_by_group: dict[uuid.UUID, list[SubmissionMatchRow]] = {}
    for group_id, group_submissions in submissions_by_group.items():
        linked_broadcasts = linked_by_group.get(group_id, {})
        if not linked_broadcasts:
            continue
        comparison_recipients = [
            RecipientForComparison(
                id=recipient.id,
                broadcast_id=broadcast_id,
                broadcast_name=broadcast_name,
                name=recipient.name,
                phone=recipient.normalized_phone_number,
                updated_at=recipient.created_at,
                imported_fields=dict(recipient.imported_fields or {}),
            )
            for broadcast_id, broadcast_name in linked_broadcasts.items()
            for recipient in recipients_by_broadcast.get(broadcast_id, [])
        ]
        comparison_submissions = [
            SubmissionForComparison(
                id=submission.id,
                name=submission.client_name,
                client_phone=submission.client_phone,
                family_head_phone=submission.family_head_phone,
                updated_at=submission.updated_at,
                client_email=submission.client_email,
                family_head_email=submission.family_head_email,
                confirmed_fields=dict(submission.confirmed_fields or {}),
                extracted_fields=dict(submission.extracted_fields or {}),
                staff_metadata=dict(submission.staff_metadata or {}),
            )
            for submission in group_submissions
        ]
        rows, _ = compare_group_submissions(
            comparison_recipients,
            comparison_submissions,
        )
        rows_by_group[group_id] = rows
    return rows_by_group


def _export_zone_names_from_match_rows(
    submissions: list[PassportSubmission],
    rows_by_group: dict[uuid.UUID, list[SubmissionMatchRow]],
) -> dict[uuid.UUID, str]:
    resolved: dict[uuid.UUID, str] = {}
    submissions_by_group: dict[uuid.UUID, list[PassportSubmission]] = {}
    for submission in submissions:
        submissions_by_group.setdefault(submission.group_id, []).append(submission)

    for group_id, group_submissions in submissions_by_group.items():
        rows = rows_by_group.get(group_id, [])
        submissions_by_id = {submission.id: submission for submission in group_submissions}
        for row in rows:
            if row.status not in {"submitted", "multiple_submissions"}:
                continue
            zones_by_key: dict[str, str] = {}
            for field_set in row.recipient_fields:
                zone_name = _imported_zone_name(field_set.fields)
                if zone_name:
                    zones_by_key.setdefault(zone_name.casefold(), zone_name)
            if not zones_by_key:
                continue
            for submission_id in row.submission_ids:
                if len(zones_by_key) == 1:
                    resolved[submission_id] = next(iter(zones_by_key.values()))
                    continue
                submission = submissions_by_id.get(submission_id)
                stored_zone = _imported_zone_name(
                    dict(submission.staff_metadata or {}) if submission else {}
                )
                if stored_zone and stored_zone.casefold() in zones_by_key:
                    resolved[submission_id] = zones_by_key[stored_zone.casefold()]
    return resolved


async def _export_zone_names(
    session: AsyncSession,
    submissions: list[PassportSubmission],
) -> dict[uuid.UUID, str]:
    """Resolve exact imported WhatsApp zones using the production matcher."""

    rows_by_group = await _export_whatsapp_match_rows(session, submissions)
    return _export_zone_names_from_match_rows(submissions, rows_by_group)


def _recipient_export_value(
    row: SubmissionMatchRow,
    *keys: str,
) -> str | None:
    values_by_key: dict[str, str] = {}
    accepted_keys = {_normalized_imported_field_key(key) for key in keys}
    for field_set in sorted(row.recipient_fields, key=lambda item: str(item.recipient_id)):
        for raw_key, raw_value in field_set.fields.items():
            if _normalized_imported_field_key(str(raw_key)) not in accepted_keys:
                continue
            value = " ".join(str(raw_value or "").strip().split())
            if not value or value.casefold() in {"null", "none", "n/a", "na"}:
                continue
            values_by_key.setdefault(value.casefold(), value)
    if len(values_by_key) == 1:
        return next(iter(values_by_key.values()))
    # Conflicting imported identities must not be silently assigned to a
    # random zone/person. Leave the ambiguous field empty for staff review.
    return None


def _pending_recipient_export_rows(
    *,
    group: ClientGroup,
    rows: list[SubmissionMatchRow],
) -> list[dict[str, Any]]:
    details = _group_export_details(group)
    pending_rows: list[dict[str, Any]] = []
    for row in rows:
        if not row.recipient_ids or row.status not in {"not_submitted", "needs_review"}:
            continue
        given_names = _recipient_export_value(
            row,
            "given_names",
            "given_name",
            "first_name",
        )
        surname = _recipient_export_value(
            row,
            "surname",
            "last_name",
            "family_name",
        )
        imported_name = _recipient_export_value(
            row,
            "name",
            "full_name",
            "client_name",
            "passenger_name",
            "recipient_name",
            "staff_name",
            "employee_name",
        )
        recipient_names_by_key = {
            normalized.casefold(): normalized
            for name in row.recipient_names
            if (normalized := " ".join(str(name or "").strip().split()))
        }
        unambiguous_recipient_name = (
            next(iter(recipient_names_by_key.values()))
            if len(recipient_names_by_key) == 1
            else None
        )
        client_name = (
            unambiguous_recipient_name
            or imported_name
            or " ".join(part for part in (given_names, surname) if part)
            or row.normalized_phone
            or "Pending recipient"
        )
        date_of_birth = _recipient_export_value(
            row,
            "date_of_birth",
            "dob",
            "birth_date",
        )
        pending_rows.append(
            {
                "Group": details.get("name") or group.name,
                "Destination": details.get("destination"),
                "Travel/Departure Date": details.get("travel_date"),
                "Return Date": details.get("return_date"),
                "Zone Name": _recipient_export_value(
                    row,
                    "zone_name",
                    "zonename",
                    "zone",
                ),
                "Agency/Dealership Name": _recipient_export_value(
                    row,
                    "agency_dealership_name",
                    "agency_name",
                    "dealership_name",
                ),
                "Designation": _recipient_export_value(row, "designation"),
                "Age Group": passport_age_group(
                    date_of_birth,
                    details.get("travel_date"),
                ),
                "Email ID": _recipient_export_value(
                    row,
                    "email",
                    "email_address",
                    "e_mail",
                    "mail",
                ),
                "Phone Number": (
                    row.normalized_phone
                    or _recipient_export_value(
                        row,
                        "phone_number",
                        "phone",
                        "mobile",
                        "mobile_number",
                        "whatsapp",
                        "whatsapp_number",
                        "contact",
                        "contact_number",
                    )
                ),
                "International Airport": _recipient_export_value(
                    row,
                    "nearest_international_airport",
                    "international_airport",
                    "departure_city",
                ),
                "Domestic Airport": _recipient_export_value(
                    row,
                    "nearest_domestic_airport",
                    "domestic_airport",
                ),
                "Base City": _recipient_export_value(row, "base_city"),
                "Staff Code": _recipient_export_value(
                    row,
                    "staff_code",
                    "staffcode",
                    "employee_code",
                    "staff_id",
                ),
                "Agent/Employee Code": _recipient_export_value(
                    row,
                    "agent_employee_code",
                    "agent_code",
                    "employee_code",
                ),
                "Meal Preference": _recipient_export_value(
                    row,
                    "meal_preference",
                    "meal",
                    "food_preference",
                ),
                "Relation with Qualifier": _recipient_export_value(
                    row,
                    "relation_with_qualifier",
                    "qualifier_relation",
                    "relation",
                ),
                "SURNAME": surname.upper() if surname else None,
                "GIVEN NAME": (
                    given_names.upper()
                    if given_names
                    else client_name.upper()
                ),
                "GENDER": (
                    value.upper()
                    if (value := _recipient_export_value(row, "sex", "gender"))
                    else None
                ),
                "Passport Number": _recipient_export_value(
                    row,
                    "passport_number",
                    "passport_no",
                    "passport",
                ),
                "DOB": date_of_birth,
                "DOI": _recipient_export_value(
                    row,
                    "date_of_issue",
                    "issue_date",
                ),
                "DOE": _recipient_export_value(
                    row,
                    "date_of_expiry",
                    "expiry_date",
                    "expiration_date",
                ),
                "Nationality": _recipient_export_value(row, "nationality"),
            }
        )
    return pending_rows


_FIXED_IMPORTED_EXPORT_KEYS = {
    "name",
    "full_name",
    "client_name",
    "passenger_name",
    "recipient_name",
    "staff_name",
    "employee_name",
    "given_names",
    "given_name",
    "first_name",
    "surname",
    "last_name",
    "family_name",
    "email",
    "email_address",
    "e_mail",
    "mail",
    "phone_number",
    "phone",
    "mobile",
    "mobile_number",
    "whatsapp",
    "whatsapp_number",
    "contact",
    "contact_number",
    "passport_number",
    "passport_no",
    "passport",
    "nationality",
    "place_of_issue",
    "issue_place",
    "date_of_birth",
    "dob",
    "birth_date",
    "date_of_issue",
    "issue_date",
    "date_of_expiry",
    "expiry_date",
    "expiration_date",
    "sex",
    "gender",
    "nearest_international_airport",
    "international_airport",
    "departure_city",
    "nearest_domestic_airport",
    "domestic_airport",
    "base_city",
    "staff_code",
    "staffcode",
    "staff_id",
    "agent_employee_code",
    "agent_code",
    "employee_code",
    "meal_preference",
    "meal",
    "food_preference",
    "relation_with_qualifier",
    "qualifier_relation",
    "relation",
    "designation",
    "agency_dealership_name",
    "agency_name",
    "dealership_name",
    "source_file",
    "source_sheet",
    "sheet_name",
    "row_number",
}
_ZONE_IMPORTED_KEYS = {"zone_name", "zonename", "zone"}


def _export_field_catalog(
    group: ClientGroup,
    rows: list[SubmissionMatchRow],
    submissions: list[PassportSubmission] | None = None,
) -> list[dict[str, str | bool]]:
    """List selectable supplemental columns with stable keys and labels."""

    used_labels = {
        str(header).casefold() for header in PassportExcelExporter.HEADERS
    }

    def unique_label(label: str, source_label: str) -> str:
        candidate = label[:120]
        suffix_index = 1
        while candidate.casefold() in used_labels:
            suffix = (
                f" ({source_label})"
                if suffix_index == 1
                else f" ({source_label} {suffix_index})"
            )
            candidate = f"{label[: max(1, 120 - len(suffix))]}{suffix}"
            suffix_index += 1
        used_labels.add(candidate.casefold())
        return candidate

    imported_labels: dict[str, str] = {}
    for row in rows:
        for field_set in row.recipient_fields:
            for raw_key in field_set.fields:
                normalized = _normalized_imported_field_key(str(raw_key))
                if not normalized or normalized in _FIXED_IMPORTED_EXPORT_KEYS:
                    continue
                if normalized in _ZONE_IMPORTED_KEYS:
                    imported_labels["zone_name"] = "Zone Name"
                    continue
                imported_labels.setdefault(
                    normalized,
                    " ".join(str(raw_key).strip().split())[:120],
                )

    fields: list[dict[str, str | bool]] = []
    for normalized, label in imported_labels.items():
        key = "zone_name" if normalized == "zone_name" else f"whatsapp:{normalized}"
        fields.append(
            {
                "key": key,
                "label": (
                    "Zone Name"
                    if key == "zone_name"
                    else unique_label(label, "WhatsApp")
                ),
                "source": "whatsapp",
                "selected_by_default": key == "zone_name",
            }
        )
    return sorted(
        fields,
        key=lambda field: (
            field["key"] != "zone_name",
            str(field["label"]).casefold(),
            str(field["key"]),
        ),
    )


def _export_additional_values(
    submissions: list[PassportSubmission],
    rows_by_group: dict[uuid.UUID, list[SubmissionMatchRow]],
    selected_fields: list[dict[str, str | bool]],
) -> dict[uuid.UUID, dict[str, str | None]]:
    values: dict[uuid.UUID, dict[str, str | None]] = {
        submission.id: {} for submission in submissions
    }
    selected_whatsapp = [
        field
        for field in selected_fields
        if str(field["key"]).startswith("whatsapp:")
    ]
    for rows in rows_by_group.values():
        for row in rows:
            if row.status not in {"submitted", "multiple_submissions"}:
                continue
            for submission_id in row.submission_ids:
                if submission_id not in values:
                    continue
                for field in selected_whatsapp:
                    normalized = str(field["key"]).removeprefix("whatsapp:")
                    values[submission_id][str(field["key"])] = _recipient_export_value(
                        row,
                        normalized,
                    )

    return values


def _apply_pending_export_fields(
    pending_rows: list[dict[str, Any]],
    match_rows: list[SubmissionMatchRow],
    selected_fields: list[dict[str, str | bool]],
) -> None:
    source_rows = [
        row
        for row in match_rows
        if row.recipient_ids and row.status in {"not_submitted", "needs_review"}
    ]
    for exported_row, source_row in zip(pending_rows, source_rows, strict=True):
        for field in selected_fields:
            key = str(field["key"])
            if key == "zone_name":
                exported_row[str(field["label"])] = _recipient_export_value(
                    source_row,
                    "zone_name",
                    "zonename",
                    "zone",
                )
            elif key.startswith("whatsapp:"):
                exported_row[str(field["label"])] = _recipient_export_value(
                    source_row,
                    key.removeprefix("whatsapp:"),
                )


def _resolve_export_group_by(
    requested_group_by: str | None,
    requested_field_keys: list[str],
) -> str | None:
    """Keep legacy Zone defaults while honoring an explicit no-grouping choice."""

    if requested_group_by is None:
        return "zone_name" if "zone_name" in requested_field_keys else None
    normalized = requested_group_by.strip()
    return None if normalized in {"", "none"} else normalized


async def _dispatch_processing_job(
    result: PassportSubmissionOutputDTO,
    *,
    session: AsyncSession,
    background_tasks: BackgroundTasks,
) -> None:
    if not result.processing_job_id:
        return

    # The worker uses a separate database session, so commit the queued rows
    # before dispatching to avoid a race with the worker reading the job.
    await session.commit()
    try:
        task_id = PassportProcessingDispatcher().dispatch(
            job_id=result.processing_job_id,
            submission_id=result.id,
            background_tasks=background_tasks,
        )
    except Exception as exc:
        # The submission and image keys are durable at this point. Dispatch is
        # best effort and must never turn persistence success into an upload
        # failure (or trigger compensation that deletes committed objects).
        logger.error(
            "passport_processing_dispatch_failed_after_persistence",
            job_id=str(result.processing_job_id),
            error_type=type(exc).__name__,
        )
        return
    try:
        await PassportProcessingJobRepository(session).set_task_id(
            result.processing_job_id,
            task_id or "local-background",
        )
        await session.commit()
    except Exception as exc:
        # The submission and job were already committed before dispatch.
        # Losing optional queue metadata must not turn a successful upload
        # into a reported upload failure.
        await session.rollback()
        logger.warning(
            "passport_processing_task_id_not_recorded",
            job_id=str(result.processing_job_id),
            error_type=type(exc).__name__,
        )


async def _validated_upload_file(file: UploadFile, *, label: str):
    try:
        content = await file.read()
    except Exception:
        record_operational_event(
            OperationalEvent.UPLOAD_RESULT,
            "read_error",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read {label} file content",
        )
    try:
        return await asyncio.to_thread(
            UploadValidator().validate,
            content=content,
            filename=file.filename,
            declared_content_type=file.content_type,
        )
    except PassDetectionError as exc:
        record_operational_event(
            OperationalEvent.UPLOAD_RESULT,
            "validation_failed",
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)


def _get_submit_passport_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> SubmitPassportUseCase:
    return SubmitPassportUseCase(
        client_group_repo=ClientGroupRepository(session),
        passport_repo=PassportSubmissionRepository(session),
        storage_repo=MinioStorageRepository(),
        processing_job_repo=PassportProcessingJobRepository(session),
        qualifier_selection_repo=QualifierSelectionRepository(session),
    )


def _get_reconcile_passport_upload_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ReconcilePassportUploadUseCase:
    return ReconcilePassportUploadUseCase(
        client_group_repo=ClientGroupRepository(session),
        passport_repo=PassportSubmissionRepository(session),
    )


def _get_list_passports_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ListPassportSubmissionsUseCase:
    return ListPassportSubmissionsUseCase(passport_repo=PassportSubmissionRepository(session))


def _get_list_passport_groups_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ListPassportGroupSummariesUseCase:
    return ListPassportGroupSummariesUseCase(passport_repo=PassportSubmissionRepository(session))


def _get_list_passports_by_group_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ListPassportSubmissionsByGroupUseCase:
    return ListPassportSubmissionsByGroupUseCase(
        passport_repo=PassportSubmissionRepository(session)
    )


def _get_get_passport_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> GetPassportSubmissionUseCase:
    return GetPassportSubmissionUseCase(passport_repo=PassportSubmissionRepository(session))


def _get_confirm_passport_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ConfirmPassportSubmissionUseCase:
    return ConfirmPassportSubmissionUseCase(passport_repo=PassportSubmissionRepository(session))


def _get_client_submit_passport_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ClientSubmitPassportUseCase:
    return ClientSubmitPassportUseCase(
        passport_repo=PassportSubmissionRepository(session),
        client_group_repo=ClientGroupRepository(session),
        storage_repo=MinioStorageRepository(),
    )


def _get_reextract_passport_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ReextractPassportSubmissionUseCase:
    return ReextractPassportSubmissionUseCase(
        passport_repo=PassportSubmissionRepository(session),
        processing_job_repo=PassportProcessingJobRepository(session),
    )


def _get_retry_public_extraction_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> RetryPublicPassportExtractionUseCase:
    return RetryPublicPassportExtractionUseCase(
        passport_repo=PassportSubmissionRepository(session),
        client_group_repo=ClientGroupRepository(session),
        processing_job_repo=PassportProcessingJobRepository(session),
    )


@router.post(
    "/upload/{token}",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a passport image using a secure token (Public)",
)
async def upload_passport(
    token: str,
    background_tasks: BackgroundTasks,
    client_name: str = Form(...),
    acquisition_mode: str = Form(..., pattern="^(camera|file)$"),
    upload_idempotency_key: str = Form(..., min_length=32, max_length=128),
    upload_session_id: str = Header(
        ...,
        alias="X-Upload-Session-ID",
        min_length=32,
        max_length=128,
    ),
    qualifier_selection_token: str | None = Form(
        default=None,
        min_length=32,
        max_length=256,
    ),
    file: UploadFile = File(...),
    passport_back_file: UploadFile = File(..., description="Required original passport back image"),
    passport_photo_file: UploadFile | None = File(
        None,
        description="Optional original Visa Photo captured against a verified plain light background",
    ),
    use_case: SubmitPassportUseCase = Depends(_get_submit_passport_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    if not upload_session_matches_identifier(
        upload_session_id,
        upload_idempotency_key,
    ):
        record_operational_event(
            OperationalEvent.UPLOAD_RESULT,
            "domain_rejected",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload session identifier does not match this upload attempt.",
        )

    # 1. Read and validate file content using magic bytes + actual decoder.
    validated = await _validated_upload_file(file, label="passport front")
    validated_photo = (
        await _validated_upload_file(passport_photo_file, label="Visa Photo")
        if passport_photo_file
        else None
    )
    validated_back = await _validated_upload_file(passport_back_file, label="passport back")

    # 2. Execute use case
    failure_metric_recorded = False
    try:
        result = await use_case.execute(
            token=token,
            file_content=validated.content,
            content_type=validated.content_type,
            filename=validated.filename,
            client_name=client_name,
            passport_photo=(
                validated_photo.content,
                validated_photo.content_type,
                validated_photo.filename,
            )
            if validated_photo
            else None,
            passport_back=(
                validated_back.content,
                validated_back.content_type,
                validated_back.filename,
            ),
            acquisition_mode=acquisition_mode,
            upload_idempotency_key=upload_idempotency_key,
            qualifier_selection_token=qualifier_selection_token,
        )
        try:
            await _dispatch_processing_job(
                result,
                session=session,
                background_tasks=background_tasks,
            )
        except Exception as exc:
            await session.rollback()
            # A database commit exception is ambiguous: the server may have
            # committed before the connection failed, and this may also be an
            # idempotent replay of existing objects. Never delete durable image
            # keys here, because that could leave a committed row dangling.
            logger.error(
                "passport_upload_database_commit_failed",
                group_id=str(result.group_id),
                error_type=type(exc).__name__,
            )
            record_operational_event(
                OperationalEvent.UPLOAD_RESULT,
                "database_failed",
            )
            failure_metric_recorded = True
            raise StorageError(
                "Passport images could not be saved. Please try the upload again."
            ) from exc
        record_operational_event(
            OperationalEvent.UPLOAD_RESULT,
            ("idempotent_replay" if result.idempotent_replay else "success"),
        )
        return await _response_from_dto(
            result,
            session=session,
            include_document_urls=False,
        )
    except EntityNotFoundError as e:
        record_operational_event(
            OperationalEvent.UPLOAD_RESULT,
            "domain_rejected",
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except StorageError as e:
        if not failure_metric_recorded:
            record_operational_event(
                OperationalEvent.UPLOAD_RESULT,
                "storage_failed",
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=e.message,
        )
    except PassDetectionError as e:
        record_operational_event(
            OperationalEvent.UPLOAD_RESULT,
            "domain_rejected",
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
    except Exception:
        if not failure_metric_recorded:
            record_operational_event(
                OperationalEvent.UPLOAD_RESULT,
                "unexpected_failure",
            )
        raise


@router.put(
    "/upload/{token}",
    response_model=ReconcilePassportUploadResponse,
    status_code=status.HTTP_200_OK,
    summary="Recover a durable passport upload by its attempt identifier (Public)",
)
async def reconcile_passport_upload(
    token: str,
    body: ReconcilePassportUploadRequest,
    response: Response,
    upload_session_id: str = Header(
        ...,
        alias="X-Upload-Session-ID",
        min_length=32,
        max_length=128,
    ),
    use_case: ReconcilePassportUploadUseCase = Depends(_get_reconcile_passport_upload_use_case),
) -> ReconcilePassportUploadResponse:
    if not upload_session_matches_identifier(
        upload_session_id,
        body.upload_idempotency_key,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload session identifier does not match this upload attempt.",
        )

    submission_id = await use_case.execute(
        token=token,
        upload_idempotency_key=body.upload_idempotency_key,
    )
    record_operational_event(
        OperationalEvent.UPLOAD_RESULT,
        "reconciled" if submission_id is not None else "reconcile_miss",
    )
    # Unknown keys, tokens belonging to another group, and inactive links all
    # deliberately share the same empty response. This prevents the endpoint
    # from becoming an oracle for upload-link or attempt-key enumeration.
    response.headers["Cache-Control"] = "private, no-store"
    return ReconcilePassportUploadResponse(submission_id=submission_id)


@router.get(
    "/upload/{token}/{submission_id}/status",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Poll passport extraction status for a public upload",
)
async def get_upload_passport_status(
    token: str,
    submission_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    upload_session_id: str = Header(
        ...,
        alias="X-Upload-Session-ID",
        min_length=32,
        max_length=128,
    ),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    group = await ClientGroupRepository(session).get_by_token(token)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Upload link was not found"
        )

    submission = await PassportSubmissionRepository(session).get_by_id(submission_id)
    if not submission or submission.group_id != group.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Passport submission was not found"
        )
    _require_public_upload_credential(submission, upload_session_id)

    # The job row is a durable outbox. If the process stopped after committing
    # it but before recording a delivery (or before an in-process background
    # task started), the first poll safely re-delivers the same revision;
    # worker claim semantics prevent duplicate extraction.
    job = await PassportProcessingJobRepository(session).latest_for_submission(submission.id)
    # Snapshot every response field before a possible dispatch commit. SQLAlchemy
    # expires loaded state on commit; reading the submission afterwards from an
    # async route can otherwise trigger an implicit synchronous refresh and
    # raise MissingGreenlet, turning an otherwise healthy status poll into 500.
    response_result = passport_submission_output_from_entity(submission, job=job)
    if job is not None and queued_job_needs_redelivery(job):
        await _dispatch_processing_job(
            response_result,
            session=session,
            background_tasks=background_tasks,
        )

    return await _response_from_dto(
        response_result,
        session=session,
        include_document_urls=False,
    )


@router.post(
    "/upload/{token}/{submission_id}/scan-again",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Rerun fallback MRZ extraction for a public upload",
)
async def scan_again_public_upload(
    token: str,
    submission_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    upload_session_id: str = Header(
        ...,
        alias="X-Upload-Session-ID",
        min_length=32,
        max_length=128,
    ),
    use_case: RetryPublicPassportExtractionUseCase = Depends(_get_retry_public_extraction_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    try:
        group = await ClientGroupRepository(session).get_by_token(token)
        submission = await PassportSubmissionRepository(session).get_by_id(submission_id)
        if not group or not submission or submission.group_id != group.id:
            raise EntityNotFoundError(
                "PassportSubmission",
                submission_id,
            )
        _require_public_upload_credential(submission, upload_session_id)
        result = await use_case.execute(token=token, submission_id=submission_id)
        await _dispatch_processing_job(
            result,
            session=session,
            background_tasks=background_tasks,
        )
        return await _response_from_dto(
            result,
            session=session,
            include_document_urls=False,
        )
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except PassDetectionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


@router.get(
    "/upload/{token}/{submission_id}/image",
    status_code=status.HTTP_200_OK,
    summary="Stream a public upload passport image through the API",
)
async def get_public_upload_passport_image(
    token: str,
    submission_id: uuid.UUID,
    upload_session_id: str = Header(
        ...,
        alias="X-Upload-Session-ID",
        min_length=32,
        max_length=128,
    ),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    group = await ClientGroupRepository(session).get_by_token(token)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Upload link was not found"
        )

    submission = await PassportSubmissionRepository(session).get_by_id(submission_id)
    if not submission or submission.group_id != group.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Passport submission was not found"
        )
    _require_public_upload_credential(submission, upload_session_id)

    try:
        content = await MinioStorageRepository().get_file(submission.image_s3_key)
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        )
    return StreamingResponse(
        io.BytesIO(content),
        media_type=mimetypes.guess_type(submission.image_s3_key)[0] or "image/jpeg",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": 'inline; filename="passport.jpg"',
        },
    )


def _get_staff_approve_passport_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> StaffApprovePassportUseCase:
    return StaffApprovePassportUseCase(passport_repo=PassportSubmissionRepository(session))


def _staff_approval_conflict_response(
    error: StaffApprovalStaleError | StaffApprovalUnavailableError,
) -> JSONResponse:
    details: dict[str, object] = {}
    if isinstance(error, StaffApprovalStaleError):
        details["current_revision"] = error.current_revision
    else:
        details["current_status"] = error.current_status
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "details": details,
            }
        },
        headers={"Cache-Control": "no-store"},
    )


def _get_retry_post_submission_verification_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> RetryPostSubmissionVerificationUseCase:
    return RetryPostSubmissionVerificationUseCase(
        passport_repo=PassportSubmissionRepository(session)
    )


@router.get(
    "/upload/{token}/{submission_id}/image/{document_type}",
    status_code=status.HTTP_200_OK,
    summary="Stream one stored public passport document through the API",
)
async def get_public_upload_passport_document(
    token: str,
    submission_id: uuid.UUID,
    document_type: str,
    upload_session_id: str = Header(
        ...,
        alias="X-Upload-Session-ID",
        min_length=32,
        max_length=128,
    ),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    group = await ClientGroupRepository(session).get_by_token(token)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Upload link was not found"
        )

    submission = await PassportSubmissionRepository(session).get_by_id(submission_id)
    if not submission or submission.group_id != group.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Passport submission was not found",
        )
    _require_public_upload_credential(submission, upload_session_id)

    keys = {
        "front": submission.image_s3_key,
        "back": submission.passport_back_s3_key,
        "photo": submission.passport_photo_s3_key,
    }
    if document_type not in keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose front, back, or photo.",
        )
    key = keys[document_type]
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested passport document was not uploaded.",
        )
    try:
        content = await MinioStorageRepository().get_file(key)
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        )
    return StreamingResponse(
        io.BytesIO(content),
        media_type=mimetypes.guess_type(key)[0] or "image/jpeg",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'inline; filename="passport-{document_type}"',
        },
    )


@router.delete(
    "/upload/{token}/{submission_id}",
    status_code=status.HTTP_200_OK,
    summary="Discard an unsubmitted public passport draft",
)
async def discard_public_upload(
    token: str,
    submission_id: uuid.UUID,
    upload_session_id: str = Header(
        ...,
        alias="X-Upload-Session-ID",
        min_length=32,
        max_length=128,
    ),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, bool]:
    group = await ClientGroupRepository(session).get_by_token(token)
    submission_repo = PassportSubmissionRepository(session)
    submission = await submission_repo.get_by_id_for_update(submission_id)
    if not group or not submission or submission.group_id != group.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Passport draft was not found"
        )
    try:
        _require_public_upload_credential(submission, upload_session_id)
    except HTTPException as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Passport draft was not found",
        ) from exc
    if submission.status.value in OFFICE_VISIBLE_PASSPORT_STATUS_VALUES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Submitted passports cannot be discarded"
        )

    keys = [
        key
        for key in (
            submission.image_s3_key,
            submission.thumbnail_s3_key,
            submission.passport_photo_s3_key,
            submission.passport_back_s3_key,
        )
        if key
    ]
    await submission_repo.delete(submission.id)
    # Remove the live database reference first. A failed commit leaves all
    # stored pages intact; post-commit object cleanup is best effort.
    await session.commit()
    try:
        await MinioStorageRepository().delete_files(keys)
    except StorageError as exc:
        logger.warning(
            "discarded_passport_object_cleanup_deferred",
            submission_id=str(submission.id),
            object_count=len(keys),
            error_type=type(exc).__name__,
        )
    record_operational_event(
        OperationalEvent.PUBLIC_FLOW,
        "upload_abandoned",
    )
    return {"discarded": True}


@router.get(
    "/groups",
    response_model=list[PassportGroupSummaryResponse],
    status_code=status.HTTP_200_OK,
    summary="List client groups that contain passport submissions",
)
async def list_passport_groups(
    current_user: User = Depends(get_current_active_user),
    use_case: ListPassportGroupSummariesUseCase = Depends(_get_list_passport_groups_use_case),
    skip: int = 0,
    limit: int = 50,
) -> list[PassportGroupSummaryResponse]:
    if not current_user.agency_id:
        return []

    result = await use_case.execute(
        agency_id=current_user.agency_id,
        skip=skip,
        limit=limit,
        created_by_user_id=_owner_scope_for(current_user),
        visible_to_user=current_user,
    )
    return [PassportGroupSummaryResponse.model_validate(item) for item in result]


@router.get(
    "/groups/{group_id}",
    response_model=list[PassportSubmissionResponse],
    status_code=status.HTTP_200_OK,
    summary="List passport submissions within a client group",
)
async def list_passports_by_group(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    use_case: ListPassportSubmissionsByGroupUseCase = Depends(
        _get_list_passports_by_group_use_case
    ),
    skip: int = 0,
    limit: int = 100,
    search: str | None = None,
    include_deleted: bool = False,
) -> list[PassportSubmissionResponse]:
    if not current_user.agency_id:
        return []
    if include_deleted and current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only super admins can view old data"
        )

    result = await use_case.execute(
        agency_id=current_user.agency_id,
        group_id=group_id,
        skip=skip,
        limit=limit,
        search=search,
        created_by_user_id=None if include_deleted else _owner_scope_for(current_user),
        include_deleted_group=include_deleted,
        visible_to_user=None if include_deleted else current_user,
    )
    crop_rows = await PassportImageCropRepository(session).list_for_submissions(
        [item.id for item in result]
    )
    return [
        PassportSubmissionResponse.model_validate(
            {**item.__dict__, **_staff_image_urls(item, crop_rows.get(item.id))}
        )
        for item in result
    ]


@router.get(
    "/groups/{group_id}/submissions-view",
    response_model=PassportSubmissionsViewResponse,
    status_code=status.HTTP_200_OK,
    summary="List a full-group filtered and duplicate-aware submission view",
)
async def list_passports_by_group_view(
    group_id: uuid.UUID,
    submission_filter: Literal[
        "all",
        "pending_ai",
        "ai_approved",
        "needs_review",
        "staff_approved",
        "duplicates",
    ] = "all",
    sort_by: Literal["name", "updated_at", "verification_confidence"] = "name",
    sort_order: Literal["asc", "desc"] = "asc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None, max_length=200),
    include_deleted: bool = False,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    use_case: ListPassportSubmissionsByGroupUseCase = Depends(
        _get_list_passports_by_group_use_case
    ),
) -> PassportSubmissionsViewResponse:
    if not current_user.agency_id:
        return PassportSubmissionsViewResponse(
            items=[],
            ordered_submission_ids=[],
            group_total=0,
            total=0,
            page=page,
            page_size=page_size,
            total_pages=0,
            returned_count=0,
            expiry_alerts=[],
        )
    if include_deleted and current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super admins can view old data",
        )

    # Identity clusters, search propagation, and status filtering must operate
    # over the complete authorized group before block-aware pagination.
    all_submissions = await use_case.execute(
        agency_id=current_user.agency_id,
        group_id=group_id,
        skip=0,
        limit=None,
        search=None,
        created_by_user_id=(None if include_deleted else _owner_scope_for(current_user)),
        include_deleted_group=include_deleted,
        visible_to_user=None if include_deleted else current_user,
    )
    travel_date_stmt = select(ClientGroupModel.travel_date).where(ClientGroupModel.id == group_id)
    if not include_deleted:
        travel_date_stmt = travel_date_stmt.where(ClientGroupModel.deleted_at.is_(None))
    travel_date_stmt = AuthorizationPolicy.apply_group_visibility_scope(
        travel_date_stmt,
        current_user,
    )
    travel_date = (await session.execute(travel_date_stmt)).scalar_one_or_none()
    view = build_submission_view(
        all_submissions,
        submission_filter=submission_filter,
        sort_by=sort_by,
        sort_order=sort_order,
        search=search,
        page=page,
        page_size=page_size,
        travel_date=travel_date,
    )
    items: list[PassportSubmissionViewItemResponse] = []
    crop_rows = await PassportImageCropRepository(session).list_for_submissions(
        [entry.submission.id for entry in view.items]
    )
    for entry in view.items:
        base = PassportSubmissionResponse.model_validate(
            {
                **entry.submission.__dict__,
                **_staff_image_urls(entry.submission, crop_rows.get(entry.submission.id)),
            }
        )
        items.append(
            PassportSubmissionViewItemResponse.model_validate(
                {
                    **base.model_dump(),
                    "duplicate_cluster_id": (entry.duplicate_cluster_id),
                    "duplicate_cluster_size": (entry.duplicate_cluster_size),
                    "duplicate_cluster_member_ids": list(entry.duplicate_cluster_member_ids),
                    "verification_confidence": (entry.verification_confidence),
                }
            )
        )
    return PassportSubmissionsViewResponse(
        items=items,
        ordered_submission_ids=list(view.ordered_submission_ids),
        group_total=view.group_total,
        total=view.total,
        page=view.page,
        page_size=view.page_size,
        total_pages=view.total_pages,
        returned_count=view.returned_count,
        cluster_boundaries_preserved=True,
        expiry_alerts=[
            PassportExpiryAlertResponse(
                submission_id=alert.submission_id,
                client_name=alert.client_name,
                client_email=alert.client_email,
                passport_number=alert.passport_number,
                date_of_expiry=alert.date_of_expiry,
                status=alert.status,
            )
            for alert in view.expiry_alerts
        ],
    )


@router.post(
    "/groups/{group_id}/bulk-delete",
    response_model=BulkDeletePassportSubmissionsResponse,
    status_code=status.HTTP_200_OK,
    summary="Permanently delete selected passport submissions from a group",
)
async def bulk_delete_passport_submissions(
    group_id: uuid.UUID,
    body: BulkDeletePassportSubmissionsRequest,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> BulkDeletePassportSubmissionsResponse:
    if current_user.role != UserRole.SUPER_ADMIN and not current_user.agency_id:
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
        await AuthorizationPolicy(session).require_delete_data(
            current_user,
            group,
            permanent=True,
        )
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        ) from exc

    submission_ids = list(dict.fromkeys(body.submission_ids))
    selected_rows = await session.execute(
        select(
            PassportSubmissionModel.id,
            PassportSubmissionModel.image_s3_key,
            PassportSubmissionModel.thumbnail_s3_key,
            PassportSubmissionModel.passport_back_s3_key,
            PassportSubmissionModel.passport_photo_s3_key,
        )
        .where(
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.id.in_(submission_ids),
        )
        .with_for_update()
    )
    submissions = list(selected_rows.all())
    found_ids = {row.id for row in submissions}
    missing_ids = [
        submission_id for submission_id in submission_ids if submission_id not in found_ids
    ]
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "One or more selected passport submissions were not found "
                "in this group. Refresh the page and try again."
            ),
        )

    # Replacement creation locks its submission before recording a roster
    # decision. Taking the same locks first closes the check/delete race: either
    # the decision commits first and is observed below, or it waits and then
    # finds that the submission no longer exists.
    protected_submission_ids = await _active_roster_resolution_references(
        session,
        group_id=group_id,
        agency_id=group.agency_id,
    )
    selected_protected_ids = protected_submission_ids.intersection(submission_ids)
    if selected_protected_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "One or more selected uploads belong to an active "
                "replacement or rejection. Restore that roster decision "
                "before permanently deleting the upload."
            ),
        )

    storage_keys = passport_storage_keys(submissions)
    crop_repository = PassportImageCropRepository(session)
    storage_keys.extend(await crop_repository.derived_storage_keys(submission_ids))
    storage_keys.extend(await crop_repository.edit_storage_keys(submission_ids))
    notification_result = await session.execute(
        delete(NotificationModel).where(
            NotificationModel.agency_id == group.agency_id,
            NotificationModel.entity_type == "passport_submission",
            NotificationModel.entity_id.in_(
                [str(submission_id) for submission_id in submission_ids]
            ),
        )
    )
    deleted_notifications = int(getattr(notification_result, "rowcount", 0) or 0)
    delete_result = await session.execute(
        delete(PassportSubmissionModel).where(
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.id.in_(submission_ids),
        )
    )
    deleted_count = int(getattr(delete_result, "rowcount", 0) or 0)
    if deleted_count != len(submission_ids):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The selected submissions changed while deletion was in "
                "progress. Refresh the page and try again."
            ),
        )

    await AuditLogRepository(session).record(
        action="passport_submissions_bulk_deleted",
        entity_type="client_group",
        entity_id=str(group_id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "deleted_count": deleted_count,
            "deleted_submission_ids": [str(submission_id) for submission_id in submission_ids],
            "storage_objects_scheduled_for_cleanup": len(storage_keys),
            "deleted_notifications": deleted_notifications,
        },
    )
    # Commit the authoritative database deletion before touching object
    # storage. A failed commit therefore leaves every passport file intact.
    await session.commit()

    deleted_storage_objects = 0
    storage_cleanup_deferred = False
    try:
        deleted_storage_objects = await MinioStorageRepository().delete_files(storage_keys)
    except StorageError as exc:
        storage_cleanup_deferred = True
        logger.warning(
            "passport_bulk_delete_storage_cleanup_deferred",
            group_id=str(group_id),
            submission_count=deleted_count,
            object_count=len(storage_keys),
            error_type=type(exc).__name__,
        )

    return BulkDeletePassportSubmissionsResponse(
        deleted_count=deleted_count,
        deleted_submission_ids=submission_ids,
        deleted_storage_objects=deleted_storage_objects,
        deleted_notifications=deleted_notifications,
        storage_cleanup_deferred=storage_cleanup_deferred,
    )


@router.get(
    "",
    response_model=list[PassportSubmissionResponse],
    status_code=status.HTTP_200_OK,
    summary="List passport submissions for the current agency",
)
async def list_passports(
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    use_case: ListPassportSubmissionsUseCase = Depends(_get_list_passports_use_case),
    skip: int = 0,
    limit: int = 100,
    status_filter: str | None = None,
    search: str | None = None,
) -> list[PassportSubmissionResponse]:
    if not current_user.agency_id:
        return []

    result = await use_case.execute(
        agency_id=current_user.agency_id,
        skip=skip,
        limit=limit,
        status_filter=status_filter,
        search=search,
        created_by_user_id=_owner_scope_for(current_user),
        visible_to_user=current_user,
    )
    crop_rows = await PassportImageCropRepository(session).list_for_submissions(
        [item.id for item in result]
    )
    return [
        PassportSubmissionResponse.model_validate(
            {**item.__dict__, **_staff_image_urls(item, crop_rows.get(item.id))}
        )
        for item in result
    ]


@router.get(
    "/groups/{group_id}/export-history",
    response_model=PassportExportHistoryListResponse,
    status_code=status.HTTP_200_OK,
    summary="List successful passport export checkpoints for a client group",
)
async def list_passport_group_export_history(
    group_id: uuid.UUID,
    export_kind: PassportExportKind = Query(..., alias="kind"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportExportHistoryListResponse:
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
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

    submissions = await _current_group_export_submissions(
        session,
        group_id=group_id,
        agency_id=current_user.agency_id,
        current_user=current_user,
    )
    current_ids = {submission.id for submission in submissions}
    history_repository = PassportExportHistoryRepository(session)
    owner_scope = _owner_scope_for(current_user)
    total_count = await history_repository.count_for_group(
        group_id=group_id,
        agency_id=current_user.agency_id,
        export_kind=export_kind,
        created_by_user_id=owner_scope,
    )
    history = await history_repository.list_for_group(
        group_id=group_id,
        agency_id=current_user.agency_id,
        export_kind=export_kind,
        created_by_user_id=owner_scope,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    history_items: list[PassportExportHistoryItemResponse] = []
    for item in history:
        if item.completed_at is None:
            logger.error(
                "passport_export_history_completed_without_timestamp",
                history_id=str(item.id),
            )
            continue
        try:
            snapshot_ids = _validated_export_history_ids(
                item,
                field_name="snapshot_submission_ids",
            )
            compatible = True
            new_submission_count = len(current_ids - snapshot_ids)
        except ValueError:
            compatible = False
            new_submission_count = 0
        history_items.append(
            PassportExportHistoryItemResponse(
                id=item.id,
                export_kind=item.export_kind,
                export_mode=item.export_mode,
                baseline_export_id=item.baseline_export_id,
                total_available_count=item.total_available_count,
                exported_count=item.exported_count,
                pending_recipient_count=item.pending_recipient_count,
                new_submission_count=new_submission_count,
                compatible=compatible,
                actor_email=item.actor_email,
                created_at=item.created_at,
                completed_at=item.completed_at,
            )
        )
    return PassportExportHistoryListResponse(
        group_id=group_id,
        export_kind=export_kind,
        current_submission_count=len(submissions),
        items=history_items,
        page=page,
        page_size=page_size,
        total_count=total_count,
        total_pages=(
            (total_count + page_size - 1) // page_size if total_count else 0
        ),
    )


@router.get(
    "/groups/{group_id}/export-history/{history_id}",
    response_model=PassportExportHistoryDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="List the exact passport submissions included in one export",
)
async def get_passport_group_export_history_detail(
    group_id: uuid.UUID,
    history_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportExportHistoryDetailResponse:
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

    history = await PassportExportHistoryRepository(session).get_for_group(
        history_id=history_id,
        group_id=group_id,
        agency_id=current_user.agency_id,
        created_by_user_id=_owner_scope_for(current_user),
    )
    if history is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download history entry was not found",
        )
    if history.completed_at is None:
        logger.error(
            "passport_export_history_completed_without_timestamp",
            history_id=str(history.id),
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This download history entry failed its integrity check.",
        )
    try:
        people = _validated_export_history_people(history)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This download history entry failed its integrity check.",
        )

    offset = (page - 1) * page_size
    page_people = people[offset : offset + page_size]
    page_ids = [uuid.UUID(str(item["submission_id"])) for item in page_people]
    available_ids: set[uuid.UUID] = set()
    if page_ids:
        result = await session.execute(
            select(PassportSubmissionModel.id).where(
                PassportSubmissionModel.id.in_(page_ids),
                PassportSubmissionModel.group_id == group_id,
                PassportSubmissionModel.agency_id == current_user.agency_id,
            )
        )
        available_ids = set(result.scalars().all())

    items: list[PassportExportHistorySubmissionResponse] = []
    for person in page_people:
        submission_id = uuid.UUID(str(person["submission_id"]))
        items.append(
            PassportExportHistorySubmissionResponse(
                submission_id=submission_id,
                record_available=submission_id in available_ids,
                client_name=person["client_name"],
                client_phone=person["client_phone"],
                client_email=person["client_email"],
                passport_number=person["passport_number"],
            )
        )
    return PassportExportHistoryDetailResponse(
        history_id=history.id,
        group_id=group_id,
        export_kind=history.export_kind,
        created_at=history.created_at,
        completed_at=history.completed_at,
        exported_count=history.exported_count,
        items=items,
        page=page,
        page_size=page_size,
        total_pages=(
            (history.exported_count + page_size - 1) // page_size if history.exported_count else 0
        ),
    )


@router.post(
    "/groups/{group_id}/export-history/{history_id}/complete",
    response_model=PassportExportHistoryCompletionResponse,
    status_code=status.HTTP_200_OK,
    summary="Confirm that a prepared passport export reached the browser",
)
async def complete_passport_group_export_history(
    group_id: uuid.UUID,
    history_id: uuid.UUID,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportExportHistoryCompletionResponse:
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

    history = await PassportExportHistoryRepository(session).get_for_completion(
        history_id=history_id,
        group_id=group_id,
        agency_id=current_user.agency_id,
        created_by_user_id=current_user.id,
    )
    if history is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prepared download was not found",
        )
    if history.status == "completed":
        if history.completed_at is None:
            logger.error(
                "passport_export_history_completed_without_timestamp",
                history_id=str(history.id),
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This prepared download failed its integrity check.",
            )
        return PassportExportHistoryCompletionResponse(
            history_id=history.id,
            group_id=history.group_id,
            export_kind=history.export_kind,
            status="completed",
            completed_at=history.completed_at,
        )
    if history.status != "prepared" or history.completed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This prepared download is in an invalid state.",
        )

    try:
        snapshot_ids = _validated_export_history_ids(
            history,
            field_name="snapshot_submission_ids",
        )
        exported_ids = _validated_export_history_ids(
            history,
            field_name="exported_submission_ids",
        )
        _validated_export_history_people(history)
        if not exported_ids.issubset(snapshot_ids):
            raise ValueError("Export payload is outside its cumulative checkpoint.")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This prepared download failed its integrity check.",
        )

    completed_at = datetime.now(tz=UTC)
    history.status = "completed"
    history.completed_at = completed_at
    artifact_metadata = dict(history.artifact_metadata or {})
    await AuditLogRepository(session).record(
        action=(
            "passport_group_images_exported"
            if history.export_kind == "passport_images"
            else "passport_group_exported"
        ),
        entity_type="client_group",
        entity_id=str(group_id),
        agency_id=current_user.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            **artifact_metadata,
            "export_history_id": str(history.id),
            "export_mode": history.export_mode,
            "baseline_export_id": (
                str(history.baseline_export_id)
                if history.baseline_export_id
                else None
            ),
            "total_available_count": history.total_available_count,
            "submission_count": history.exported_count,
            "pending_recipient_count": history.pending_recipient_count,
        },
    )
    await session.commit()
    return PassportExportHistoryCompletionResponse(
        history_id=history.id,
        group_id=history.group_id,
        export_kind=history.export_kind,
        status="completed",
        completed_at=completed_at,
    )


@router.get(
    "/groups/{group_id}/export-fields",
    response_model=PassportExportFieldOptionsResponse,
    status_code=status.HTTP_200_OK,
    summary="List selectable supplemental columns for a passport Excel export",
)
async def get_passport_group_export_fields(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportExportFieldOptionsResponse:
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

    submissions = await _current_group_export_submissions(
        session,
        group_id=group_id,
        agency_id=current_user.agency_id,
        current_user=current_user,
    )
    rows_by_group = await _export_whatsapp_match_rows(
        session,
        submissions,
        groups=[group],
    )
    catalog = _export_field_catalog(
        group,
        rows_by_group.get(group.id, []),
        submissions,
    )
    default_selected = [
        str(field["key"]) for field in catalog if field["selected_by_default"]
    ]
    return PassportExportFieldOptionsResponse(
        group_id=group.id,
        fields=[
            PassportExportFieldOptionResponse.model_validate(field)
            for field in catalog
        ],
        grouping_fields=[
            *(
                [
                    PassportExportGroupingOptionResponse(
                        key="international_airport",
                        label="International Airport",
                        fixed=True,
                    )
                ]
                if _international_airport_is_enabled(group)
                else []
            ),
            *[
                PassportExportGroupingOptionResponse(
                    key=str(field["key"]),
                    label=str(field["label"]),
                    fixed=False,
                )
                for field in catalog
            ],
        ],
        default_selected_fields=default_selected,
        default_group_by_field=(
            "zone_name" if "zone_name" in default_selected else None
        ),
    )


@router.get(
    "/groups/{group_id}/export.xlsx",
    status_code=status.HTTP_200_OK,
    summary="Export a client group's passport submissions to Excel",
)
async def export_passports_by_group(
    group_id: uuid.UUID,
    export_mode: PassportExportMode = Query(default="all", alias="mode"),
    baseline_export_id: uuid.UUID | None = Query(default=None),
    request_id: uuid.UUID | None = Query(default=None),
    supplemental_fields: str | None = Query(default=None, max_length=20_000),
    group_by_field: str | None = Query(default=None, max_length=180),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    group_repo = ClientGroupRepository(session)
    group = await group_repo.get_by_id(group_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client group was not found"
        )
    try:
        await AuthorizationPolicy(session).require_export_data(current_user, group)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)

    current_submissions = await _current_group_export_submissions(
        session,
        group_id=group_id,
        agency_id=current_user.agency_id,
        current_user=current_user,
    )
    resolved_request_id = request_id or uuid.uuid4()
    await _require_new_export_request(
        session,
        group_id=group_id,
        agency_id=current_user.agency_id,
        export_kind="passport_excel",
        request_id=resolved_request_id,
        created_by_user_id=_owner_scope_for(current_user),
    )
    submissions, baseline = await _resolve_group_export_payload(
        session,
        group_id=group_id,
        agency_id=current_user.agency_id,
        export_kind="passport_excel",
        export_mode=export_mode,
        baseline_export_id=baseline_export_id,
        submissions=current_submissions,
        created_by_user_id=_owner_scope_for(current_user),
    )
    match_rows_by_group = await _export_whatsapp_match_rows(
        session,
        current_submissions,
        groups=[group],
    )
    catalog = _export_field_catalog(
        group,
        match_rows_by_group.get(group.id, []),
        current_submissions,
    )
    catalog_by_key = {str(field["key"]): field for field in catalog}
    requested_field_keys = (
        list(
            dict.fromkeys(
                key.strip()
                for key in supplemental_fields.split(",")
                if key.strip()
            )
        )
        if supplemental_fields is not None
        else [
            str(field["key"])
            for field in catalog
            if field["selected_by_default"]
        ]
    )
    unknown_fields = [
        key for key in requested_field_keys if key not in catalog_by_key
    ]
    if unknown_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more selected Excel fields are unavailable for this group.",
        )
    selected_fields = [catalog_by_key[key] for key in requested_field_keys]
    resolved_group_by = _resolve_export_group_by(
        group_by_field,
        requested_field_keys,
    )
    if (
        resolved_group_by == "international_airport"
        and not _international_airport_is_enabled(group)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "International Airport grouping is available only when the "
                "group asks travellers for that field."
            ),
        )
    if (
        resolved_group_by
        and resolved_group_by != "international_airport"
        and resolved_group_by not in requested_field_keys
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "The grouping field must be International Airport or an "
                "included WhatsApp field."
            ),
        )
    pending_rows = (
        _pending_recipient_export_rows(
            group=group,
            rows=match_rows_by_group.get(group.id, []),
        )
        if export_mode == "all"
        else []
    )
    if pending_rows:
        _apply_pending_export_fields(
            pending_rows,
            match_rows_by_group.get(group.id, []),
            selected_fields,
        )
    additional_values = _export_additional_values(
        submissions,
        match_rows_by_group,
        selected_fields,
    )
    content = PassportExcelExporter().export_group(
        submissions,
        group_name=group.name,
        group_details={group.id: _group_export_details(group)},
        zone_names=_export_zone_names_from_match_rows(
            submissions,
            match_rows_by_group,
        ),
        additional_fields=[
            {"key": str(field["key"]), "label": str(field["label"])}
            for field in selected_fields
        ],
        additional_values=additional_values,
        group_by_field=resolved_group_by,
        pending_rows=pending_rows,
    )
    try:
        async with session.begin_nested():
            history = await PassportExportHistoryRepository(session).record(
                group_id=group_id,
                agency_id=current_user.agency_id,
                export_kind="passport_excel",
                export_mode=export_mode,
                request_id=resolved_request_id,
                baseline_export_id=baseline.id if baseline else None,
                snapshot_submission_ids=[submission.id for submission in current_submissions],
                exported_submission_ids=[submission.id for submission in submissions],
                exported_people_snapshot=_export_people_snapshot(submissions),
                pending_recipient_count=len(pending_rows),
                artifact_metadata={
                    "workbook_bytes": len(content),
                    "supplemental_fields": requested_field_keys,
                    "group_by_field": resolved_group_by,
                },
                created_by_user_id=current_user.id,
                actor_email=current_user.email,
            )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This download request was already prepared by another "
                "request. Open download history or start a new download."
            ),
        ) from exc

    # Only persist a hidden prepared record here. The browser confirms it after
    # the complete response has been received and its download has been started.
    await session.commit()

    filename = f"passport-export-{group_id}.xlsx"
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Passport-Export-History-ID": str(history.id),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/groups/{group_id}/export-images",
    status_code=status.HTTP_200_OK,
    summary="Export a client group's current cropped passport images as ZIP",
)
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

    current_submissions = await _current_group_export_submissions(
        session,
        group_id=group_id,
        agency_id=current_user.agency_id,
        current_user=current_user,
    )
    resolved_request_id = request_id or uuid.uuid4()
    await _require_new_export_request(
        session,
        group_id=group_id,
        agency_id=current_user.agency_id,
        export_kind="passport_images",
        request_id=resolved_request_id,
        created_by_user_id=_owner_scope_for(current_user),
    )
    submissions, baseline = await _resolve_group_export_payload(
        session,
        group_id=group_id,
        agency_id=current_user.agency_id,
        export_kind="passport_images",
        export_mode=export_mode,
        baseline_export_id=baseline_export_id,
        submissions=current_submissions,
        created_by_user_id=_owner_scope_for(current_user),
    )
    crop_metadata = await PassportImageCropRepository(session).list_for_submissions(
        [submission.id for submission in submissions]
    )
    zone_names = await _export_zone_names(session, current_submissions)
    try:
        spool, image_count, uncompressed_bytes = await PassportImageZipExporter().export_group(
            submissions,
            group_name=group.name,
            staff_code_enabled=group.staff_code_enabled,
            agent_employee_code_enabled=group.agent_employee_code_enabled,
            storage=MinioStorageRepository(),
            crop_metadata=crop_metadata,
            zone_names=zone_names,
            namespace_submissions=current_submissions,
        )
    except MissingPassportImagesError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except PassportImageExportLimitError as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc))
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
                group_id=group_id,
                agency_id=current_user.agency_id,
                export_kind="passport_images",
                export_mode=export_mode,
                request_id=resolved_request_id,
                baseline_export_id=baseline.id if baseline else None,
                snapshot_submission_ids=[submission.id for submission in current_submissions],
                exported_submission_ids=[submission.id for submission in submissions],
                exported_people_snapshot=_export_people_snapshot(submissions),
                artifact_metadata={
                    "image_count": image_count,
                    "uncompressed_bytes": uncompressed_bytes,
                    "archive_bytes": archive_size,
                },
                created_by_user_id=current_user.id,
                actor_email=current_user.email,
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
    "/groups/{group_id}/import.xlsx",
    response_model=ImportPassportGroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Import passport submissions into a client group from Excel",
)
async def import_passports_by_group(
    group_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ImportPassportGroupResponse:
    if not current_user.agency_id or current_user.role == UserRole.AGENCY_COORDINATOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    group_repo = ClientGroupRepository(session)
    group = await group_repo.get_by_id(group_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client group was not found"
        )
    try:
        await AuthorizationPolicy(session).require_export_data(current_user, group)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)

    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Please upload an .xlsx Excel file"
        )

    try:
        content = await file.read()
        rows = PassportExcelImporter().import_rows(content)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to read the Excel file"
        )

    result = await session.execute(
        select(PassportSubmissionModel).where(PassportSubmissionModel.group_id == group.id)
    )
    existing_submissions = list(result.scalars().all())
    existing_by_staff_code = {
        code: submission
        for submission in existing_submissions
        if (code := _staff_code_for_submission(submission))
    }
    existing_by_identity = {
        _excel_identity_key(
            submission.client_name, submission.client_email, submission.client_phone
        ): submission
        for submission in existing_submissions
    }

    now = datetime.now(tz=UTC)
    models: list[PassportSubmissionModel] = []
    updated_count = 0
    seen_import_keys: set[str] = set()
    for row in rows:
        row_staff_code = (
            str(
                (row.staff_metadata or {}).get("staff_code")
                or row.confirmed_fields.get("staff_code")
                or ""
            )
            .strip()
            .upper()
        )
        row_identity = _excel_identity_key(row.client_name, row.client_email, row.client_phone)
        import_key = row_staff_code or row_identity
        if import_key in seen_import_keys:
            continue
        seen_import_keys.add(import_key)

        existing = (
            existing_by_staff_code.get(row_staff_code)
            if row_staff_code
            else existing_by_identity.get(row_identity)
        )
        if existing:
            existing.client_name = row.client_name
            existing.client_email = row.client_email
            existing.client_phone = row.client_phone
            existing.departure_city = row.departure_city
            existing.nearest_domestic_airport = row.nearest_domestic_airport
            existing.staff_metadata = row.staff_metadata or existing.staff_metadata
            existing.confirmed_fields = _merge_excel_fields(
                existing.confirmed_fields, row.confirmed_fields
            )
            existing.extracted_fields = _merge_excel_fields(
                existing.extracted_fields, row.confirmed_fields
            )
            existing.confidence_score = {
                **(existing.confidence_score or {}),
                "source": "excel_import",
                "row_number": row.row_number,
                "source_sheet": row.worksheet_name,
                "updated_from_excel": True,
            }
            existing.overall_confidence = (
                existing.overall_confidence
                if existing.overall_confidence is not None
                else (1.0 if row.confirmed_fields else None)
            )
            existing.updated_at = now
            updated_count += 1
            continue

        submission_id = uuid.uuid4()
        models.append(
            PassportSubmissionModel(
                id=submission_id,
                group_id=group.id,
                agency_id=group.agency_id,
                client_name=row.client_name,
                client_email=row.client_email,
                client_phone=row.client_phone,
                departure_city=row.departure_city,
                nearest_domestic_airport=row.nearest_domestic_airport,
                image_s3_key=f"excel-imports/{group.id}/{submission_id}.placeholder",
                status="client_submitted",
                confirmed_fields=row.confirmed_fields or None,
                extracted_fields=row.confirmed_fields or None,
                staff_metadata=row.staff_metadata or None,
                overall_confidence=1.0 if row.confirmed_fields else None,
                confidence_score={
                    "source": "excel_import",
                    "row_number": row.row_number,
                    "source_sheet": row.worksheet_name,
                },
                client_reviewed_at=now,
                created_at=now,
                updated_at=now,
            )
        )

    if models:
        session.add_all(models)
    if models or updated_count:
        await AuditLogRepository(session).record(
            action="passport_group_imported",
            entity_type="client_group",
            entity_id=str(group_id),
            agency_id=group.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "imported_count": len(models),
                "updated_count": updated_count,
                "filename": file.filename,
            },
        )
        await session.commit()

    return ImportPassportGroupResponse(
        imported_count=len(models),
        updated_count=updated_count,
        skipped_count=max(len(rows) - len(models) - updated_count, 0),
    )


def _excel_identity_key(name: str | None, email: str | None, phone: str | None) -> str:
    parts = [name or "", email or "", phone or ""]
    return "|".join(part.strip().casefold() for part in parts)


def _merge_excel_fields(existing: dict | None, imported: dict) -> dict | None:
    if not existing:
        return imported or None
    merged = dict(existing)
    for key, value in imported.items():
        if value not in (None, ""):
            merged[key] = value
    return merged


def _staff_code_for_submission(submission: PassportSubmissionModel) -> str | None:
    metadata = getattr(submission, "staff_metadata", None) or {}
    fields = submission.confirmed_fields or submission.extracted_fields or {}
    value = metadata.get("staff_code") or fields.get("staff_code")
    return str(value).strip().upper() if value else None


async def _authorized_passport_document_group(
    group_id: uuid.UUID, current_user: User, session: AsyncSession
) -> ClientGroupModel:
    if not current_user.agency_id or current_user.role == UserRole.AGENCY_COORDINATOR:
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
    return group


async def _passport_document_preview(
    *, group_id: uuid.UUID, files: list[UploadFile], session: AsyncSession
) -> tuple[PassportDocumentImportPreviewResponse, list[PassportDocumentFile]]:
    result = await session.execute(
        select(PassportSubmissionModel).where(PassportSubmissionModel.group_id == group_id)
    )
    submissions = list(result.scalars().all())
    by_staff_code = {
        code: submission
        for submission in submissions
        if (code := _staff_code_for_submission(submission))
    }
    payloads: list[tuple[str, bytes, str | None]] = []
    for file in files:
        try:
            payloads.append((file.filename or "upload", await file.read(), file.content_type))
        except Exception:
            payloads.append((file.filename or "upload", b"", file.content_type))
    accepted, rejected = PassportDocumentImporter().collect(
        payloads, allowed_staff_codes=set(by_staff_code)
    )
    response_accepted: list[PassportDocumentImportItem] = []
    matched: list[PassportDocumentFile] = []
    seen: set[tuple[uuid.UUID, str]] = set()
    for item in accepted:
        submission = by_staff_code.get(item.staff_code)
        if not submission:
            rejected.append(
                RejectedPassportDocument(item.filename, "Staff code was not found in this group")
            )
            continue
        key = (submission.id, item.document_type)
        if key in seen:
            rejected.append(
                RejectedPassportDocument(
                    item.filename, "Duplicate document type for this passenger"
                )
            )
            continue
        seen.add(key)
        matched.append(item)
        response_accepted.append(
            PassportDocumentImportItem(
                filename=item.filename,
                staff_code=item.staff_code,
                document_type=item.document_type,
                passenger_id=submission.id,
                passenger_name=submission.client_name,
                accepted=True,
            )
        )
    response_rejected = [
        PassportDocumentImportItem(filename=item.filename, accepted=False, reason=item.reason)
        for item in rejected
    ]
    return PassportDocumentImportPreviewResponse(
        group_id=group_id,
        total_count=len(response_accepted) + len(response_rejected),
        accepted_count=len(response_accepted),
        rejected_count=len(response_rejected),
        accepted_documents=response_accepted,
        rejected_documents=response_rejected,
    ), matched


@router.post(
    "/groups/{group_id}/import-passports/preview",
    response_model=PassportDocumentImportPreviewResponse,
)
async def preview_passport_documents_by_group(
    group_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportDocumentImportPreviewResponse:
    await _authorized_passport_document_group(group_id, current_user, session)
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose one or more images or ZIP archives",
        )
    preview, _ = await _passport_document_preview(group_id=group_id, files=files, session=session)
    return preview


@router.post(
    "/groups/{group_id}/import-passports/save", response_model=PassportDocumentImportSaveResponse
)
async def save_passport_documents_by_group(
    group_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportDocumentImportSaveResponse:
    group = await _authorized_passport_document_group(group_id, current_user, session)
    if not any((file.filename or "").lower().endswith(".zip") for file in files):
        return await _save_loose_passport_documents_by_group(
            group=group,
            group_id=group_id,
            files=files,
            current_user=current_user,
            session=session,
            background_tasks=background_tasks,
        )

    preview, matched = await _passport_document_preview(
        group_id=group_id, files=files, session=session
    )
    if not matched:
        return PassportDocumentImportSaveResponse(**preview.model_dump(), saved_count=0)

    result = await session.execute(
        select(PassportSubmissionModel)
        .where(PassportSubmissionModel.group_id == group_id)
        .with_for_update()
    )
    by_staff_code = {
        code: submission
        for submission in result.scalars().all()
        if (code := _staff_code_for_submission(submission))
    }
    storage = MinioStorageRepository()
    crop_repo = PassportImageCropRepository(session)
    library_repo = PassportImageLibraryRepository(session)
    uploaded_keys: list[str] = []
    replaced_keys: list[str] = []
    replaced_crop_keys: list[str] = []
    try:
        for item in matched:
            submission = by_staff_code[item.staff_code]
            image_type = {
                "front": PassportImageType.PASSPORT_FRONT,
                "photo": PassportImageType.VISA_PHOTO,
                "back": PassportImageType.PASSPORT_BACK,
            }[item.document_type]
            attr = {
                "front": "image_s3_key",
                "photo": "passport_photo_s3_key",
                "back": "passport_back_s3_key",
            }[item.document_type]
            old_key = getattr(submission, attr, None)
            suffix = item.upload.filename.rsplit(".", 1)[-1]
            key = (
                f"passport-bulk/{group.agency_id}/{group.id}/{submission.id}/"
                f"{uuid.uuid4().hex}-{item.document_type}.{suffix}"
            )
            await storage.upload_file(item.upload.content, key, item.upload.content_type)
            uploaded_keys.append(key)
            setattr(submission, attr, key)
            if old_key and old_key != key:
                if not old_key.startswith("excel-imports/"):
                    await library_repo.ensure_original(
                        submission_id=submission.id,
                        image_type=image_type,
                        storage_key=old_key,
                        created_at=submission.created_at,
                    )
                _, old_crop_key, old_edit_key = await crop_repo.reset(
                    submission_id=submission.id,
                    image_type=image_type,
                    updated_by_user_id=current_user.id,
                    expected_revision=None,
                )
                if old_crop_key:
                    replaced_crop_keys.append(old_crop_key)
                if old_edit_key:
                    replaced_crop_keys.append(old_edit_key)
            if old_key and not old_key.startswith("excel-imports/") and old_key != key:
                replaced_keys.append(old_key)
        await AuditLogRepository(session).record(
            action="passport_documents_bulk_imported",
            entity_type="client_group",
            entity_id=str(group_id),
            agency_id=group.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={"saved_count": len(matched), "rejected_count": preview.rejected_count},
        )
        await session.commit()
    except Exception:
        await session.rollback()
        await storage.delete_files(uploaded_keys)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save passport documents; no imported files were retained",
        )
    await _delete_unreferenced_passport_image_keys_best_effort(
        session=session,
        storage=storage,
        keys=[*replaced_keys, *replaced_crop_keys],
        group_id=group_id,
    )
    # OCR is only useful once the complete staff bundle is present. It enriches
    # blanks through PassportSubmission.mark_review_required without replacing
    # values imported from Excel.
    ocr_targets = []
    required_fields = (
        "passport_number",
        "surname",
        "given_names",
        "date_of_birth",
        "date_of_expiry",
    )
    for submission in {
        by_staff_code[item.staff_code].id: by_staff_code[item.staff_code] for item in matched
    }.values():
        fields = submission.confirmed_fields or submission.extracted_fields or {}
        has_all_images = (
            bool(submission.image_s3_key)
            and bool(getattr(submission, "passport_photo_s3_key", None))
            and bool(getattr(submission, "passport_back_s3_key", None))
        )
        if has_all_images and any(
            not str(fields.get(field, "")).strip() for field in required_fields
        ):
            ocr_targets.append(submission.id)
    if ocr_targets:
        reextract = ReextractPassportSubmissionUseCase(
            passport_repo=PassportSubmissionRepository(session),
            processing_job_repo=PassportProcessingJobRepository(session),
        )
        jobs = [await reextract.execute(submission_id) for submission_id in ocr_targets]
        await session.commit()
        for job in jobs:
            if job.processing_job_id:
                PassportProcessingDispatcher().dispatch(
                    job_id=job.processing_job_id,
                    submission_id=job.id,
                    background_tasks=background_tasks,
                )
    return PassportDocumentImportSaveResponse(**preview.model_dump(), saved_count=len(matched))


async def _save_loose_passport_documents_by_group(
    *,
    group: ClientGroupModel,
    group_id: uuid.UUID,
    files: list[UploadFile],
    current_user: User,
    session: AsyncSession,
    background_tasks: BackgroundTasks,
) -> PassportDocumentImportSaveResponse:
    result = await session.execute(
        select(PassportSubmissionModel)
        .where(PassportSubmissionModel.group_id == group_id)
        .with_for_update()
    )
    by_staff_code = {
        code: submission
        for submission in result.scalars().all()
        if (code := _staff_code_for_submission(submission))
    }
    importer = PassportDocumentImporter()
    storage = MinioStorageRepository()
    crop_repo = PassportImageCropRepository(session)
    library_repo = PassportImageLibraryRepository(session)
    uploaded_keys: list[str] = []
    replaced_keys: list[str] = []
    replaced_crop_keys: list[str] = []
    accepted_documents: list[PassportDocumentImportItem] = []
    rejected_documents: list[PassportDocumentImportItem] = []
    seen: set[tuple[uuid.UUID, str]] = set()
    touched_submissions: dict[uuid.UUID, PassportSubmissionModel] = {}

    try:
        for file in files:
            filename = file.filename or "upload"
            accepted, rejected = importer.collect(
                [(filename, await file.read(), file.content_type)],
                allowed_staff_codes=set(by_staff_code),
            )
            rejected_documents.extend(
                PassportDocumentImportItem(
                    filename=item.filename, accepted=False, reason=item.reason
                )
                for item in rejected
            )
            for item in accepted:
                submission = by_staff_code.get(item.staff_code)
                if not submission:
                    rejected_documents.append(
                        PassportDocumentImportItem(
                            filename=item.filename,
                            accepted=False,
                            reason="Staff code was not found in this group",
                        )
                    )
                    continue
                duplicate_key = (submission.id, item.document_type)
                if duplicate_key in seen:
                    rejected_documents.append(
                        PassportDocumentImportItem(
                            filename=item.filename,
                            accepted=False,
                            reason="Duplicate document type for this passenger",
                        )
                    )
                    continue
                seen.add(duplicate_key)

                image_type = {
                    "front": PassportImageType.PASSPORT_FRONT,
                    "photo": PassportImageType.VISA_PHOTO,
                    "back": PassportImageType.PASSPORT_BACK,
                }[item.document_type]
                attr = {
                    "front": "image_s3_key",
                    "photo": "passport_photo_s3_key",
                    "back": "passport_back_s3_key",
                }[item.document_type]
                old_key = getattr(submission, attr, None)
                suffix = item.upload.filename.rsplit(".", 1)[-1]
                key = (
                    f"passport-bulk/{group.agency_id}/{group.id}/{submission.id}/"
                    f"{uuid.uuid4().hex}-{item.document_type}.{suffix}"
                )
                await storage.upload_file(item.upload.content, key, item.upload.content_type)
                uploaded_keys.append(key)
                setattr(submission, attr, key)
                if old_key and old_key != key:
                    if not old_key.startswith("excel-imports/"):
                        await library_repo.ensure_original(
                            submission_id=submission.id,
                            image_type=image_type,
                            storage_key=old_key,
                            created_at=submission.created_at,
                        )
                    _, old_crop_key, old_edit_key = await crop_repo.reset(
                        submission_id=submission.id,
                        image_type=image_type,
                        updated_by_user_id=current_user.id,
                        expected_revision=None,
                    )
                    if old_crop_key:
                        replaced_crop_keys.append(old_crop_key)
                    if old_edit_key:
                        replaced_crop_keys.append(old_edit_key)
                submission.updated_at = datetime.now(tz=UTC)
                touched_submissions[submission.id] = submission
                accepted_documents.append(
                    PassportDocumentImportItem(
                        filename=item.filename,
                        staff_code=item.staff_code,
                        document_type=item.document_type,
                        passenger_id=submission.id,
                        passenger_name=submission.client_name,
                        accepted=True,
                    )
                )
                if old_key and not old_key.startswith("excel-imports/") and old_key != key:
                    replaced_keys.append(old_key)

        if accepted_documents:
            await AuditLogRepository(session).record(
                action="passport_documents_bulk_imported",
                entity_type="client_group",
                entity_id=str(group_id),
                agency_id=group.agency_id,
                user_id=current_user.id,
                actor_email=current_user.email,
                metadata={
                    "saved_count": len(accepted_documents),
                    "rejected_count": len(rejected_documents),
                    "streamed": True,
                },
            )
            await session.commit()
        else:
            await session.rollback()
    except Exception:
        await session.rollback()
        await storage.delete_files(uploaded_keys)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save passport documents; no imported files were retained",
        )

    await _delete_unreferenced_passport_image_keys_best_effort(
        session=session,
        storage=storage,
        keys=[*replaced_keys, *replaced_crop_keys],
        group_id=group_id,
    )

    await _queue_ocr_for_complete_staff_bundles(
        submissions=list(touched_submissions.values()),
        session=session,
        background_tasks=background_tasks,
    )
    return PassportDocumentImportSaveResponse(
        group_id=group_id,
        total_count=len(accepted_documents) + len(rejected_documents),
        accepted_count=len(accepted_documents),
        rejected_count=len(rejected_documents),
        accepted_documents=accepted_documents,
        rejected_documents=rejected_documents,
        saved_count=len(accepted_documents),
    )


async def _queue_ocr_for_complete_staff_bundles(
    *,
    submissions: list[PassportSubmissionModel],
    session: AsyncSession,
    background_tasks: BackgroundTasks,
) -> None:
    required_fields = (
        "passport_number",
        "surname",
        "given_names",
        "date_of_birth",
        "date_of_expiry",
    )
    ocr_targets = []
    for submission in submissions:
        fields = submission.confirmed_fields or submission.extracted_fields or {}
        has_all_images = (
            bool(submission.image_s3_key)
            and bool(getattr(submission, "passport_photo_s3_key", None))
            and bool(getattr(submission, "passport_back_s3_key", None))
        )
        if has_all_images and any(
            not str(fields.get(field, "")).strip() for field in required_fields
        ):
            ocr_targets.append(submission.id)
    if not ocr_targets:
        return
    reextract = ReextractPassportSubmissionUseCase(
        passport_repo=PassportSubmissionRepository(session),
        processing_job_repo=PassportProcessingJobRepository(session),
    )
    jobs = [await reextract.execute(submission_id) for submission_id in ocr_targets]
    await session.commit()
    for job in jobs:
        if job.processing_job_id:
            PassportProcessingDispatcher().dispatch(
                job_id=job.processing_job_id,
                submission_id=job.id,
                background_tasks=background_tasks,
            )


@router.post(
    "/export.xlsx",
    status_code=status.HTTP_200_OK,
    summary="Export selected passport submissions to Excel",
)
async def export_selected_passports(
    body: ExportSelectedPassportsRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    if not current_user.agency_id or current_user.role == UserRole.AGENCY_COORDINATOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    stmt = (
        select(PassportSubmissionModel)
        .join(ClientGroupModel, PassportSubmissionModel.group_id == ClientGroupModel.id)
        .where(
            PassportSubmissionModel.id.in_(body.submission_ids),
            PassportSubmissionModel.status.in_(_submitted_statuses()),
        )
    )
    stmt = _apply_manager_visibility(stmt, current_user)
    result = await session.execute(stmt)
    submissions = [
        PassportSubmissionRepository._to_entity(model) for model in result.scalars().all()
    ]
    if not submissions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No exportable passport submissions found"
        )

    content = PassportExcelExporter().export_group(
        submissions,
        group_name="Selected Passports",
        group_details=await _export_group_details(
            session, [submission.group_id for submission in submissions]
        ),
        zone_names=await _export_zone_names(session, submissions),
    )
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="selected-passports.xlsx"'},
    )


@router.post(
    "/groups/export.xlsx",
    status_code=status.HTTP_200_OK,
    summary="Export selected passport groups to Excel",
)
async def export_selected_groups(
    body: ExportSelectedGroupsRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    if not current_user.agency_id or current_user.role == UserRole.AGENCY_COORDINATOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    group_stmt = select(ClientGroupModel).where(ClientGroupModel.id.in_(set(body.group_ids)))
    group_stmt = AuthorizationPolicy.apply_group_visibility_scope(
        group_stmt,
        current_user,
    )
    group_result = await session.execute(group_stmt)
    groups = [ClientGroupRepository._to_entity(model) for model in group_result.scalars().all()]
    if not groups:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No exportable passport groups found",
        )

    visible_group_ids = [group.id for group in groups]
    stmt = (
        select(PassportSubmissionModel)
        .join(ClientGroupModel, PassportSubmissionModel.group_id == ClientGroupModel.id)
        .where(
            PassportSubmissionModel.group_id.in_(visible_group_ids),
            PassportSubmissionModel.status.in_(_submitted_statuses()),
        )
    )
    stmt = _apply_manager_visibility(stmt, current_user)
    result = await session.execute(stmt)
    submissions = [
        PassportSubmissionRepository._to_entity(model) for model in result.scalars().all()
    ]

    match_rows_by_group = await _export_whatsapp_match_rows(
        session,
        submissions,
        groups=groups,
    )
    pending_rows = [
        pending_row
        for group in groups
        for pending_row in _pending_recipient_export_rows(
            group=group,
            rows=match_rows_by_group.get(group.id, []),
        )
    ]
    if not submissions and not pending_rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No exportable passport submissions or pending recipients found",
        )

    content = PassportExcelExporter().export_group(
        submissions,
        group_name="Selected Groups",
        group_details={group.id: _group_export_details(group) for group in groups},
        zone_names=_export_zone_names_from_match_rows(
            submissions,
            match_rows_by_group,
        ),
        additional_fields=[{"key": "zone_name", "label": "Zone Name"}],
        group_by_field="zone_name",
        pending_rows=pending_rows,
    )
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="selected-groups-passports.xlsx"'},
    )


async def _authorized_staff_passport_image(
    *,
    submission_id: uuid.UUID,
    image_type: PassportImageType,
    current_user: User,
    session: AsyncSession,
    require_editor: bool,
):  # type: ignore[no-untyped-def]
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
        sharpness_algorithm_version=(effective.sharpness_algorithm_version if effective else 1),
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
        referenced_keys = await PassportImageLibraryRepository(
            session
        ).referenced_storage_keys(unique_keys)
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
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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


@router.get(
    "/{submission_id}/images/{image_type}/edit-source",
    status_code=status.HTTP_200_OK,
    summary="Stream the current full-resolution source to an authorized image editor",
)
async def get_passport_image_edit_source(
    submission_id: uuid.UUID,
    image_type: PassportImageType,
    crop_revision: int | None = Query(default=None, ge=0),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    del crop_revision
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    crop_row = await PassportImageCropRepository(session).get(submission.id, image_type)
    effective = _effective_crop(crop_row, source_storage_key=source_key)
    edit_source_key = (
        effective.edit_source_storage_key
        if effective and effective.edit_source_storage_key
        else source_key
    )
    try:
        content = await MinioStorageRepository().get_file(edit_source_key)
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        ) from exc
    content_type = mimetypes.guess_type(edit_source_key)[0] or "image/jpeg"
    extension = mimetypes.guess_extension(content_type) or ".jpg"
    return StreamingResponse(
        io.BytesIO(content),
        media_type=content_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'inline; filename="{image_type.value}-edit-source{extension}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/{submission_id}/images/{image_type}",
    status_code=status.HTTP_200_OK,
    summary="Stream the effective staff view of a passport image",
)
async def get_passport_image_view(
    submission_id: uuid.UUID,
    image_type: PassportImageType,
    crop_revision: int | None = Query(default=None, ge=0),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    del crop_revision  # cache-buster only; callers cannot select crop history
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=False,
    )
    crop_row = await PassportImageCropRepository(session).get(submission.id, image_type)
    effective = _effective_crop(crop_row, source_storage_key=source_key)
    storage = MinioStorageRepository()
    content, content_type, extension = await _load_effective_passport_image(
        storage=storage,
        source_key=source_key,
        effective_crop=effective,
    )
    return StreamingResponse(
        io.BytesIO(content),
        media_type=content_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'inline; filename="{image_type.value}{extension}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/{submission_id}/images/{image_type}/thumbnail",
    status_code=status.HTTP_200_OK,
    summary="Return a bounded authenticated dashboard thumbnail",
)
async def get_passport_image_thumbnail(
    submission_id: uuid.UUID,
    image_type: PassportImageType,
    crop_revision: int | None = Query(default=None, ge=0),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    del crop_revision  # cache-buster only; callers cannot select crop history
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=False,
    )
    crop_row = await PassportImageCropRepository(session).get(submission.id, image_type)
    effective = _effective_crop(crop_row, source_storage_key=source_key)
    effective_identity = (
        effective.derived_storage_key if effective and effective.derived_storage_key else source_key
    )
    cache_key = hashlib.sha256(effective_identity.encode("utf-8")).hexdigest()
    storage = MinioStorageRepository()

    async def create_thumbnail():  # type: ignore[no-untyped-def]
        content, _, _ = await _load_effective_passport_image(
            storage=storage,
            source_key=source_key,
            effective_crop=effective,
        )
        try:
            return await asyncio.to_thread(
                render_passport_image_thumbnail,
                content,
                max_dimension=get_settings().dashboard_thumbnail_max_dimension,
            )
        except PassportImageCropError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    thumbnail = await _dashboard_thumbnail_cache().get_or_create(
        cache_key,
        create_thumbnail,
    )
    return Response(
        content=thumbnail.content,
        media_type=thumbnail.content_type,
        headers={
            # Passport/Visa previews are private PII. Keep them out of shared
            # and persistent browser caches; the bounded worker cache absorbs
            # repeat rendering without weakening the authorization boundary.
            "Cache-Control": "private, no-store",
            "Content-Disposition": (f'inline; filename="{image_type.value}-thumbnail.jpg"'),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/{submission_id}/images/{image_type}/original",
    status_code=status.HTTP_200_OK,
    summary="Stream an immutable original image to an authorized crop editor",
)
async def get_passport_image_original(
    submission_id: uuid.UUID,
    image_type: PassportImageType,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    _, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    try:
        content = await MinioStorageRepository().get_file(source_key)
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message
        ) from exc
    content_type = mimetypes.guess_type(source_key)[0] or "image/jpeg"
    extension = mimetypes.guess_extension(content_type) or ".jpg"
    return StreamingResponse(
        io.BytesIO(content),
        media_type=content_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'inline; filename="{image_type.value}-original{extension}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/{submission_id}/images/{image_type}/crop",
    response_model=PassportImageCropResponse,
    status_code=status.HTTP_200_OK,
    summary="Get crop-editor metadata for one passport image",
)
async def get_passport_image_crop(
    submission_id: uuid.UUID,
    image_type: PassportImageType,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportImageCropResponse:
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    crop_row = await PassportImageCropRepository(session).get(submission.id, image_type)
    effective = _effective_crop(crop_row, source_storage_key=source_key)
    source_width = effective.source_width if effective else None
    source_height = effective.source_height if effective else None
    return _crop_response(
        submission_id=submission.id,
        image_type=image_type,
        crop_row=crop_row,
        source_storage_key=source_key,
        source_width=source_width,
        source_height=source_height,
    )


@router.put(
    "/{submission_id}/images/{image_type}/crop",
    response_model=PassportImageCropResponse,
    status_code=status.HTTP_200_OK,
    summary="Save a non-destructive crop for one passport image",
)
async def update_passport_image_crop(
    submission_id: uuid.UUID,
    image_type: PassportImageType,
    body: PassportImageCropUpdateRequest,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportImageCropResponse:
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    storage = MinioStorageRepository()
    existing_crop = await PassportImageCropRepository(session).get(submission.id, image_type)
    effective_existing = _effective_crop(existing_crop, source_storage_key=source_key)
    edit_source_key = (
        effective_existing.edit_source_storage_key
        if effective_existing and effective_existing.edit_source_storage_key
        else source_key
    )
    try:
        original = await storage.get_file(edit_source_key)
        rendered = await asyncio.to_thread(
            render_passport_image_crop,
            original,
            x=body.x,
            y=body.y,
            width=body.width,
            height=body.height,
            rotation_degrees=body.rotation_degrees,
            sharpness=body.sharpness,
            sharpness_algorithm_version=2,
        )
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message
        ) from exc
    except PassportImageCropError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    derived_key = (
        f"passport-crops/{submission.agency_id}/{submission.id}/"
        f"{image_type.value}/{uuid.uuid4().hex}{rendered.extension}"
    )
    try:
        await storage.upload_file(rendered.content, derived_key, rendered.content_type)
    except StorageError as exc:
        await _delete_crop_derivative_best_effort(storage, derived_key, submission_id=submission.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message
        ) from exc

    previous_derived_key: str | None = None
    previous_edit_source_key: str | None = None
    try:
        locked = await PassportSubmissionRepository(session).get_by_id_for_update(submission.id)
        if not locked or passport_image_storage_key(locked, image_type) != source_key:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The source image changed. Refresh it and crop again.",
            )
        (
            crop_row,
            previous_derived_key,
            previous_edit_source_key,
        ) = await PassportImageCropRepository(session).upsert(
            submission_id=submission.id,
            image_type=image_type,
            source_storage_key=source_key,
            edit_source_storage_key=(
                effective_existing.edit_source_storage_key if effective_existing else None
            ),
            derived_storage_key=derived_key,
            x=body.x,
            y=body.y,
            width=body.width,
            height=body.height,
            rotation_degrees=body.rotation_degrees,
            sharpness=body.sharpness,
            source_width=rendered.source_width,
            source_height=rendered.source_height,
            updated_by_user_id=current_user.id,
            expected_revision=body.expected_revision,
        )
        await AuditLogRepository(session).record(
            action="passport_image_crop_saved",
            entity_type="passport_submission",
            entity_id=str(submission.id),
            agency_id=submission.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "image_type": image_type.value,
                "crop_revision": crop_row.revision,
                "sharpness": crop_row.sharpness,
                "sharpness_algorithm_version": crop_row.sharpness_algorithm_version,
                "ai_edited": bool(crop_row.edit_source_storage_key),
            },
        )
        await session.commit()
    except PassportImageCropRevisionConflict as exc:
        await session.rollback()
        await _delete_crop_derivative_best_effort(storage, derived_key, submission_id=submission.id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The image crop changed (current revision {exc.current_revision}). Refresh it and try again.",
            headers={"X-Current-Crop-Revision": str(exc.current_revision)},
        ) from exc
    except Exception:
        await session.rollback()
        await _delete_crop_derivative_best_effort(storage, derived_key, submission_id=submission.id)
        raise

    if previous_derived_key and previous_derived_key != derived_key:
        await _delete_crop_derivative_best_effort(
            storage, previous_derived_key, submission_id=submission.id
        )
    if previous_edit_source_key and previous_edit_source_key != crop_row.edit_source_storage_key:
        await _delete_ephemeral_edit_source_best_effort(
            session=session,
            storage=storage,
            key=previous_edit_source_key,
            submission_id=submission.id,
        )
    return _crop_response(
        submission_id=submission.id,
        image_type=image_type,
        crop_row=crop_row,
        source_storage_key=source_key,
    )


@router.post(
    "/{submission_id}/images/visa_photo/ai-preview",
    status_code=status.HTTP_200_OK,
    summary="Generate an identity-preserving Visa photo edit preview",
)
async def preview_visa_ai_image_edit(
    submission_id: uuid.UUID,
    body: PassportVisaAiPreviewRequest,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    image_type = PassportImageType.VISA_PHOTO
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    crop_row = await PassportImageCropRepository(session).get(submission.id, image_type)
    effective = _effective_crop(crop_row, source_storage_key=source_key)
    edit_source_key = _visa_ai_input_storage_key(
        source_key=source_key,
        effective_crop=effective,
    )
    normalized_prompt = " ".join(body.prompt.strip().split())
    try:
        source_content = await MinioStorageRepository().get_file(edit_source_key)
        result = await GeminiVisaImageEditService().edit(
            source_content,
            prompt=normalized_prompt,
        )
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        ) from exc
    except GeminiVisaImageEditError as exc:
        raise _visa_ai_edit_http_exception(exc) from exc

    revision = crop_row.revision if crop_row else 0
    token = issue_passport_ai_edit_token(
        secret=get_settings().app_secret_key,
        submission_id=submission.id,
        user_id=current_user.id,
        image_type=image_type.value,
        expected_revision=revision,
        source_storage_key=source_key,
        prompt=normalized_prompt,
        image_content=result.content,
    )
    await AuditLogRepository(session).record(
        action="passport_visa_ai_edit_previewed",
        entity_type="passport_submission",
        entity_id=str(submission.id),
        agency_id=submission.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "image_type": image_type.value,
            "crop_revision": revision,
            "prompt_sha256": result.prompt_sha256,
        },
    )
    await session.commit()
    return Response(
        content=result.content,
        media_type=result.content_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": 'inline; filename="visa-ai-preview.jpg"',
            "X-Content-Type-Options": "nosniff",
            "X-Visa-AI-Edit-Token": token,
        },
    )


def _visa_ai_edit_http_exception(exc: GeminiVisaImageEditError) -> HTTPException:
    if isinstance(exc, GeminiVisaImageEditRejected):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    if isinstance(exc, GeminiVisaImageEditNotConfigured):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    if isinstance(exc, GeminiVisaImageEditProviderUnavailable):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    if isinstance(exc, GeminiVisaImageEditProviderRejected):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=str(exc),
    )


def _visa_ai_library_response(
    *,
    submission_id: uuid.UUID,
    generation: PassportVisaAiImage,
    current_storage_key: str | None,
) -> PassportVisaAiImageResponse:
    return PassportVisaAiImageResponse(
        id=generation.id,
        image_url=_passport_visa_ai_library_image_api_url(
            submission_id,
            generation.id,
        ),
        prompt=generation.prompt,
        model=generation.model,
        created_at=generation.created_at,
        is_current=(generation.generated_storage_key == current_storage_key),
    )


async def _visa_ai_job_response(
    *,
    submission_id: uuid.UUID,
    job: PassportVisaAiImageJob,
    current_storage_key: str | None,
    session: AsyncSession,
) -> PassportVisaAiImageJobResponse:
    result = None
    if job.result_image_id:
        generation = await PassportVisaAiImageRepository(session).get_for_submission(
            submission_id,
            job.result_image_id,
        )
        if generation:
            result = _visa_ai_library_response(
                submission_id=submission_id,
                generation=generation,
                current_storage_key=current_storage_key,
            )
    return PassportVisaAiImageJobResponse(
        id=job.id,
        status=job.status,
        prompt=job.prompt,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        error_message=job.error_message,
        result=result,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


async def _dispatch_queued_visa_ai_job(
    *,
    job: PassportVisaAiImageJob,
    session: AsyncSession,
) -> PassportVisaAiImageJob:
    if job.status != "queued" or job.celery_task_id:
        return job

    # Commit the durable outbox row before publishing. If publishing fails, a
    # later short status poll retries it without rerunning work in the request.
    await session.commit()
    task_id = await dispatch_visa_ai_image_job(
        job_id=job.id,
        submission_id=job.submission_id,
    )
    repository = PassportVisaAiImageJobRepository(session)
    if task_id:
        current = await repository.get_for_submission(job.submission_id, job.id)
        if current and current.status == "queued" and not current.celery_task_id:
            await repository.set_task_id(job.id, task_id)
            await session.commit()
    refreshed = await repository.get_for_submission(job.submission_id, job.id)
    return refreshed or job


async def _recover_and_dispatch_visa_ai_job(
    *,
    job: PassportVisaAiImageJob,
    session: AsyncSession,
) -> PassportVisaAiImageJob:
    if job.status == "running":
        recovered = await PassportVisaAiImageJobRepository(session).recover_stale(job.id)
        if recovered:
            await session.commit()
            job = recovered
    return await _dispatch_queued_visa_ai_job(job=job, session=session)


@router.post(
    "/{submission_id}/images/visa_photo/ai-jobs",
    response_model=PassportVisaAiImageJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a durable verified Visa AI image generation",
)
async def create_visa_ai_image_job(
    submission_id: uuid.UUID,
    body: PassportVisaAiPreviewRequest,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportVisaAiImageJobResponse:
    image_type = PassportImageType.VISA_PHOTO
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    try:
        normalized_prompt = GeminiVisaImageEditService.validate_prompt(body.prompt)
    except GeminiVisaImageEditRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    settings = get_settings()
    google_key = settings.google_api_key.get_secret_value() if settings.google_api_key else ""
    if not settings.gemini_image_edit_model.strip() or not google_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Visa AI editing is not configured. Add "
                "GEMINI_IMAGE_EDIT_MODEL and a Google API key."
            ),
        )

    crop_row = await PassportImageCropRepository(session).get(submission.id, image_type)
    effective = _effective_crop(crop_row, source_storage_key=source_key)
    input_storage_key = _visa_ai_input_storage_key(
        source_key=source_key,
        effective_crop=effective,
    )
    repository = PassportVisaAiImageJobRepository(session)
    job, created = await repository.enqueue(
        submission_id=submission.id,
        original_source_storage_key=source_key,
        input_storage_key=input_storage_key,
        prompt=normalized_prompt,
        requested_by_user_id=current_user.id,
    )
    if created:
        await AuditLogRepository(session).record(
            action="passport_visa_ai_image_queued",
            entity_type="passport_submission",
            entity_id=str(submission.id),
            agency_id=submission.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "image_type": image_type.value,
                "job_id": str(job.id),
                "prompt_sha256": job.prompt_sha256,
            },
        )
    job = await _dispatch_queued_visa_ai_job(job=job, session=session)
    return await _visa_ai_job_response(
        submission_id=submission.id,
        job=job,
        current_storage_key=(effective.edit_source_storage_key if effective else None),
        session=session,
    )


@router.get(
    "/{submission_id}/images/visa_photo/ai-jobs/active",
    response_model=PassportVisaAiImageJobResponse | None,
    status_code=status.HTTP_200_OK,
    summary="Resume the active Visa AI image generation, if any",
)
async def get_active_visa_ai_image_job(
    submission_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportVisaAiImageJobResponse | None:
    image_type = PassportImageType.VISA_PHOTO
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    job = await PassportVisaAiImageJobRepository(session).active_for_submission(submission.id)
    if job is None:
        return None
    job = await _recover_and_dispatch_visa_ai_job(job=job, session=session)
    crop_row = await PassportImageCropRepository(session).get(submission.id, image_type)
    effective = _effective_crop(crop_row, source_storage_key=source_key)
    return await _visa_ai_job_response(
        submission_id=submission.id,
        job=job,
        current_storage_key=(effective.edit_source_storage_key if effective else None),
        session=session,
    )


@router.get(
    "/{submission_id}/images/visa_photo/ai-jobs/{job_id}",
    response_model=PassportVisaAiImageJobResponse,
    status_code=status.HTTP_200_OK,
    summary="Get one durable Visa AI image generation job",
)
async def get_visa_ai_image_job(
    submission_id: uuid.UUID,
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportVisaAiImageJobResponse:
    image_type = PassportImageType.VISA_PHOTO
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    job = await PassportVisaAiImageJobRepository(session).get_for_submission(
        submission.id,
        job_id,
    )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The Visa AI generation job was not found.",
        )
    job = await _recover_and_dispatch_visa_ai_job(job=job, session=session)
    crop_row = await PassportImageCropRepository(session).get(submission.id, image_type)
    effective = _effective_crop(crop_row, source_storage_key=source_key)
    return await _visa_ai_job_response(
        submission_id=submission.id,
        job=job,
        current_storage_key=(effective.edit_source_storage_key if effective else None),
        session=session,
    )


@router.get(
    "/{submission_id}/images/visa_photo/ai-library",
    response_model=PassportVisaAiImageListResponse,
    status_code=status.HTTP_200_OK,
    summary="List saved, verified Visa AI image generations",
)
async def list_visa_ai_image_library(
    submission_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportVisaAiImageListResponse:
    image_type = PassportImageType.VISA_PHOTO
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    crop_row = await PassportImageCropRepository(session).get(submission.id, image_type)
    effective = _effective_crop(crop_row, source_storage_key=source_key)
    current_storage_key = effective.edit_source_storage_key if effective else None
    generations = await PassportVisaAiImageRepository(session).list_for_submission(submission.id)
    return PassportVisaAiImageListResponse(
        items=[
            _visa_ai_library_response(
                submission_id=submission.id,
                generation=generation,
                current_storage_key=current_storage_key,
            )
            for generation in generations
        ]
    )


@router.get(
    "/{submission_id}/images/visa_photo/ai-library/{generation_id}/image",
    status_code=status.HTTP_200_OK,
    summary="Stream one saved Visa AI image generation",
)
async def get_visa_ai_library_image(
    submission_id: uuid.UUID,
    generation_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=PassportImageType.VISA_PHOTO,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    generation = await PassportVisaAiImageRepository(session).get_for_submission(
        submission_id,
        generation_id,
    )
    if not generation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The saved Visa AI image was not found.",
        )
    try:
        content = await MinioStorageRepository().get_file(generation.generated_storage_key)
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        ) from exc
    return StreamingResponse(
        io.BytesIO(content),
        media_type="image/jpeg",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": 'inline; filename="visa-ai-generation.jpg"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/{submission_id}/images/visa_photo/ai-library",
    response_model=PassportVisaAiImageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate and automatically save a verified Visa AI image",
)
async def create_visa_ai_library_image(
    submission_id: uuid.UUID,
    body: PassportVisaAiPreviewRequest,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportVisaAiImageResponse:
    image_type = PassportImageType.VISA_PHOTO
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    crop_row = await PassportImageCropRepository(session).get(submission.id, image_type)
    effective = _effective_crop(crop_row, source_storage_key=source_key)
    input_storage_key = _visa_ai_input_storage_key(
        source_key=source_key,
        effective_crop=effective,
    )
    normalized_prompt = " ".join(body.prompt.strip().split())
    storage = MinioStorageRepository()
    try:
        source_content = await storage.get_file(input_storage_key)
        result = await GeminiVisaImageEditService().edit(
            source_content,
            prompt=normalized_prompt,
        )
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        ) from exc
    except GeminiVisaImageEditError as exc:
        raise _visa_ai_edit_http_exception(exc) from exc

    generated_storage_key = (
        f"passport-ai-library/{submission.agency_id}/{submission.id}/visa_photo/"
        f"{uuid.uuid4().hex}.jpg"
    )
    try:
        await storage.upload_file(
            result.content,
            generated_storage_key,
            result.content_type,
        )
    except StorageError as exc:
        await _delete_crop_derivative_best_effort(
            storage,
            generated_storage_key,
            submission_id=submission.id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        ) from exc

    try:
        locked = await PassportSubmissionRepository(session).get_by_id_for_update(submission.id)
        if not locked or passport_image_storage_key(locked, image_type) != source_key:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The source image changed. Refresh it and generate the edit again.",
            )
        generation = await PassportVisaAiImageRepository(session).create(
            submission_id=submission.id,
            original_source_storage_key=source_key,
            input_storage_key=input_storage_key,
            generated_storage_key=generated_storage_key,
            prompt=normalized_prompt,
            prompt_sha256=result.prompt_sha256,
            content_sha256=hashlib.sha256(result.content).hexdigest(),
            model=result.model,
            created_by_user_id=current_user.id,
        )
        await AuditLogRepository(session).record(
            action="passport_visa_ai_image_generated",
            entity_type="passport_submission",
            entity_id=str(submission.id),
            agency_id=submission.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "image_type": image_type.value,
                "generation_id": str(generation.id),
                "model": generation.model,
                "prompt_sha256": generation.prompt_sha256,
            },
        )
        await session.commit()
    except Exception:
        await session.rollback()
        await _delete_crop_derivative_best_effort(
            storage,
            generated_storage_key,
            submission_id=submission.id,
        )
        raise

    return _visa_ai_library_response(
        submission_id=submission.id,
        generation=generation,
        current_storage_key=(effective.edit_source_storage_key if effective else None),
    )


@router.post(
    "/{submission_id}/images/visa_photo/ai-library/{generation_id}/use",
    response_model=PassportImageCropResponse,
    status_code=status.HTTP_200_OK,
    summary="Use one saved Visa AI image as the active Visa photo",
)
async def use_visa_ai_library_image(
    submission_id: uuid.UUID,
    generation_id: uuid.UUID,
    body: PassportVisaAiImageUseRequest,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportImageCropResponse:
    image_type = PassportImageType.VISA_PHOTO
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    generation = await PassportVisaAiImageRepository(session).get_for_submission(
        submission.id,
        generation_id,
    )
    if not generation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The saved Visa AI image was not found.",
        )
    if generation.original_source_storage_key != source_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This generated image belongs to an older source photo and cannot be used.",
        )

    storage = MinioStorageRepository()
    try:
        generated_content = await storage.get_file(generation.generated_storage_key)
        rendered = await asyncio.to_thread(
            render_passport_image_crop,
            generated_content,
            x=body.x,
            y=body.y,
            width=body.width,
            height=body.height,
            rotation_degrees=body.rotation_degrees,
            sharpness=body.sharpness,
            sharpness_algorithm_version=2,
        )
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        ) from exc
    except PassportImageCropError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    derived_key = (
        f"passport-crops/{submission.agency_id}/{submission.id}/visa_photo/"
        f"{uuid.uuid4().hex}{rendered.extension}"
    )
    try:
        await storage.upload_file(rendered.content, derived_key, rendered.content_type)
    except StorageError as exc:
        await _delete_crop_derivative_best_effort(
            storage,
            derived_key,
            submission_id=submission.id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        ) from exc

    try:
        locked = await PassportSubmissionRepository(session).get_by_id_for_update(submission.id)
        if not locked or passport_image_storage_key(locked, image_type) != source_key:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The source image changed. Refresh it and try again.",
            )
        (
            crop_row,
            previous_derived_key,
            previous_edit_source_key,
        ) = await PassportImageCropRepository(session).upsert(
            submission_id=submission.id,
            image_type=image_type,
            source_storage_key=source_key,
            edit_source_storage_key=generation.generated_storage_key,
            derived_storage_key=derived_key,
            x=body.x,
            y=body.y,
            width=body.width,
            height=body.height,
            rotation_degrees=body.rotation_degrees,
            sharpness=body.sharpness,
            source_width=rendered.source_width,
            source_height=rendered.source_height,
            updated_by_user_id=current_user.id,
            expected_revision=body.expected_revision,
            sharpness_algorithm_version=2,
        )
        await AuditLogRepository(session).record(
            action="passport_visa_ai_image_selected",
            entity_type="passport_submission",
            entity_id=str(submission.id),
            agency_id=submission.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "generation_id": str(generation.id),
                "crop_revision": crop_row.revision,
            },
        )
        await session.commit()
    except PassportImageCropRevisionConflict as exc:
        await session.rollback()
        await _delete_crop_derivative_best_effort(
            storage,
            derived_key,
            submission_id=submission.id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The image edit changed (current revision {exc.current_revision}). Refresh it and try again.",
            headers={"X-Current-Crop-Revision": str(exc.current_revision)},
        ) from exc
    except Exception:
        await session.rollback()
        await _delete_crop_derivative_best_effort(
            storage,
            derived_key,
            submission_id=submission.id,
        )
        raise

    if previous_derived_key and previous_derived_key != derived_key:
        await _delete_crop_derivative_best_effort(
            storage,
            previous_derived_key,
            submission_id=submission.id,
        )
    if previous_edit_source_key != generation.generated_storage_key:
        await _delete_ephemeral_edit_source_best_effort(
            session=session,
            storage=storage,
            key=previous_edit_source_key,
            submission_id=submission.id,
        )
    return _crop_response(
        submission_id=submission.id,
        image_type=image_type,
        crop_row=crop_row,
        source_storage_key=source_key,
    )


@router.post(
    "/{submission_id}/images/visa_photo/ai-apply",
    response_model=PassportImageCropResponse,
    status_code=status.HTTP_200_OK,
    summary="Save a verified Visa AI edit with crop and sharpness metadata",
)
async def apply_visa_ai_image_edit(
    submission_id: uuid.UUID,
    image: UploadFile = File(...),
    preview_token: str = Form(..., min_length=20, max_length=2048),
    prompt: str = Form(..., min_length=3, max_length=1000),
    x: float = Form(...),
    y: float = Form(...),
    width: float = Form(...),
    height: float = Form(...),
    rotation_degrees: int = Form(...),
    sharpness: float = Form(...),
    expected_revision: int = Form(..., ge=0),
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportImageCropResponse:
    image_type = PassportImageType.VISA_PHOTO
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    normalized_prompt = " ".join(prompt.strip().split())
    limit = get_settings().upload_max_file_size_bytes
    content = await image.read(limit + 1)
    if not content or len(content) > limit:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="The generated Visa image is empty or too large.",
        )
    try:
        verify_passport_ai_edit_token(
            preview_token,
            secret=get_settings().app_secret_key,
            submission_id=submission.id,
            user_id=current_user.id,
            image_type=image_type.value,
            expected_revision=expected_revision,
            source_storage_key=source_key,
            prompt=normalized_prompt,
            image_content=content,
        )
        coordinates = PassportImageCropCoordinates(
            x=x,
            y=y,
            width=width,
            height=height,
            rotation_degrees=rotation_degrees,
            sharpness=sharpness,
        )
        canonical = await asyncio.to_thread(
            render_passport_image_crop,
            content,
            x=0.0,
            y=0.0,
            width=1.0,
            height=1.0,
            rotation_degrees=0,
            sharpness=1.0,
        )
        rendered = await asyncio.to_thread(
            render_passport_image_crop,
            canonical.content,
            x=coordinates.x,
            y=coordinates.y,
            width=coordinates.width,
            height=coordinates.height,
            rotation_degrees=coordinates.rotation_degrees,
            sharpness=coordinates.sharpness,
            sharpness_algorithm_version=2,
        )
    except PassportAiEditTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (PassportImageCropError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    edit_source_key = (
        f"passport-edits/{submission.agency_id}/{submission.id}/visa_photo/{uuid.uuid4().hex}.jpg"
    )
    derived_key = (
        f"passport-crops/{submission.agency_id}/{submission.id}/visa_photo/"
        f"{uuid.uuid4().hex}{rendered.extension}"
    )
    storage = MinioStorageRepository()
    try:
        await storage.upload_file(canonical.content, edit_source_key, canonical.content_type)
        await storage.upload_file(rendered.content, derived_key, rendered.content_type)
    except StorageError as exc:
        await _delete_crop_derivative_best_effort(
            storage,
            edit_source_key,
            submission_id=submission.id,
        )
        await _delete_crop_derivative_best_effort(
            storage,
            derived_key,
            submission_id=submission.id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        ) from exc

    previous_derived_key: str | None = None
    previous_edit_source_key: str | None = None
    try:
        locked = await PassportSubmissionRepository(session).get_by_id_for_update(submission.id)
        if not locked or passport_image_storage_key(locked, image_type) != source_key:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The source image changed. Refresh it and generate the edit again.",
            )
        ai_library_item = await PassportImageLibraryRepository(session).create_ai(
            submission_id=submission.id,
            image_type=image_type,
            storage_key=edit_source_key,
            original_source_storage_key=source_key,
            content_sha256=hashlib.sha256(canonical.content).hexdigest(),
            prompt=normalized_prompt,
            prompt_sha256=hashlib.sha256(normalized_prompt.encode("utf-8")).hexdigest(),
            model=get_settings().gemini_image_edit_model.strip(),
            created_by_user_id=current_user.id,
        )
        (
            crop_row,
            previous_derived_key,
            previous_edit_source_key,
        ) = await PassportImageCropRepository(session).upsert(
            submission_id=submission.id,
            image_type=image_type,
            source_storage_key=source_key,
            edit_source_storage_key=edit_source_key,
            derived_storage_key=derived_key,
            x=coordinates.x,
            y=coordinates.y,
            width=coordinates.width,
            height=coordinates.height,
            rotation_degrees=coordinates.rotation_degrees,
            sharpness=coordinates.sharpness,
            source_width=rendered.source_width,
            source_height=rendered.source_height,
            updated_by_user_id=current_user.id,
            expected_revision=expected_revision,
            sharpness_algorithm_version=2,
        )
        await AuditLogRepository(session).record(
            action="passport_visa_ai_edit_saved",
            entity_type="passport_submission",
            entity_id=str(submission.id),
            agency_id=submission.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "image_type": image_type.value,
                "crop_revision": crop_row.revision,
                "sharpness": crop_row.sharpness,
                "prompt_sha256": hashlib.sha256(normalized_prompt.encode("utf-8")).hexdigest(),
                "library_item_id": str(ai_library_item.id),
            },
        )
        await session.commit()
    except PassportImageCropRevisionConflict as exc:
        await session.rollback()
        await _delete_crop_derivative_best_effort(
            storage, edit_source_key, submission_id=submission.id
        )
        await _delete_crop_derivative_best_effort(storage, derived_key, submission_id=submission.id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The image edit changed (current revision {exc.current_revision}). Refresh it and try again.",
            headers={"X-Current-Crop-Revision": str(exc.current_revision)},
        ) from exc
    except Exception:
        await session.rollback()
        await _delete_crop_derivative_best_effort(
            storage, edit_source_key, submission_id=submission.id
        )
        await _delete_crop_derivative_best_effort(storage, derived_key, submission_id=submission.id)
        raise

    if previous_derived_key and previous_derived_key != derived_key:
        await _delete_crop_derivative_best_effort(
            storage,
            previous_derived_key,
            submission_id=submission.id,
        )
    if previous_edit_source_key and previous_edit_source_key != edit_source_key:
        await _delete_ephemeral_edit_source_best_effort(
            session=session,
            storage=storage,
            key=previous_edit_source_key,
            submission_id=submission.id,
        )
    return _crop_response(
        submission_id=submission.id,
        image_type=image_type,
        crop_row=crop_row,
        source_storage_key=source_key,
    )


@router.delete(
    "/{submission_id}/images/{image_type}/crop",
    response_model=PassportImageCropResponse,
    status_code=status.HTTP_200_OK,
    summary="Reset a passport image to its immutable original",
)
async def reset_passport_image_crop(
    submission_id: uuid.UUID,
    image_type: PassportImageType,
    body: PassportImageCropResetRequest,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportImageCropResponse:
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    locked = await PassportSubmissionRepository(session).get_by_id_for_update(submission.id)
    if not locked or passport_image_storage_key(locked, image_type) != source_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The source image changed. Refresh it and try again.",
        )
    try:
        (
            crop_row,
            previous_derived_key,
            previous_edit_source_key,
        ) = await PassportImageCropRepository(session).reset(
            submission_id=submission.id,
            image_type=image_type,
            updated_by_user_id=current_user.id,
            expected_revision=body.expected_revision,
        )
        if crop_row is not None and previous_derived_key:
            await AuditLogRepository(session).record(
                action="passport_image_crop_reset",
                entity_type="passport_submission",
                entity_id=str(submission.id),
                agency_id=submission.agency_id,
                user_id=current_user.id,
                actor_email=current_user.email,
                metadata={"image_type": image_type.value, "crop_revision": crop_row.revision},
            )
        await session.commit()
    except PassportImageCropRevisionConflict as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The image crop changed (current revision {exc.current_revision}). Refresh it and try again.",
            headers={"X-Current-Crop-Revision": str(exc.current_revision)},
        ) from exc

    await _delete_crop_derivative_best_effort(
        MinioStorageRepository(), previous_derived_key, submission_id=submission.id
    )
    await _delete_ephemeral_edit_source_best_effort(
        session=session,
        storage=MinioStorageRepository(),
        key=previous_edit_source_key,
        submission_id=submission.id,
    )
    return _crop_response(
        submission_id=submission.id,
        image_type=image_type,
        crop_row=crop_row,
        source_storage_key=source_key,
    )


@router.get(
    "/{submission_id}",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a passport submission by id",
)
async def get_passport(
    submission_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_user),
    use_case: GetPassportSubmissionUseCase = Depends(_get_get_passport_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    try:
        result = await use_case.execute(submission_id)
        await AuthorizationPolicy(session).require_view_passport(current_user, result)

        job = await PassportProcessingJobRepository(session).latest_for_submission(result.id)
        if job is not None and queued_job_needs_redelivery(job):
            await _dispatch_processing_job(
                replace(
                    result,
                    processing_job_id=job.id,
                    processing_job_status=job.status.value,
                    processing_progress=job.progress,
                    processing_stage=job.current_stage,
                ),
                session=session,
                background_tasks=background_tasks,
            )
        return await _response_from_dto(result, session=session)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=e.message)


@router.post(
    "/{submission_id}/client-submit",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit client-reviewed passport fields (Public)",
)
async def client_submit_passport(
    submission_id: uuid.UUID,
    body: ClientSubmitPassportRequest,
    background_tasks: BackgroundTasks,
    upload_session_id: str = Header(
        ...,
        alias="X-Upload-Session-ID",
        min_length=32,
        max_length=128,
    ),
    use_case: ClientSubmitPassportUseCase = Depends(_get_client_submit_passport_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    existing = await PassportSubmissionRepository(session).get_by_id(submission_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Passport submission was not found",
        )
    _require_public_upload_credential(existing, upload_session_id)

    result: PassportSubmissionOutputDTO | None = None
    verification_job = None
    committed = False
    commit_attempted = False
    try:
        result = await use_case.execute(
            submission_id,
            group_token=body.group_token,
            confirmed_fields=body.confirmed_fields,
            client_email=str(body.client_email) if body.client_email else None,
            client_phone=body.client_phone,
            departure_city=body.departure_city,
            nearest_domestic_airport=body.nearest_domestic_airport,
            base_city=body.base_city,
            staff_code=body.staff_code,
            agent_employee_type=body.agent_employee_type,
            agent_employee_code=body.agent_employee_code,
            designation=body.designation,
            agency_dealership_name=body.agency_dealership_name,
            meal_preference=body.meal_preference,
            submission_mode=body.submission_mode,
            family_group_id=body.family_group_id,
            family_member_index=body.family_member_index,
            family_relation=body.family_relation,
            family_gender=body.family_gender,
            family_head_name=body.family_head_name,
            family_head_email=str(body.family_head_email) if body.family_head_email else None,
            family_head_phone=body.family_head_phone,
            custom_answers=[
                answer.model_dump(mode="json") for answer in body.custom_answers
            ],
            custom_detail_answers=[
                answer.model_dump(mode="json")
                for answer in body.custom_detail_answers
            ],
        )
        verification_job = await PostSubmissionVerificationJobRepository(session).enqueue(
            submission_id=result.id,
            verification_revision=result.post_submission_verification_revision,
        )
        if not result.idempotent_replay:
            await AuditLogRepository(session).record(
                action="client_passport_submitted",
                entity_type="passport_submission",
                entity_id=str(result.id),
                agency_id=result.agency_id,
                metadata={
                    "group_id": str(result.group_id),
                    "submission_mode": result.submission_mode,
                    "qualifier_enabled_snapshot": (result.qualifier_enabled_snapshot),
                },
            )
            await NotificationRepository(session).create(
                agency_id=result.agency_id,
                type="passport_submitted",
                title="Client passport submitted",
                message="A client submitted reviewed passport details.",
                entity_type="passport_submission",
                entity_id=str(result.id),
            )
        # Commit the DB transition before deleting superseded draft objects.
        # A failed commit therefore leaves the original draft keys intact and
        # the traveller can retry safely.
        commit_attempted = True
        await session.commit()
        committed = True
        task_id = None
        if verification_job.status == "queued":
            task_id = PostSubmissionVerificationDispatcher().dispatch(
                job_id=verification_job.id,
                submission_id=result.id,
                verification_revision=result.post_submission_verification_revision,
                background_tasks=background_tasks,
            )
        if task_id:
            try:
                await PostSubmissionVerificationJobRepository(session).set_task_id(
                    verification_job.id,
                    task_id,
                )
                await session.commit()
            except Exception as exc:
                await session.rollback()
                logger.warning(
                    "post_submission_verification_task_id_persist_failed",
                    job_id=str(verification_job.id),
                    error_type=type(exc).__name__,
                )
        if result.storage_cleanup_keys:
            try:
                await MinioStorageRepository().delete_files(list(result.storage_cleanup_keys))
            except StorageError as exc:
                logger.warning(
                    "passport_draft_cleanup_deferred",
                    submission_id=str(result.id),
                    object_count=len(result.storage_cleanup_keys),
                    error_type=type(exc).__name__,
                )
        return PassportSubmissionResponse.model_validate(result)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except PassDetectionError as e:
        if not committed and not commit_attempted:
            await _cleanup_uncommitted_promotions(result)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
    except Exception:
        # Once commit was attempted its outcome can be ambiguous after a
        # connection loss. Deleting promoted objects could break a row that
        # PostgreSQL actually committed, so compensate only pre-commit errors.
        if not committed and not commit_attempted:
            await _cleanup_uncommitted_promotions(result)
        raise


@router.post(
    "/{submission_id}/staff-approve",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve a passport that needs post-submission review",
)
async def staff_approve_passport(
    submission_id: uuid.UUID,
    body: StaffApprovePassportRequest,
    response: Response,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    get_use_case: GetPassportSubmissionUseCase = Depends(_get_get_passport_use_case),
    approve_use_case: StaffApprovePassportUseCase = Depends(_get_staff_approve_passport_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse | JSONResponse:
    try:
        existing = await get_use_case.execute(submission_id)
        await AuthorizationPolicy(session).require_staff_approve_passport(
            current_user,
            existing,
        )
        approval: StaffApprovalResult = await approve_use_case.execute(
            submission_id,
            reviewer_id=current_user.id,
            reviewer_name=current_user.full_name,
            confirmed_fields=body.confirmed_fields,
            expected_extraction_revision=body.expected_extraction_revision,
            review_reason=body.review_reason,
        )
        result = approval.submission
        if approval.outcome is StaffApprovalOutcome.APPROVED:
            audit_metadata: dict[str, object] = {
                "group_id": str(result.group_id),
                "prior_status": approval.previous_status,
                "new_status": result.status,
                "corrected_field_names": list(approval.corrected_field_names),
                "outcome": approval.outcome.value,
                "extraction_revision": result.extraction_revision,
                "verification_revision": (result.post_submission_verification_revision),
            }
            if approval.review_reason is not None:
                audit_metadata["review_reason"] = approval.review_reason
            await AuditLogRepository(session).record(
                action="passport_staff_approved",
                entity_type="passport_submission",
                entity_id=str(result.id),
                agency_id=result.agency_id,
                user_id=current_user.id,
                metadata=audit_metadata,
            )
            await _ensure_submission_qr(session, result.id, current_user.id)

        # The locked transition, audit row, and first QR issuance are one
        # transaction. Commit before presigned-URL work so the row lock is
        # released and a lost response can be retried idempotently.
        await session.commit()
        record_operational_event(
            OperationalEvent.STAFF_APPROVAL,
            (
                "approved"
                if approval.outcome is StaffApprovalOutcome.APPROVED
                else "already_approved"
            ),
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Staff-Approval-Outcome"] = approval.outcome.value
        response.headers["X-Staff-Approval-Revision"] = str(result.extraction_revision)
        return await _response_from_dto(result, session=session)
    except (StaffApprovalStaleError, StaffApprovalUnavailableError) as exc:
        # The typed conflict is raised while the submission row is locked.
        # Release that lock before returning the retry-safe 409 response.
        await session.rollback()
        record_operational_event(
            OperationalEvent.STAFF_APPROVAL,
            ("stale" if isinstance(exc, StaffApprovalStaleError) else "unavailable"),
        )
        return _staff_approval_conflict_response(exc)
    except EntityNotFoundError as exc:
        record_operational_event(
            OperationalEvent.STAFF_APPROVAL,
            "not_found",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        )
    except AuthorizationError as exc:
        record_operational_event(
            OperationalEvent.STAFF_APPROVAL,
            "forbidden",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        )
    except Exception:
        record_operational_event(
            OperationalEvent.STAFF_APPROVAL,
            "unexpected_failure",
        )
        raise


@router.post(
    "/{submission_id}/retry-ai-verification",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Retry AI verification after a temporary provider failure",
)
async def retry_post_submission_verification(
    submission_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    get_use_case: GetPassportSubmissionUseCase = Depends(_get_get_passport_use_case),
    retry_use_case: RetryPostSubmissionVerificationUseCase = Depends(
        _get_retry_post_submission_verification_use_case
    ),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    try:
        existing = await get_use_case.execute(submission_id)
        await AuthorizationPolicy(session).require_confirm_passport(
            current_user,
            existing,
        )
        retry_result = await retry_use_case.execute(submission_id)
        result = retry_result.submission
        verification_job = await PostSubmissionVerificationJobRepository(session).enqueue(
            submission_id=result.id,
            verification_revision=result.post_submission_verification_revision,
        )
        await AuditLogRepository(session).record(
            action="passport_post_submission_verification_retry_requested",
            entity_type="passport_submission",
            entity_id=str(result.id),
            agency_id=result.agency_id,
            user_id=current_user.id,
            metadata={
                "group_id": str(result.group_id),
                "previous_provider_status": retry_result.previous_provider_status,
                "previous_reason_code": retry_result.previous_reason_code,
                "verification_revision": result.post_submission_verification_revision,
            },
        )

        # The submission revision and durable outbox job must be committed
        # together before any worker can claim the new revision.
        await session.commit()
        if verification_job.status == "queued":
            try:
                task_id = PostSubmissionVerificationDispatcher().dispatch(
                    job_id=verification_job.id,
                    submission_id=result.id,
                    verification_revision=result.post_submission_verification_revision,
                    background_tasks=background_tasks,
                )
            except Exception as exc:
                # The recovery loop will publish the already-committed outbox
                # row. A queue outage must not lose or duplicate the request.
                logger.error(
                    "post_submission_verification_retry_dispatch_deferred",
                    job_id=str(verification_job.id),
                    error_type=type(exc).__name__,
                )
            else:
                if task_id:
                    try:
                        await PostSubmissionVerificationJobRepository(session).set_task_id(
                            verification_job.id, task_id
                        )
                        await session.commit()
                    except Exception as exc:
                        await session.rollback()
                        logger.warning(
                            "post_submission_verification_retry_task_id_persist_failed",
                            job_id=str(verification_job.id),
                            error_type=type(exc).__name__,
                        )
        return await _response_from_dto(result, session=session)
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        )
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        )
    except PassDetectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.message,
        )


@router.post(
    "/{submission_id}/reextract",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Rerun automatic extraction for a passport submission",
)
async def reextract_passport(
    submission_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_user),
    get_use_case: GetPassportSubmissionUseCase = Depends(_get_get_passport_use_case),
    reextract_use_case: ReextractPassportSubmissionUseCase = Depends(
        _get_reextract_passport_use_case
    ),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    try:
        existing = await get_use_case.execute(submission_id)
        await AuthorizationPolicy(session).require_confirm_passport(current_user, existing)

        result = await reextract_use_case.execute(submission_id)
        await _dispatch_processing_job(result, session=session, background_tasks=background_tasks)
        await AuditLogRepository(session).record(
            action="passport_reextract_queued",
            entity_type="passport_submission",
            entity_id=str(result.id),
            agency_id=result.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
        )
        return await _response_from_dto(result, session=session)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=e.message)
    except PassDetectionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


@router.post(
    "/{submission_id}/cancel-processing",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Request cancellation of queued passport extraction",
)
async def cancel_passport_processing(
    submission_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    get_use_case: GetPassportSubmissionUseCase = Depends(_get_get_passport_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    try:
        existing = await get_use_case.execute(submission_id)
        await AuthorizationPolicy(session).require_confirm_passport(current_user, existing)

        job_repo = PassportProcessingJobRepository(session)
        job = await job_repo.latest_for_submission(submission_id)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Processing job was not found"
            )

        await job_repo.request_cancel(job.id)
        await AuditLogRepository(session).record(
            action="passport_processing_cancel_requested",
            entity_type="passport_submission",
            entity_id=str(submission_id),
            agency_id=existing.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={"job_id": str(job.id)},
        )
        submission = await PassportSubmissionRepository(session).get_by_id(submission_id)
        if not submission:
            raise EntityNotFoundError("PassportSubmission", submission_id)
        return await _response_from_submission(submission, session=session)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=e.message)


@router.post(
    "/{submission_id}/confirm",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Confirm reviewed passport fields",
)
async def confirm_passport(
    submission_id: uuid.UUID,
    body: ConfirmPassportSubmissionRequest,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    get_use_case: GetPassportSubmissionUseCase = Depends(_get_get_passport_use_case),
    confirm_use_case: ConfirmPassportSubmissionUseCase = Depends(_get_confirm_passport_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    try:
        existing = await get_use_case.execute(submission_id)
        await AuthorizationPolicy(session).require_confirm_passport(current_user, existing)

        result = await confirm_use_case.execute(
            submission_id,
            confirmed_fields=body.confirmed_fields,
        )
        await AuditLogRepository(session).record(
            action="passport_confirmed",
            entity_type="passport_submission",
            entity_id=str(result.id),
            agency_id=result.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
        )
        await _ensure_submission_qr(session, result.id, current_user.id)
        return await _response_from_dto(result, session=session)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=e.message)
    except PassDetectionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
