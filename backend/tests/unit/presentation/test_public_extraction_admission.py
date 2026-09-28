"""Public uploads reserve one waiting batch and retain usable manual drafts."""

from __future__ import annotations

import asyncio
import threading
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import BackgroundTasks

from app.application.dtos.passport_dtos import passport_submission_output_from_entity
from app.domain.entities.entities import PassportSubmission
from app.infrastructure.ai_priority.state import (
    AdmissionDecision,
    AdmissionStatus,
    AiWorkload,
    PriorityLease,
    QueueCounts,
)
from app.infrastructure.processing.job_state import ProcessingJobStatus
from app.presentation.api.v1.routes.passport_routes import public_processing_support as support


def decision(reason="reserved", *, admitted=True):
    return AdmissionDecision(
        status=AdmissionStatus.ADMITTED if admitted else AdmissionStatus.DEFERRED,
        reason=reason,
        lease=PriorityLease(AiWorkload.EXTRACTION, "synthetic-job", 1, 30_000),
        counts=QueueCounts(extraction_active=4, extraction_dispatching=4),
    )


@pytest.fixture
def admission_context(monkeypatch):
    submission = PassportSubmission.create(
        group_id=uuid.uuid4(), agency_id=uuid.uuid4(), client_name="Synthetic traveller",
        client_email=None, image_s3_key="drafts/synthetic-front.jpg",
    )
    submission.mark_processing()
    job = SimpleNamespace(
        id=uuid.uuid4(), status=ProcessingJobStatus.QUEUED,
        extraction_revision=submission.extraction_revision, progress=0.0,
        current_stage="queued",
    )
    original = passport_submission_output_from_entity(submission, job=job)
    job.status = ProcessingJobStatus.DEAD_LETTER
    job.current_stage = "extraction_busy"
    jobs = Mock(mark_busy_if_unstarted=AsyncMock(return_value=job), mark_cancelled=AsyncMock())

    async def apply_failure(**kwargs):
        submission.mark_extraction_failed(
            kwargs["public_message"], expected_revision=kwargs["expected_revision"],
            diagnostics=kwargs["diagnostics"],
        )
        return submission

    passports = Mock(apply_extraction_failure=AsyncMock(side_effect=apply_failure))
    priority = Mock(reserve_public_extraction=Mock(return_value=decision()), release_public_reservation=Mock(return_value=True))
    dispatch = AsyncMock()
    monkeypatch.setattr(support, "get_ai_priority_coordinator", lambda: priority)
    monkeypatch.setattr(support, "PassportProcessingJobRepository", lambda _: jobs)
    monkeypatch.setattr(support, "PassportSubmissionRepository", lambda _: passports)
    monkeypatch.setattr(support, "_dispatch_processing_job", dispatch)
    return SimpleNamespace(
        original=original, jobs=jobs, passports=passports, priority=priority,
        dispatch=dispatch, session=AsyncMock(), background=BackgroundTasks(),
    )


async def run(context):
    return await support.dispatch_public_extraction(
        context.original, session=context.session, background_tasks=context.background,
    )


async def test_admitted_upload_dispatches_existing_durable_job(admission_context):
    context = admission_context
    assert await run(context) is context.original
    context.dispatch.assert_awaited_once()
    context.jobs.mark_busy_if_unstarted.assert_not_awaited()


@pytest.mark.parametrize("reason", ["deferred_capacity", "admission_unavailable"])
async def test_full_batch_or_scheduler_outage_returns_saved_manual_draft(admission_context, reason):
    context = admission_context
    context.priority.reserve_public_extraction.return_value = decision(reason, admitted=False)
    result = await run(context)
    assert result.status == "ready_for_client_review"
    assert result.manual_review_submission_allowed is True
    assert result.processing_stage == "extraction_busy"
    assert result.image_s3_key == context.original.image_s3_key
    assert result.extracted_fields["ai_verification"]["extraction_revision"] == result.extraction_revision
    assert "Fill in the details manually" in result.error_message
    context.dispatch.assert_not_awaited()
    context.session.commit.assert_awaited_once()


async def test_slow_scheduler_returns_busy_before_scheduler_responds(admission_context, monkeypatch):
    context = admission_context
    unblock = threading.Event()
    released = threading.Event()
    context.priority.release_public_reservation.side_effect = lambda _: released.set() or True

    def reserve(_):
        unblock.wait(timeout=2)
        return decision()

    context.priority.reserve_public_extraction.side_effect = reserve
    monkeypatch.setattr(support, "PUBLIC_ADMISSION_TIMEOUT_SECONDS", 0.01)
    try:
        result = await asyncio.wait_for(run(context), timeout=0.5)
        assert result.manual_review_submission_allowed is True
        context.dispatch.assert_not_awaited()
    finally:
        unblock.set()
    assert await asyncio.to_thread(released.wait, 1)
    context.priority.release_public_reservation.assert_called_once()


async def test_cancelled_request_releases_late_reservation_without_a_response(admission_context):
    context = admission_context
    started = threading.Event()
    unblock = threading.Event()
    released = threading.Event()
    context.priority.release_public_reservation.side_effect = lambda _: released.set() or True

    def reserve(_):
        started.set()
        unblock.wait(timeout=2)
        return decision()

    context.priority.reserve_public_extraction.side_effect = reserve
    request = asyncio.create_task(run(context))
    assert await asyncio.to_thread(started.wait, 1)
    request.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await request
    finally:
        unblock.set()
    assert await asyncio.to_thread(released.wait, 1)
    context.priority.release_public_reservation.assert_called_once()
    context.jobs.mark_busy_if_unstarted.assert_not_awaited()


async def test_busy_does_not_cancel_worker_that_won_the_claim(admission_context):
    context = admission_context
    context.priority.reserve_public_extraction.return_value = decision("deferred_capacity", admitted=False)
    context.jobs.mark_busy_if_unstarted.return_value = None
    assert await run(context) is context.original
    context.passports.apply_extraction_failure.assert_not_awaited()
    context.dispatch.assert_awaited_once()


@pytest.mark.parametrize("reason,release_count", [("reserved", 1), ("existing_reservation", 0)])
async def test_commit_failure_releases_only_new_reservation(admission_context, reason, release_count):
    context = admission_context
    context.priority.reserve_public_extraction.return_value = decision(reason)
    context.dispatch.side_effect = RuntimeError("database commit failed")
    with pytest.raises(RuntimeError, match="commit failed"):
        await run(context)
    assert context.priority.release_public_reservation.call_count == release_count
