"""
Tests: Dashboard Use Cases
==========================
Unit tests for GetDashboardStatsUseCase.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.application.use_cases.dashboard.get_dashboard_stats_use_case import (
    GetDashboardStatsUseCase,
)
from app.domain.entities.entities import PassportProcessingStatus, PassportSubmission


def _make_submission(status: PassportProcessingStatus) -> PassportSubmission:
    return PassportSubmission(
        id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        client_name="John Doe",
        client_email="john@doe.com",
        client_phone=None,
        departure_city=None,
        submission_mode="single",
        family_group_id=None,
        family_member_index=None,
        family_relation=None,
        family_gender=None,
        family_head_name=None,
        family_head_email=None,
        family_head_phone=None,
        family_broadcast_to_member=False,
        image_s3_key="uploads/img.jpg",
        thumbnail_s3_key=None,
        passport_photo_s3_key=None,
        passport_back_s3_key=None,
        staff_metadata=None,
        status=status,
        extracted_fields=None,
        confirmed_fields=None,
        overall_confidence=0.92,
        confidence_score=None,
        mrz_raw=None,
        error_message=None,
        created_at=datetime.now(tz=timezone.utc),
        updated_at=datetime.now(tz=timezone.utc),
        client_reviewed_at=None,
        confirmed_at=None,
    )


class TestGetDashboardStatsUseCase:
    @pytest.mark.asyncio
    async def test_get_stats_success(self) -> None:
        sub_repo = AsyncMock()
        link_repo = AsyncMock()

        agency_id = uuid.uuid4()

        # Mock repository returns
        sub_repo.count_by_agency.side_effect = lambda aid, status_filter=None, **kwargs: {
            None: 10,
            PassportProcessingStatus.REVIEW_REQUIRED.value: 3,
            PassportProcessingStatus.CONFIRMED.value: 5,
        }.get(status_filter, 0)

        link_repo.count_active_by_agency.return_value = 2
        sub_repo.list_by_agency.return_value = [
            _make_submission(PassportProcessingStatus.REVIEW_REQUIRED),
            _make_submission(PassportProcessingStatus.CONFIRMED),
        ]

        use_case = GetDashboardStatsUseCase(sub_repo, link_repo)
        result = await use_case.execute(agency_id)

        assert result.total_passports == 10
        assert result.pending_review == 3
        assert result.confirmed == 5
        assert result.active_links == 2
        assert len(result.recent_submissions) == 2
        assert result.recent_submissions[0].client_name == "John Doe"

        sub_repo.count_by_agency.assert_any_call(
            agency_id,
            created_by_user_id=None,
            visible_to_user=None,
        )
        sub_repo.count_by_agency.assert_any_call(
            agency_id,
            status_filter=PassportProcessingStatus.REVIEW_REQUIRED.value,
            exclude_archived_groups=True,
            created_by_user_id=None,
            visible_to_user=None,
        )
        sub_repo.count_by_agency.assert_any_call(
            agency_id,
            status_filter=PassportProcessingStatus.CONFIRMED.value,
            exclude_archived_groups=True,
            created_by_user_id=None,
            visible_to_user=None,
        )
        link_repo.count_active_by_agency.assert_called_once_with(
            agency_id,
            created_by_user_id=None,
            visible_to_user=None,
        )
        sub_repo.list_by_agency.assert_called_once_with(
            agency_id,
            skip=0,
            limit=5,
            status_filter=PassportProcessingStatus.CLIENT_SUBMITTED.value,
            exclude_archived_groups=True,
            created_by_user_id=None,
            visible_to_user=None,
        )
