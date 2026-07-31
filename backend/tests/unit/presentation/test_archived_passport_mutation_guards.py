from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.application.use_cases.passports.client_submit_passport_use_case import (
    ClientSubmitPassportUseCase,
)
from app.application.use_cases.passports.retry_public_passport_extraction_use_case import (
    RetryPublicPassportExtractionUseCase,
)
from app.domain.exceptions.exceptions import EntityNotFoundError, ValidationError
from app.presentation.api.v1.routes import passports


@pytest.mark.parametrize("group_status", ["active", "closed"])
def test_route_mutation_guard_allows_only_current_group_statuses(
    group_status: str,
) -> None:
    group = SimpleNamespace(status=group_status, deleted_at=None)

    passports._require_mutable_passport_group(group)


@pytest.mark.parametrize(
    ("group_status", "deleted_at"),
    [
        ("archived", None),
        ("deleted", None),
        ("future_status", None),
        ("active", datetime.now(tz=UTC)),
        ("closed", datetime.now(tz=UTC)),
    ],
)
def test_route_mutation_guard_rejects_historical_or_unknown_groups(
    group_status: str,
    deleted_at: datetime | None,
) -> None:
    group = SimpleNamespace(status=group_status, deleted_at=deleted_at)

    with pytest.raises(HTTPException) as exc_info:
        passports._require_mutable_passport_group(group)

    assert exc_info.value.status_code == 409
    assert "read-only" in str(exc_info.value.detail)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("group_status", "deleted_at"),
    [
        ("archived", None),
        ("deleted", None),
        ("future_status", None),
        ("active", datetime.now(tz=UTC)),
    ],
)
async def test_client_submit_rejects_historical_groups_before_locking_submission(
    group_status: str,
    deleted_at: datetime | None,
) -> None:
    passport_repo = SimpleNamespace(get_by_id_for_update=AsyncMock())
    group_repo = SimpleNamespace(
        get_by_token=AsyncMock(
            return_value=SimpleNamespace(
                status=group_status,
                deleted_at=deleted_at,
            )
        )
    )
    use_case = ClientSubmitPassportUseCase(
        passport_repo=passport_repo,
        client_group_repo=group_repo,
        storage_repo=SimpleNamespace(),
    )

    with pytest.raises(ValidationError, match="read-only"):
        await use_case.execute(
            uuid.uuid4(),
            group_token="group-token",
            confirmed_fields={},
            client_email=None,
            client_phone=None,
        )

    passport_repo.get_by_id_for_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_public_retry_keeps_closed_groups_mutable() -> None:
    group_id = uuid.uuid4()
    passport_repo = SimpleNamespace(
        get_by_id_for_update=AsyncMock(return_value=None)
    )
    use_case = RetryPublicPassportExtractionUseCase(
        passport_repo=passport_repo,
        client_group_repo=SimpleNamespace(
            get_by_token=AsyncMock(
                return_value=SimpleNamespace(
                    id=group_id,
                    status="closed",
                    deleted_at=None,
                )
            )
        ),
        processing_job_repo=SimpleNamespace(),
    )
    submission_id = uuid.uuid4()

    with pytest.raises(EntityNotFoundError):
        await use_case.execute(
            token="group-token",
            submission_id=submission_id,
        )

    passport_repo.get_by_id_for_update.assert_awaited_once_with(submission_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("group_status", "deleted_at"),
    [
        ("archived", None),
        ("deleted", None),
        ("future_status", None),
        ("closed", datetime.now(tz=UTC)),
    ],
)
async def test_public_retry_rejects_historical_groups_before_locking_submission(
    group_status: str,
    deleted_at: datetime | None,
) -> None:
    passport_repo = SimpleNamespace(get_by_id_for_update=AsyncMock())
    use_case = RetryPublicPassportExtractionUseCase(
        passport_repo=passport_repo,
        client_group_repo=SimpleNamespace(
            get_by_token=AsyncMock(
                return_value=SimpleNamespace(
                    status=group_status,
                    deleted_at=deleted_at,
                )
            )
        ),
        processing_job_repo=SimpleNamespace(),
    )

    with pytest.raises(ValidationError, match="read-only"):
        await use_case.execute(
            token="group-token",
            submission_id=uuid.uuid4(),
        )

    passport_repo.get_by_id_for_update.assert_not_awaited()
