"""Passport queries: focused workflow boundary."""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.passports.list_passport_group_summaries_use_case import (
    ListPassportGroupSummariesUseCase,
)
from app.application.use_cases.passports.list_passport_submissions_by_group_use_case import (
    ListPassportSubmissionsByGroupUseCase,
)
from app.application.use_cases.passports.list_passport_submissions_use_case import (
    ListPassportSubmissionsUseCase,
)
from app.application.use_cases.passports.submission_view import build_submission_view
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository,
)
from app.infrastructure.repositories.passport_submission_view_repository import (
    PassportSubmissionViewRepository,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportExpiryAlertResponse,
    PassportGroupSummaryResponse,
    PassportSubmissionResponse,
    PassportSubmissionSelectionSnapshotResponse,
    PassportSubmissionsViewResponse,
    PassportSubmissionViewItemResponse,
)
from app.presentation.dependencies.auth import get_current_active_user

from .constants import PASSPORT_BULK_SELECTION_MAX
from .dependencies import (
    _get_list_passport_groups_use_case,
    _get_list_passports_by_group_use_case,
    _get_list_passports_use_case,
)
from .response_support import _owner_scope_for, _staff_image_urls

router = APIRouter()


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
) -> PassportSubmissionsViewResponse:
    if not current_user.agency_id:
        return PassportSubmissionsViewResponse(
            items=[],
            ordered_submission_ids=[],
            ordered_selection_snapshot=[],
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

    # Preserve full-group duplicate identity semantics using a narrow projection.
    repository = PassportSubmissionViewRepository(session)
    all_submissions = await repository.projection(
        group_id=group_id, user=current_user, include_deleted=include_deleted
    )
    travel_date_stmt = select(ClientGroupModel.travel_date).where(ClientGroupModel.id == group_id)
    if not include_deleted:
        travel_date_stmt = travel_date_stmt.where(ClientGroupModel.deleted_at.is_(None))
    travel_date_stmt = AuthorizationPolicy.apply_group_visibility_scope(
        travel_date_stmt,
        current_user,
    )
    travel_date = (await session.execute(travel_date_stmt)).scalar_one_or_none()
    view = await asyncio.to_thread(
        build_submission_view,
        all_submissions,
        submission_filter=submission_filter,
        sort_by=sort_by,
        sort_order=sort_order,
        search=search,
        page=page,
        page_size=page_size,
        travel_date=travel_date,
    )
    submissions_by_id = {submission.id: submission for submission in all_submissions}
    details = await repository.page_details(
        submission_ids=[entry.submission.id for entry in view.items],
        group_id=group_id,
        user=current_user,
        include_deleted=include_deleted,
    )
    items: list[PassportSubmissionViewItemResponse] = []
    crop_rows = await PassportImageCropRepository(session).list_for_submissions(
        [entry.submission.id for entry in view.items]
    )
    for entry in view.items:
        detail = details.get(entry.submission.id)
        if (
            detail is None
            or detail.extraction_revision != entry.submission.extraction_revision
            or detail.updated_at != entry.submission.updated_at
        ):
            raise HTTPException(
                status_code=409,
                detail="The passport roster changed while loading. Refresh this page.",
            )
        base = PassportSubmissionResponse.model_validate(
            {
                **detail.__dict__,
                **_staff_image_urls(detail, crop_rows.get(entry.submission.id)),
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
    ordered_selection_ids = list(view.ordered_submission_ids[:PASSPORT_BULK_SELECTION_MAX])
    return PassportSubmissionsViewResponse(
        items=items,
        ordered_submission_ids=ordered_selection_ids,
        ordered_selection_snapshot=[
            PassportSubmissionSelectionSnapshotResponse(
                submission_id=submission_id,
                extraction_revision=submissions_by_id[submission_id].extraction_revision,
            )
            for submission_id in ordered_selection_ids
        ],
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
                date_of_expiry=date.fromisoformat(alert.date_of_expiry),
                status=cast(Literal["expired", "near_expiry"], alert.status),
            )
            for alert in view.expiry_alerts
        ],
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
