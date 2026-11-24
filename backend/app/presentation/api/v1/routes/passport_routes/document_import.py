"""Passport document import: focused workflow boundary."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import propagate_mobile_passenger_change
from app.core.logging.logger import get_logger
from app.domain.entities.entities import User
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.imports.passport_document_importer import (
    PassportDocumentImportWorkspace,
)
from app.infrastructure.processing.dispatcher import PassportProcessingDispatcher
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportDocumentImportPreviewResponse,
    PassportDocumentImportSaveResponse,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

from .constants import _staff_code_for_submission
from .document_import_authority import (
    _authorized_passport_document_group as _authorized_passport_document_group,
)
from .document_import_authority import lock_document_import_authority
from .document_import_failure import compensate_failed_document_import
from .document_import_persistence import apply_staged_document_import
from .document_import_preview import _passport_document_preview as _passport_document_preview
from .document_import_preview import (
    _passport_document_upload_sources as _passport_document_upload_sources,
)
from .document_import_processing import (
    _queue_ocr_for_complete_staff_bundles as _queue_ocr_for_complete_staff_bundles,
)
from .document_import_processing import (
    _stage_ocr_for_complete_staff_bundles as _stage_ocr_for_complete_staff_bundles,
)
from .document_import_staging import (
    prepare_document_import_targets,
    stage_document_import_targets,
)
from .image_support import _delete_unreferenced_passport_image_keys_best_effort

router = APIRouter()
logger = get_logger(__name__)


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
    group = await _authorized_passport_document_group(group_id, current_user, session)
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
    await session.rollback()
    await lock_document_import_authority(session, current_user, group)
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
    except BaseException:
        workspace.close()
        raise
    if not matched:
        try:
            await session.rollback()
            await lock_document_import_authority(session, current_user, group)
            return PassportDocumentImportSaveResponse(**preview.model_dump(), saved_count=0)
        finally:
            workspace.close()

    try:
        result = await session.execute(
            select(PassportSubmissionModel)
            .where(PassportSubmissionModel.group_id == group_id)
            .execution_options(populate_existing=True)
        )
        by_staff_code = {
            code: submission
            for submission in result.scalars().all()
            if (code := _staff_code_for_submission(submission))
        }
        targets = prepare_document_import_targets(
            matched,
            by_staff_code,
            agency_id=group.agency_id,
            group_id=group_id,
        )
        # Release the read transaction; targets retain IDs and source keys for
        # the fresh scoped comparison after external image work.
        await session.rollback()
        storage = MinioStorageRepository()
    except BaseException:
        workspace.close()
        raise
    import_id = uuid.uuid4()
    commit_attempted = False
    uploaded_keys: list[str] = []
    try:
        await stage_document_import_targets(storage, targets, uploaded_keys)
        current_user = await lock_document_import_authority(session, current_user, group)
        applied = await apply_staged_document_import(
            session, targets, actor=current_user, group=group
        )
        await propagate_mobile_passenger_change(
            session,
            agency_id=group.agency_id,
            group_id=group_id,
            passenger_submission_ids={submission.id for submission in applied.submissions},
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
            submissions=list(applied.submissions),
            session=session,
        )
        commit_attempted = True
        await session.commit()
    except BaseException as exc:
        await compensate_failed_document_import(
            session,
            agency_id=group.agency_id,
            import_id=import_id,
            uploaded_keys=uploaded_keys,
            commit_attempted=commit_attempted,
            error=exc,
        )
    finally:
        workspace.close()
    await _delete_unreferenced_passport_image_keys_best_effort(
        session=session,
        storage=storage,
        keys=list(applied.replaced_keys),
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
