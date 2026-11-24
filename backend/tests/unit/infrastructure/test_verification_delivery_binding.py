"""Delivery arguments must agree with the durable verification job."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportPostSubmissionVerificationJobModel,
    PassportSubmissionModel,
)
from app.infrastructure.verification import runtime
from app.infrastructure.verification.job_repository import PostSubmissionVerificationJobRepository
from tests.persistence import persist_graph


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_status", ["queued", "failed"])
@pytest.mark.parametrize("mismatch", ["submission", "revision"])
async def test_mismatched_delivery_never_changes_passport_or_consumes_attempt(
    db_session,
    initial_status,
    mismatch,
) -> None:
    agency_id, group_id, submission_id, job_id = (uuid.uuid4() for _ in range(4))
    attempts = 0 if initial_status == "queued" else 3
    await persist_graph(
        db_session,
        [
            AgencyModel(id=agency_id, name="Synthetic", email="synthetic@example.invalid"),
            ClientGroupModel(
                id=group_id, agency_id=agency_id, name="Synthetic", token="synthetic-token"
            ),
            PassportSubmissionModel(
                id=submission_id,
                group_id=group_id,
                agency_id=agency_id,
                client_name="Synthetic",
                image_s3_key="synthetic.jpg",
            ),
            PassportPostSubmissionVerificationJobModel(
                id=job_id,
                submission_id=submission_id,
                verification_revision=2,
                status=initial_status,
                attempts=attempts,
                max_attempts=3,
            ),
        ],
    )
    await db_session.commit()

    @asynccontextmanager
    async def session_factory():
        yield db_session

    with (
        patch("app.infrastructure.database.session.AsyncSessionFactory", session_factory),
        patch.object(runtime, "VerifySubmittedPassportUseCase") as use_case,
        patch.object(runtime, "_persist_terminal_needs_review", AsyncMock()) as persist_terminal,
    ):
        await runtime._run_post_submission_verification_admitted(
            job_id=str(job_id),
            submission_id=str(uuid.uuid4() if mismatch == "submission" else submission_id),
            verification_revision=3 if mismatch == "revision" else 2,
        )
    use_case.assert_not_called()
    persist_terminal.assert_not_awaited()
    stored = (
        await db_session.execute(
            select(PassportPostSubmissionVerificationJobModel).where(
                PassportPostSubmissionVerificationJobModel.id == job_id,
            )
        )
    ).scalar_one()
    assert stored.status == initial_status
    assert stored.attempts == attempts
    submission = await db_session.get(PassportSubmissionModel, submission_id)
    assert submission is not None and submission.post_submission_verification is None
    if initial_status == "queued":
        job, claimed = await PostSubmissionVerificationJobRepository(db_session).claim_running(
            job_id
        )
        assert claimed and job is not None and job.attempts == 1
        assert job.submission_id == submission_id and job.verification_revision == 2
