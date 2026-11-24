"""Revision-guarded AI results, verification outbox and history publication."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import PassportSubmission
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.repositories.passport_submission_mapping import (
    _apply_extraction_fields,
    _to_entity,
)
from app.infrastructure.verification.job_repository import PostSubmissionVerificationJobRepository


async def apply_extraction_result(
    session: AsyncSession,
    *,
    submission_id: uuid.UUID,
    expected_revision: int,
    extracted_fields: dict[str, object],
    confidence: float,
    confidence_score: dict[str, object] | None,
    mrz_raw: str | None,
    review_threshold: float = 0.85,
) -> PassportSubmission | None:
    result = await session.execute(
        select(PassportSubmissionModel)
        .where(
            PassportSubmissionModel.id == submission_id,
            PassportSubmissionModel.extraction_revision == expected_revision,
        )
        .with_for_update()
    )
    model = result.scalar_one_or_none()
    if model is None:
        return None
    submission = _to_entity(model)
    previous_verification_revision = submission.post_submission_verification_revision
    if not submission.mark_review_required(
        extracted_fields=extracted_fields,
        confidence=confidence,
        confidence_score=confidence_score,
        mrz_raw=mrz_raw,
        expected_revision=expected_revision,
        review_threshold=review_threshold,
    ):
        return None
    _apply_extraction_fields(model, submission)
    if submission.post_submission_verification_revision != previous_verification_revision:
        # Persist the result and verification outbox together so a worker
        # restart cannot strand a re-extracted passport with an old verdict.
        model.post_submission_verification_revision = (
            submission.post_submission_verification_revision
        )
        model.post_submission_verification = submission.post_submission_verification
        model.post_submission_verified_at = submission.post_submission_verified_at
        await PostSubmissionVerificationJobRepository(session).enqueue(
            submission_id=submission.id,
            verification_revision=submission.post_submission_verification_revision,
        )
    await session.flush()
    return submission


async def apply_extraction_failure(
    session: AsyncSession,
    *,
    submission_id: uuid.UUID,
    expected_revision: int,
    public_message: str,
    diagnostics: dict[str, object] | None = None,
) -> PassportSubmission | None:
    result = await session.execute(
        select(PassportSubmissionModel)
        .where(
            PassportSubmissionModel.id == submission_id,
            PassportSubmissionModel.extraction_revision == expected_revision,
        )
        .with_for_update()
    )
    model = result.scalar_one_or_none()
    if model is None:
        return None
    submission = _to_entity(model)
    if not submission.mark_extraction_failed(
        public_message,
        expected_revision=expected_revision,
        diagnostics=diagnostics,
    ):
        return None
    _apply_extraction_fields(model, submission)
    await session.flush()
    return submission


async def apply_post_submission_verification(
    session: AsyncSession,
    *,
    submission_id: uuid.UUID,
    expected_revision: int,
    decision: str,
    verification: dict[str, object],
) -> PassportSubmission | None:
    from app.infrastructure.repositories.passport_verification_history import (
        lock_verification_history_scope,
    )

    await lock_verification_history_scope(session, submission_id)
    result = await session.execute(
        select(PassportSubmissionModel)
        .where(
            PassportSubmissionModel.id == submission_id,
            PassportSubmissionModel.post_submission_verification_revision == expected_revision,
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    model = result.scalar_one_or_none()
    if model is None:
        return None
    submission = _to_entity(model)
    if not submission.apply_post_submission_verification(
        expected_revision=expected_revision,
        decision=decision,
        verification=verification,
    ):
        return None
    model.status = submission.status.value
    model.post_submission_verification = submission.post_submission_verification
    model.post_submission_verified_at = submission.post_submission_verified_at
    model.error_message = submission.error_message
    model.updated_at = submission.updated_at
    await session.flush()
    from app.application.travellers.history_schedule import schedule_submission_history

    await schedule_submission_history(
        session,
        agency_id=model.agency_id,
        group_id=model.group_id,
        trigger="post-submission-verification",
        source_submission_id=model.id,
        expected_extraction_revision=model.extraction_revision,
    )
    return submission
