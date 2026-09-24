from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks

from app.presentation.api.v1.routes.passport_routes import (
    submission_review,
    submission_side_effects,
)
from app.presentation.api.v1.routes.passports import client_submit_passport
from app.presentation.api.v1.schemas.passport_schemas import (
    ClientSubmitPassportRequest,
    PassportSubmissionResponse,
)


@pytest.fixture(autouse=True)
def isolate_ecr_staging(monkeypatch):
    monkeypatch.setattr(
        submission_side_effects, "stage_passport_ecr_check", AsyncMock(return_value=False)
    )


def _request() -> ClientSubmitPassportRequest:
    return ClientSubmitPassportRequest(
        confirmed_fields={"full_name": "Test Passenger"},
        group_token="public-group-token-1234567890",
        client_email="traveller@example.com",
        client_phone="9876543210",
        phone_verification_id=uuid.uuid4(),
    )


def _submitted_result(*, submission_id: uuid.UUID, agency_id: uuid.UUID, group_id: uuid.UUID):
    return SimpleNamespace(
        id=submission_id,
        agency_id=agency_id,
        group_id=group_id,
        image_s3_key="front/current.jpg",
        status="submitted",
        post_submission_verification=None,
        post_submission_verification_revision=3,
        idempotent_replay=True,
        storage_cleanup_keys=("front/superseded.jpg", "back/superseded.jpg"),
        promoted_storage_keys=(),
    )


@pytest.mark.parametrize("submission_status", ["submitted", "needs_review", "staff_approved"])
async def test_client_submit_commits_cleanup_tombstone_before_object_worker(
    submission_status,
) -> None:
    submission_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    credential = "private-upload-credential-1234567890"
    result = _submitted_result(
        submission_id=submission_id,
        agency_id=agency_id,
        group_id=group_id,
    )
    result.status = submission_status
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
    enqueue = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4(), status="completed"))
    with (
        patch(
            "app.presentation.api.v1.routes.passport_routes.submission_contact.require_public_contact_proof",
            new=AsyncMock(return_value=SimpleNamespace()),
        ),
        patch(
            "app.presentation.api.v1.routes.passport_routes.submission_contact.PassportSubmissionRepository",
            return_value=SimpleNamespace(
                get_by_id_for_update=AsyncMock(
                    return_value=SimpleNamespace(
                        id=submission_id,
                        upload_idempotency_key=credential,
                    )
                )
            ),
        ),
        patch(
            "app.presentation.api.v1.routes.passport_routes.submission_side_effects.PostSubmissionVerificationJobRepository",
            return_value=SimpleNamespace(
                enqueue=enqueue,
            ),
        ),
        patch(
            "app.presentation.api.v1.routes.passport_routes.submission_side_effects.stage_storage_cleanup_jobs",
            side_effect=stage,
        ) as stage_cleanup,
        patch(
            "app.presentation.api.v1.routes.passport_routes.submission_review.process_storage_cleanup_job",
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
    assert enqueue.await_count == (1 if submission_status == "submitted" else 0)


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
            "app.presentation.api.v1.routes.passport_routes.submission_contact.require_public_contact_proof",
            new=AsyncMock(return_value=SimpleNamespace()),
        ),
        patch(
            "app.presentation.api.v1.routes.passport_routes.submission_contact.PassportSubmissionRepository",
            return_value=SimpleNamespace(
                get_by_id_for_update=AsyncMock(
                    return_value=SimpleNamespace(
                        id=submission_id,
                        upload_idempotency_key=credential,
                    )
                )
            ),
        ),
        patch(
            "app.presentation.api.v1.routes.passport_routes.submission_side_effects.PostSubmissionVerificationJobRepository",
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
            "app.presentation.api.v1.routes.passport_routes.submission_side_effects.stage_storage_cleanup_jobs",
            return_value=(SimpleNamespace(id=uuid.uuid4(), object_count=2),),
        ),
        patch(
            "app.presentation.api.v1.routes.passport_routes.submission_review.process_storage_cleanup_job",
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


@pytest.mark.parametrize("failure", [None, "commit", "broker"])
async def test_ecr_stages_atomically_and_only_dispatches_after_commit(monkeypatch, failure):
    submission_id = uuid.uuid4()
    credential = "synthetic-upload-credential-1234567890"
    result = _submitted_result(
        submission_id=submission_id, agency_id=uuid.uuid4(), group_id=uuid.uuid4()
    )
    result.storage_cleanup_keys = ()
    events = []
    session = AsyncMock()

    async def stage(actual_session, actual_id):
        assert actual_session is session and actual_id == submission_id
        events.append("stage")
        return True

    async def commit():
        events.append("commit")
        if failure == "commit":
            raise RuntimeError("commit failed")

    async def dispatch():
        events.append("dispatch")
        if failure == "broker":
            raise RuntimeError("broker unavailable")

    session.commit.side_effect = commit
    monkeypatch.setattr(submission_side_effects, "stage_passport_ecr_check", stage)
    monkeypatch.setattr(submission_review, "dispatch_passport_ecr_checks", dispatch)
    monkeypatch.setattr(submission_review, "require_verified_submission_contact", AsyncMock())
    monkeypatch.setattr(
        submission_side_effects,
        "PostSubmissionVerificationJobRepository",
        lambda _: SimpleNamespace(
            enqueue=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4(), status="completed"))
        ),
    )
    expected = object()
    monkeypatch.setattr(PassportSubmissionResponse, "model_validate", lambda _: expected)
    call = client_submit_passport(
        submission_id=submission_id,
        body=_request(),
        background_tasks=BackgroundTasks(),
        upload_session_id=credential,
        use_case=SimpleNamespace(execute=AsyncMock(return_value=result)),
        session=session,
    )
    if failure == "commit":
        with pytest.raises(RuntimeError, match="commit failed"):
            await call
        assert events == ["stage", "commit"]
    else:
        assert await call is expected
        assert events == ["stage", "commit", "dispatch"]
