"""Review owners keep real processing, audit, and retained-trip persistence."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select, update

from app.application.travellers import history_schedule
from app.application.use_cases.passports.get_passport_submission_use_case import (
    GetPassportSubmissionUseCase,
)
from app.application.use_cases.passports.reextract_passport_submission_use_case import (
    ReextractPassportSubmissionUseCase,
)
from app.infrastructure.database.models import AuditLogModel, PassportSubmissionModel
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.presentation.api.v1.routes.passport_routes import submission_review
from tests.passport_image_mutations import seed_image_mutation_context
from tests.route_dependencies import set_route_dependency
from tests.unit.application.test_traveller_snapshot_access import snapshot


@pytest.mark.asyncio
async def test_reextract_then_cancel_keeps_job_revision_and_audit(db_session, monkeypatch):
    context = await seed_image_mutation_context(db_session)
    submission_id = context.submission.id
    await db_session.execute(
        update(PassportSubmissionModel)
        .where(PassportSubmissionModel.id == submission_id)
        .values(status="failed")
    )
    await db_session.commit()
    repository = PassportSubmissionRepository(db_session)
    jobs = PassportProcessingJobRepository(db_session)
    dispatched = []

    async def dispatch(result, *, session, background_tasks):
        # The queue transport is synthetic; the submission and job are real.
        await session.commit()
        dispatched.append(result.processing_job_id)

    async def response(result, *, session):
        return result

    set_route_dependency(monkeypatch, submission_review, "_dispatch_processing_job", dispatch)
    set_route_dependency(monkeypatch, submission_review, "_response_from_dto", response)
    set_route_dependency(monkeypatch, submission_review, "_response_from_submission", response)
    result = await submission_review.reextract_passport(
        submission_id,
        BackgroundTasks(),
        current_user=context.actor,
        get_use_case=GetPassportSubmissionUseCase(repository),
        reextract_use_case=ReextractPassportSubmissionUseCase(repository, jobs),
        session=db_session,
    )
    job = await jobs.latest_for_submission(submission_id)
    assert job is not None and job.status.value == "queued"
    assert job.extraction_revision == result.extraction_revision == 1
    assert dispatched == [job.id]

    await submission_review.cancel_passport_processing(
        submission_id,
        current_user=context.actor,
        get_use_case=GetPassportSubmissionUseCase(repository),
        session=db_session,
    )
    await db_session.commit()
    cancelled = await jobs.latest_for_submission(submission_id)
    assert cancelled is not None and cancelled.id == job.id
    assert cancelled.status.value == "cancelled" and cancelled.cancel_requested
    audits = list(
        await db_session.scalars(
            select(AuditLogModel)
            .where(AuditLogModel.entity_id == str(submission_id))
            .order_by(AuditLogModel.integrity_sequence)
        )
    )
    assert [row.action for row in audits] == [
        "passport_reextract_queued",
        "passport_processing_cancel_requested",
    ]
    assert all(row.agency_id == context.actor.agency_id for row in audits)
    assert audits[-1].metadata_json == {"job_id": str(job.id)}


@pytest.mark.asyncio
async def test_cancel_without_job_keeps_not_found_contract(db_session):
    context = await seed_image_mutation_context(db_session)
    with pytest.raises(HTTPException) as error:
        await submission_review.cancel_passport_processing(
            context.submission.id,
            current_user=context.actor,
            get_use_case=GetPassportSubmissionUseCase(PassportSubmissionRepository(db_session)),
            session=db_session,
        )
    assert error.value.status_code == 404
    assert error.value.detail == "Processing job was not found"


@pytest.mark.asyncio
@pytest.mark.parametrize("retained", [False, True])
async def test_review_history_accepts_only_retained_trip_evidence(
    db_session, monkeypatch, retained
):
    _, enrolled, _, group, source, participation = await snapshot(db_session)
    source.status = "staff_approved"
    if not retained:
        source.image_s3_key = "fresh/ordinary.jpg"
    await db_session.flush()
    result = await GetPassportSubmissionUseCase(
        PassportSubmissionRepository(db_session)
    ).execute(source.id)
    schedule = AsyncMock()
    monkeypatch.setattr(history_schedule, "schedule_submission_history", schedule)

    await submission_review._schedule_review_history(
        db_session, result=result, trigger="staff_approved:synthetic"
    )
    await db_session.flush()
    schedule.assert_awaited_once_with(
        db_session,
        agency_id=group.agency_id,
        group_id=group.id,
        source_submission_id=source.id,
        expected_extraction_revision=source.extraction_revision,
        trigger="staff_approved:synthetic",
    )
    assert participation.status == ("accepted" if retained else "submitted")
    assert participation.revision == (2 if retained else 1)
    assert participation.document_revision_id == enrolled.document_revision_id
