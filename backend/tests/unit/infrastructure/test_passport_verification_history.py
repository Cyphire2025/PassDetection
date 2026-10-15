"""AI completion durably refreshes history in the result's own transaction."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, update

from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerReconciliationJobModel as Job,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from tests.unit.application.test_traveller_enrollment import _fixture


@pytest.mark.asyncio
async def test_ai_completion_queues_and_reopens_same_source_history_job(db_session):
    ctx = await _fixture(db_session)
    ctx.source.status = "submitted"
    ctx.source.client_reviewed_at = datetime.now(UTC)
    ctx.source.post_submission_verification_revision = 1
    await db_session.flush()
    repository = PassportSubmissionRepository(db_session)

    result = await repository.apply_post_submission_verification(
        submission_id=ctx.source.id, expected_revision=1, decision="ai_approved", verification={})
    assert result is not None and result.status.value == "ai_approved"
    job = await db_session.scalar(select(Job))
    assert job is not None and job.status == "queued"
    assert job.idempotency_key == f"company-source:{ctx.source.id}:{ctx.source.extraction_revision}"
    assert (job.company_id, job.group_id) == (ctx.group.company_id, ctx.group.id)

    # Verification may finish after an earlier history pass has already ended.
    job.status, job.completed_at = "succeeded", datetime.now(UTC)
    ctx.source.status, ctx.source.post_submission_verification_revision = "submitted", 2
    await db_session.flush()
    assert await repository.apply_post_submission_verification(
        submission_id=ctx.source.id, expected_revision=2, decision="ai_approved", verification={})
    await db_session.flush()
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 1
    assert job.status == "queued" and job.completed_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("company_assigned,expected_revision", [(True, 0), (False, 1)])
async def test_stale_or_unassigned_ai_completion_does_not_schedule_history(
    db_session, company_assigned, expected_revision,
):
    ctx = await _fixture(db_session)
    ctx.source.status = "submitted"
    ctx.source.post_submission_verification_revision = 1
    if not company_assigned:
        ctx.group.company_id = None
    await db_session.flush()
    result = await PassportSubmissionRepository(db_session).apply_post_submission_verification(
        submission_id=ctx.source.id, expected_revision=expected_revision,
        decision="ai_approved", verification={})
    assert (result is None) == (expected_revision == 0)
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 0


@pytest.mark.asyncio
async def test_ai_completion_refreshes_cached_group_after_reassignment(db_session):
    ctx = await _fixture(db_session)
    ctx.source.status, ctx.source.post_submission_verification_revision = "submitted", 1
    await db_session.flush()
    # Simulate a row changed while provider work retained an earlier ORM object.
    await db_session.execute(update(ClientGroupModel).where(ClientGroupModel.id == ctx.group.id)
        .values(company_id=None).execution_options(synchronize_session=False))
    assert ctx.group.company_id is not None
    result = await PassportSubmissionRepository(db_session).apply_post_submission_verification(
        submission_id=ctx.source.id, expected_revision=1, decision="ai_approved", verification={})
    assert result is not None and ctx.group.company_id is None
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 0
