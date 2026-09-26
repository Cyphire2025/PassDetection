"""Bounded, duplicate-aware roster response serialization."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal, cast

from app.application.use_cases.passports.submission_view import SubmissionViewResult
from app.infrastructure.repositories.passport_submission_view_repository import (
    PassportViewProjection,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportDuplicateClusterPageResponse,
    PassportExpiryAlertResponse,
    PassportSubmissionSelectionSnapshotResponse,
    PassportSubmissionsViewResponse,
    PassportSubmissionViewItemResponse,
)

from .constants import PASSPORT_BULK_SELECTION_MAX


def build_view_response(
    view: SubmissionViewResult,
    items: list[PassportSubmissionViewItemResponse],
    submissions_by_id: dict[uuid.UUID, PassportViewProjection],
) -> PassportSubmissionsViewResponse:
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
        cluster_boundaries_preserved=view.cluster_boundaries_preserved,
        duplicate_clusters=[
            PassportDuplicateClusterPageResponse.model_validate(cluster)
            for cluster in view.duplicate_clusters
        ],
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
