"""Public passport discard: focused capability and workflow owner."""

from __future__ import annotations

import uuid

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.public_upload_capability import public_upload_is_active
from app.domain.entities.entities import (
    OFFICE_VISIBLE_PASSPORT_STATUS_VALUES,
    GroupStatus,
)
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.documents.storage_cleanup import (
    process_storage_cleanup_job,
    stage_storage_cleanup_jobs,
)
from app.infrastructure.observability.operational_events import (
    OperationalEvent,
    record_operational_event,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)

from .public_security import _require_public_upload_credential
from .public_upload_scope import logger

router = APIRouter()


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
    if group is None or not public_upload_is_active(group):
        raise HTTPException(status_code=404, detail="Passport draft was not found")
    locked_group = None
    if group is not None and public_upload_is_active(group):
        locked_group = await session.scalar(
            select(ClientGroupModel)
            .where(
                ClientGroupModel.id == group.id,
                ClientGroupModel.agency_id == group.agency_id,
                ClientGroupModel.status == GroupStatus.ACTIVE.value,
                ClientGroupModel.deleted_at.is_(None),
            )
            .with_for_update()
        )
    submission_repo = PassportSubmissionRepository(session)
    submission = await submission_repo.get_by_id_for_update(submission_id)
    if (
        group is None
        or locked_group is None
        or submission is None
        or submission.group_id != group.id
    ):
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
            submission.passport_cover_s3_key,
            submission.passport_back_cover_s3_key,
        )
        if key
    ]
    cleanup_jobs = stage_storage_cleanup_jobs(
        session,
        agency_id=locked_group.agency_id,
        source="passport_submission_delete",
        context_id=f"public-draft:{submission.id}",
        storage_keys=keys,
    )
    await submission_repo.delete(submission.id)
    await AuditLogRepository(session).record(
        action="public_passport_draft_discarded",
        entity_type="passport_submission",
        entity_id=str(submission.id),
        agency_id=locked_group.agency_id,
        metadata={
            "storage_cleanup_job_count": len(cleanup_jobs),
            "storage_objects_scheduled_for_cleanup": len(keys),
        },
    )
    # The encrypted cleanup tombstone and authoritative row deletion share
    # one commit. A failed/ambiguous commit therefore never triggers object
    # deletion, and a worker can safely retry after storage failures.
    await session.commit()
    for cleanup_job in cleanup_jobs:
        try:
            await process_storage_cleanup_job(cleanup_job.id)
        except Exception as exc:
            logger.warning(
                "discarded_passport_object_cleanup_deferred",
                submission_id=str(submission.id),
                cleanup_job_id=str(cleanup_job.id),
                object_count=cleanup_job.object_count,
                error_type=type(exc).__name__,
            )
    record_operational_event(
        OperationalEvent.PUBLIC_FLOW,
        "upload_abandoned",
    )
    return {"discarded": True}


discard_public_upload.__module__ = "app.presentation.api.v1.routes.passport_routes.public_upload"
