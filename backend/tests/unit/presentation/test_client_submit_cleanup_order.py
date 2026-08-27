from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks

from app.presentation.api.v1.routes.passports import client_submit_passport
from app.presentation.api.v1.schemas.passport_schemas import (
    ClientSubmitPassportRequest,
    PassportSubmissionResponse,
)


def _request() -> ClientSubmitPassportRequest:
    return ClientSubmitPassportRequest(
        confirmed_fields={"full_name": "Test Passenger"},
        group_token="public-group-token-1234567890",
    )


def _submitted_result(*, submission_id: uuid.UUID, agency_id: uuid.UUID, group_id: uuid.UUID):
    return SimpleNamespace(
        id=submission_id,
        agency_id=agency_id,
        group_id=group_id,
        post_submission_verification_revision=3,
        idempotent_replay=True,
        storage_cleanup_keys=("front/superseded.jpg", "back/superseded.jpg"),
        promoted_storage_keys=(),
    )


async def test_client_submit_commits_cleanup_tombstone_before_object_worker() -> None:
    submission_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    credential = "private-upload-credential-1234567890"
    result = _submitted_result(
        submission_id=submission_id,
        agency_id=agency_id,
        group_id=group_id,
    )
    events: list[str] = []
    session = AsyncMock()

    async def commit() -> None:
        events.append("commit")

    session.commit.side_effect = commit
    cleanup_job = SimpleNamespace(id=uuid.uuid4(), object_count=2)

    def stage(*_args: object, **_kwargs: object):
        events.append("cleanup-tombstone")
        return (cleanup_job,)

    async def process(_job_id: uuid.UUID) -> None:
        events.append("object-worker")

    expected_response = object()
    with (
        patch(
            "app.presentation.api.v1.routes.passports.PassportSubmissionRepository",
            return_value=SimpleNamespace(
                get_by_id=AsyncMock(
                    return_value=SimpleNamespace(
                        id=submission_id,
                        upload_idempotency_key=credential,
                    )
                )
            ),
        ),
        patch(
            "app.presentation.api.v1.routes.passports.PostSubmissionVerificationJobRepository",
            return_value=SimpleNamespace(
                enqueue=AsyncMock(
                    return_value=SimpleNamespace(
                        id=uuid.uuid4(),
                        status="completed",
                    )
                )
            ),
        ),
        patch(
            "app.presentation.api.v1.routes.passports.stage_storage_cleanup_jobs",
            side_effect=stage,
        ) as stage_cleanup,
        patch(
            "app.presentation.api.v1.routes.passports.process_storage_cleanup_job",
            new=process,
        ),
        patch.object(
            PassportSubmissionResponse,
            "model_validate",
            return_value=expected_response,
        ),
    ):
        response = await client_submit_passport(
            submission_id=submission_id,
            body=_request(),
            background_tasks=BackgroundTasks(),
            upload_session_id=credential,
            use_case=SimpleNamespace(execute=AsyncMock(return_value=result)),
            session=session,
        )

    assert response is expected_response
    assert events == ["cleanup-tombstone", "commit", "object-worker"]
    assert stage_cleanup.call_args.kwargs["storage_keys"] == result.storage_cleanup_keys


async def test_client_submit_commit_failure_never_runs_object_cleanup() -> None:
    submission_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    credential = "private-upload-credential-1234567890"
    result = _submitted_result(
        submission_id=submission_id,
        agency_id=agency_id,
        group_id=group_id,
    )
    session = AsyncMock()
    session.commit.side_effect = RuntimeError("injected commit failure")
    process = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.passports.PassportSubmissionRepository",
            return_value=SimpleNamespace(
                get_by_id=AsyncMock(
                    return_value=SimpleNamespace(
                        id=submission_id,
                        upload_idempotency_key=credential,
                    )
                )
            ),
        ),
        patch(
            "app.presentation.api.v1.routes.passports.PostSubmissionVerificationJobRepository",
            return_value=SimpleNamespace(
                enqueue=AsyncMock(
                    return_value=SimpleNamespace(
                        id=uuid.uuid4(),
                        status="completed",
                    )
                )
            ),
        ),
        patch(
            "app.presentation.api.v1.routes.passports.stage_storage_cleanup_jobs",
            return_value=(SimpleNamespace(id=uuid.uuid4(), object_count=2),),
        ),
        patch(
            "app.presentation.api.v1.routes.passports.process_storage_cleanup_job",
            new=process,
        ),
    ):
        with pytest.raises(RuntimeError, match="injected commit failure"):
            await client_submit_passport(
                submission_id=submission_id,
                body=_request(),
                background_tasks=BackgroundTasks(),
                upload_session_id=credential,
                use_case=SimpleNamespace(execute=AsyncMock(return_value=result)),
                session=session,
            )

    process.assert_not_awaited()
