"""Passport export context: focused workflow boundary."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging.logger import get_logger
from app.domain.entities.entities import PassportSubmission, User
from app.infrastructure.database.models import (
    PassportExportHistoryModel,
    PassportRosterResolutionModel,
)
from app.infrastructure.export.passport_image_zip_exporter import PassportImageZipExporter
from app.infrastructure.repositories.passport_export_history_repository import (
    PassportExportHistoryRepository,
    PassportExportKind,
    PassportExportMode,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)

from .constants import _validated_export_history_ids
from .response_support import _owner_scope_for

logger = get_logger(__name__)


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
        operational_only=True,
        created_by_user_id=_owner_scope_for(current_user),
        visible_to_user=current_user,
    )
    if len(submissions) > PassportImageZipExporter.MAX_SUBMISSIONS:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                "A single export is limited to "
                f"{PassportImageZipExporter.MAX_SUBMISSIONS} passengers."
            ),
        )
    return submissions


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
                "This download request was already prepared or completed. Start a new download."
            ),
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
