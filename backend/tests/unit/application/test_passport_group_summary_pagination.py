from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.application.use_cases.passports.list_passport_group_summaries_use_case import (
    ListPassportGroupSummariesUseCase,
)
from app.application.use_cases.passports.list_passport_submissions_by_group_use_case import (
    ListPassportSubmissionsByGroupUseCase,
)
from app.domain.repositories.interfaces import (
    PassportSubmissionGroupSummary,
    PassportSubmissionGroupSummaryPage,
)


def _summary(group_id: uuid.UUID) -> PassportSubmissionGroupSummary:
    return PassportSubmissionGroupSummary(
        group_id=group_id,
        group_name="Liberty Pride Classic Club",
        group_status="active",
        total_passports=30,
        pending_review_count=2,
        confirmed_count=28,
        failed_count=0,
        latest_submission_at=datetime(2026, 7, 31, 15, 10, tzinfo=UTC),
        destination="Phuket",
    )


@pytest.mark.asyncio
async def test_paginated_summary_forwards_filters_and_calculates_offset() -> None:
    agency_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    group_id = uuid.uuid4()
    visible_user = SimpleNamespace(id=owner_id)
    repository = SimpleNamespace(
        list_group_summaries_page_by_agency=AsyncMock(
            return_value=PassportSubmissionGroupSummaryPage(
                items=[_summary(group_id)],
                total=67,
            )
        )
    )

    result = await ListPassportGroupSummariesUseCase(repository).execute_page(
        agency_id,
        page=3,
        page_size=25,
        group_status="active",
        review_filter="needs_review",
        search="Liberty",
        destination="Phuket",
        created_by_user_id=owner_id,
        visible_to_user=visible_user,
    )

    assert result.total == 67
    assert result.page == 3
    assert result.page_size == 25
    assert [item.group_id for item in result.items] == [group_id]
    repository.list_group_summaries_page_by_agency.assert_awaited_once_with(
        agency_id,
        skip=50,
        limit=25,
        group_status="active",
        review_filter="needs_review",
        search="Liberty",
        destination="Phuket",
        exclude_archived_groups=True,
        created_by_user_id=owner_id,
        visible_to_user=visible_user,
    )


@pytest.mark.asyncio
async def test_single_summary_uses_the_authorized_repository_scope() -> None:
    agency_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    group_id = uuid.uuid4()
    visible_user = SimpleNamespace(id=owner_id)
    repository = SimpleNamespace(
        get_group_summary_by_agency=AsyncMock(return_value=_summary(group_id))
    )

    result = await ListPassportGroupSummariesUseCase(repository).execute_one(
        agency_id,
        group_id,
        created_by_user_id=owner_id,
        visible_to_user=visible_user,
    )

    assert result is not None
    assert result.group_id == group_id
    repository.get_group_summary_by_agency.assert_awaited_once_with(
        agency_id,
        group_id,
        exclude_archived_groups=True,
        created_by_user_id=owner_id,
        visible_to_user=visible_user,
    )


@pytest.mark.asyncio
async def test_single_archived_summary_requires_explicit_opt_in() -> None:
    agency_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    group_id = uuid.uuid4()
    visible_user = SimpleNamespace(id=owner_id)
    repository = SimpleNamespace(
        get_group_summary_by_agency=AsyncMock(return_value=_summary(group_id))
    )

    await ListPassportGroupSummariesUseCase(repository).execute_one(
        agency_id,
        group_id,
        include_archived=True,
        created_by_user_id=owner_id,
        visible_to_user=visible_user,
    )

    repository.get_group_summary_by_agency.assert_awaited_once_with(
        agency_id,
        group_id,
        exclude_archived_groups=False,
        created_by_user_id=owner_id,
        visible_to_user=visible_user,
    )


@pytest.mark.asyncio
async def test_archived_page_disables_only_the_archived_exclusion() -> None:
    agency_id = uuid.uuid4()
    repository = SimpleNamespace(
        list_group_summaries_page_by_agency=AsyncMock(
            return_value=PassportSubmissionGroupSummaryPage(items=[], total=0)
        )
    )

    await ListPassportGroupSummariesUseCase(repository).execute_page(
        agency_id,
        page=1,
        page_size=50,
        group_status="archived",
        include_archived=True,
    )

    call = repository.list_group_summaries_page_by_agency.await_args.kwargs
    assert call["group_status"] == "archived"
    assert call["exclude_archived_groups"] is False


@pytest.mark.asyncio
async def test_archived_group_submissions_keep_authorized_repository_scope() -> None:
    agency_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    group_id = uuid.uuid4()
    visible_user = SimpleNamespace(id=owner_id)
    repository = SimpleNamespace(list_by_group=AsyncMock(return_value=[]))

    await ListPassportSubmissionsByGroupUseCase(repository).execute(
        agency_id,
        group_id,
        include_archived_group=True,
        created_by_user_id=owner_id,
        visible_to_user=visible_user,
    )

    repository.list_by_group.assert_awaited_once_with(
        agency_id,
        group_id,
        skip=0,
        limit=100,
        search=None,
        exclude_archived_groups=False,
        include_archived_group=True,
        created_by_user_id=owner_id,
        visible_to_user=visible_user,
    )
