"""Passport document import: focused workflow boundary."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.passport_dtos import PassportSubmissionOutputDTO
from app.application.mobile.passenger_change_propagation import propagate_mobile_passenger_change
from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.passports.reextract_passport_submission_use_case import (
    ReextractPassportSubmissionUseCase,
)
from app.core.logging.logger import get_logger
from app.domain.entities.entities import ClientGroup, User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.domain.value_objects.passport_image_crop import PassportImageType
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.documents.passport_import_compensation import (
    reconcile_failed_passport_import,
)
from app.infrastructure.imports.passport_document_importer import (
    PassportDocumentFile,
    PassportDocumentImporter,
    PassportDocumentImportWorkspace,
    PassportDocumentUploadSource,
    RejectedPassportDocument,
)
from app.infrastructure.processing.dispatcher import PassportProcessingDispatcher
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository,
)
from app.infrastructure.repositories.passport_image_library_repository import (
    PassportImageLibraryRepository,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportDocumentImportItem,
    PassportDocumentImportPreviewResponse,
    PassportDocumentImportSaveResponse,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

from .constants import _staff_code_for_submission
from .image_support import _delete_unreferenced_passport_image_keys_best_effort

router = APIRouter()
logger = get_logger(__name__)


async def _authorized_passport_document_group(
    group_id: uuid.UUID, current_user: User, session: AsyncSession
) -> ClientGroup:
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
    *,
    group_id: uuid.UUID,
    files: list[UploadFile],
    session: AsyncSession,
    workspace: PassportDocumentImportWorkspace,
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
    sources = await asyncio.to_thread(_passport_document_upload_sources, files)
    accepted, rejected = await asyncio.to_thread(
        PassportDocumentImporter().collect,
        sources,
        workspace=workspace,
        allowed_staff_codes=set(by_staff_code),
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


def _passport_document_upload_sources(
    files: list[UploadFile],
) -> list[PassportDocumentUploadSource]:
    """Measure seekable framework spools without materializing their bodies."""

    sources: list[PassportDocumentUploadSource] = []
    for upload in files:
        stream = upload.file
        try:
            stream.seek(0, 2)
            size_bytes = stream.tell()
            stream.seek(0)
        except (OSError, ValueError):
            size_bytes = -1
        sources.append(
            PassportDocumentUploadSource(
                filename=upload.filename or "upload",
                stream=stream,
                size_bytes=size_bytes,
                declared_content_type=upload.content_type,
            )
        )
    return sources


@router.post(
    "/groups/{group_id}/import-passports/preview",
    response_model=PassportDocumentImportPreviewResponse,
    dependencies=[Depends(require_cookie_csrf)],
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
    with PassportDocumentImportWorkspace() as workspace:
        preview, _ = await _passport_document_preview(
            group_id=group_id,
            files=files,
            session=session,
            workspace=workspace,
        )
    return preview


@router.post(
    "/groups/{group_id}/import-passports/save",
    response_model=PassportDocumentImportSaveResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def save_passport_documents_by_group(
    group_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportDocumentImportSaveResponse:
    group = await _authorized_passport_document_group(group_id, current_user, session)
    workspace = PassportDocumentImportWorkspace()
    try:
        preview, matched = await _passport_document_preview(
            group_id=group_id,
            files=files,
            session=session,
            workspace=workspace,
        )
    except Exception:
        workspace.close()
        raise
    if not matched:
        workspace.close()
        return PassportDocumentImportSaveResponse(**preview.model_dump(), saved_count=0)

    try:
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
    except Exception:
        workspace.close()
        raise
    import_id = uuid.uuid4()
    commit_attempted = False
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
            upload_content = await asyncio.to_thread(item.upload.read_content)
            uploaded_keys.append(key)
            await storage.upload_file(upload_content, key, item.upload.content_type)
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
        await propagate_mobile_passenger_change(
            session,
            agency_id=group.agency_id,
            group_id=group_id,
            passenger_submission_ids={by_staff_code[item.staff_code].id for item in matched},
            actor_user_id=current_user.id,
            change_kind="documents",
        )
        await AuditLogRepository(session).record(
            action="passport_documents_bulk_imported",
            entity_type="client_group",
            entity_id=str(group_id),
            agency_id=group.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={"saved_count": len(matched), "rejected_count": preview.rejected_count},
        )
        await session.flush()
        jobs = await _stage_ocr_for_complete_staff_bundles(
            submissions=list(
                {
                    by_staff_code[item.staff_code].id: by_staff_code[item.staff_code]
                    for item in matched
                }.values()
            ),
            session=session,
        )
        commit_attempted = True
        await session.commit()
    except Exception as exc:
        try:
            await session.rollback()
        finally:
            await reconcile_failed_passport_import(
                agency_id=group.agency_id,
                import_id=import_id,
                uploaded_keys=uploaded_keys,
                commit_attempted=commit_attempted,
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "The import result could not be confirmed. Refresh the group "
                "before retrying; saved documents have been preserved."
            ),
        ) from exc
    finally:
        workspace.close()
    await _delete_unreferenced_passport_image_keys_best_effort(
        session=session,
        storage=storage,
        keys=[*replaced_keys, *replaced_crop_keys],
        group_id=group_id,
    )
    # Publication is best effort; durable extraction intent committed with the
    # image references is recovered autonomously if this request disappears.
    for job in jobs:
        if job.processing_job_id:
            try:
                await PassportProcessingDispatcher().dispatch_async(
                    job_id=job.processing_job_id,
                    submission_id=job.id,
                    background_tasks=background_tasks,
                )
            except Exception as exc:
                logger.warning(
                    "passport_document_import_dispatch_deferred",
                    job_id=str(job.processing_job_id),
                    error_type=type(exc).__name__,
                )
    return PassportDocumentImportSaveResponse(**preview.model_dump(), saved_count=len(matched))


async def _stage_ocr_for_complete_staff_bundles(
    *,
    submissions: list[PassportSubmissionModel],
    session: AsyncSession,
) -> list[PassportSubmissionOutputDTO]:
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
        return []
    reextract = ReextractPassportSubmissionUseCase(
        passport_repo=PassportSubmissionRepository(session),
        processing_job_repo=PassportProcessingJobRepository(session),
    )
    return [await reextract.execute(submission_id) for submission_id in ocr_targets]


async def _queue_ocr_for_complete_staff_bundles(
    *,
    submissions: list[PassportSubmissionModel],
    session: AsyncSession,
    background_tasks: BackgroundTasks,
) -> None:
    """Compatibility helper for callers that own their import transaction."""
    jobs = await _stage_ocr_for_complete_staff_bundles(submissions=submissions, session=session)
    await session.commit()
    for job in jobs:
        if job.processing_job_id:
            await PassportProcessingDispatcher().dispatch_async(
                job_id=job.processing_job_id,
                submission_id=job.id,
                background_tasks=background_tasks,
            )
