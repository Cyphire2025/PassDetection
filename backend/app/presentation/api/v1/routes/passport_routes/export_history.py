"""Passport export history: focused workflow boundary."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.core.logging.logger import get_logger
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_export_history_repository import (
    PassportExportHistoryRepository,
    PassportExportKind,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportExportHistoryCompletionResponse,
    PassportExportHistoryDetailResponse,
    PassportExportHistoryItemResponse,
    PassportExportHistoryListResponse,
    PassportExportHistorySubmissionResponse,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

from .constants import (
    _validated_export_history_ids,
    _validated_export_history_people,
    _validated_export_kind,
    _validated_export_mode,
)
from .export_context import _current_group_export_submissions
from .response_support import _owner_scope_for

router = APIRouter()

logger = get_logger(__name__)


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
                export_kind=_validated_export_kind(item.export_kind),
                export_mode=_validated_export_mode(item.export_mode),
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
        total_pages=((total_count + page_size - 1) // page_size if total_count else 0),
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
        export_kind=_validated_export_kind(history.export_kind),
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
            export_kind=_validated_export_kind(history.export_kind),
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
                str(history.baseline_export_id) if history.baseline_export_id else None
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
        export_kind=_validated_export_kind(history.export_kind),
        status="completed",
        completed_at=completed_at,
    )
