"""Submission persistence and idempotent insertion within the caller transaction."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging.logger import get_logger
from app.domain.entities.entities import PassportSubmission
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.repositories.passport_submission_mapping import _to_model
from app.infrastructure.repositories.passport_submission_reads import get_by_upload_idempotency_key

logger = get_logger("app.infrastructure.repositories.passport_submission_repository")


async def save(session: AsyncSession, submission: PassportSubmission) -> PassportSubmission:
    model = _to_model(submission)
    session.add(model)
    await session.flush()
    logger.info(
        "passport_submission_created",
        submission_id=str(submission.id),
        group_id=str(submission.group_id),
        agency_id=str(submission.agency_id),
    )
    return submission


async def save_idempotent(
    session: AsyncSession, submission: PassportSubmission
) -> tuple[PassportSubmission, bool]:
    if not submission.upload_idempotency_key:
        return await save(session, submission), True

    model = _to_model(submission)
    try:
        async with session.begin_nested():
            session.add(model)
            await session.flush()
    except IntegrityError:
        existing = await get_by_upload_idempotency_key(
            session,
            submission.group_id,
            submission.upload_idempotency_key,
        )
        if existing is None:
            raise
        logger.info(
            "passport_submission_idempotency_collision_resolved",
            submission_id=str(existing.id),
            group_id=str(existing.group_id),
        )
        return existing, False
    logger.info(
        "passport_submission_created",
        submission_id=str(submission.id),
        group_id=str(submission.group_id),
        agency_id=str(submission.agency_id),
    )
    return submission, True


async def update(session: AsyncSession, submission: PassportSubmission) -> PassportSubmission:
    result = await session.execute(
        select(PassportSubmissionModel).where(PassportSubmissionModel.id == submission.id)
    )
    model = result.scalar_one_or_none()
    if not model:
        raise EntityNotFoundError("PassportSubmission", str(submission.id))

    model.group_id = submission.group_id
    model.agency_id = submission.agency_id
    model.client_name = submission.client_name
    model.client_email = submission.client_email
    model.client_phone = submission.client_phone
    model.departure_city = submission.departure_city
    model.nearest_domestic_airport = submission.nearest_domestic_airport
    model.submission_mode = submission.submission_mode
    model.family_group_id = submission.family_group_id
    model.family_member_index = submission.family_member_index
    model.family_relation = submission.family_relation
    model.family_gender = submission.family_gender
    model.family_head_name = submission.family_head_name
    model.family_head_email = submission.family_head_email
    model.family_head_phone = submission.family_head_phone
    model.family_broadcast_to_member = submission.family_broadcast_to_member
    model.image_s3_key = submission.image_s3_key
    model.thumbnail_s3_key = submission.thumbnail_s3_key
    model.passport_photo_s3_key = submission.passport_photo_s3_key
    model.passport_cover_s3_key = submission.passport_cover_s3_key
    model.passport_back_cover_s3_key = submission.passport_back_cover_s3_key
    model.passport_back_s3_key = submission.passport_back_s3_key
    model.acquisition_mode = submission.acquisition_mode
    model.upload_idempotency_key = submission.upload_idempotency_key
    model.qualifier_enabled_snapshot = submission.qualifier_enabled_snapshot
    model.qualifier_selection_id = submission.qualifier_selection_id
    model.qualifier_is_self = submission.qualifier_is_self
    model.qualifier_relation_code = submission.qualifier_relation_code
    model.qualifier_relation_label = submission.qualifier_relation_label
    model.qualifier_selected_at = submission.qualifier_selected_at
    model.extraction_status = submission.extraction_status.value
    model.extraction_revision = submission.extraction_revision
    model.staff_metadata = submission.staff_metadata
    # Follow-up flags have a dedicated locked mutation. A stale extraction
    # or verification snapshot must never overwrite an office flag change.
    model.custom_answers = submission.custom_answers
    model.custom_detail_answers = submission.custom_detail_answers
    model.status = submission.status.value
    model.extracted_fields = submission.extracted_fields
    model.confirmed_fields = submission.confirmed_fields
    model.extraction_conflicts = submission.extraction_conflicts
    model.overall_confidence = submission.overall_confidence
    model.confidence_score = submission.confidence_score
    model.mrz_raw = submission.mrz_raw
    model.error_message = submission.error_message
    model.updated_at = submission.updated_at
    model.client_reviewed_at = submission.client_reviewed_at
    model.confirmed_at = submission.confirmed_at
    model.post_submission_verification = submission.post_submission_verification
    model.post_submission_verification_revision = submission.post_submission_verification_revision
    model.post_submission_verified_at = submission.post_submission_verified_at
    model.verification_reviewed_by_user_id = submission.verification_reviewed_by_user_id
    model.verification_reviewer_name = submission.verification_reviewer_name
    model.verification_reviewed_at = submission.verification_reviewed_at

    await session.flush()
    return submission


async def delete_submission(session: AsyncSession, submission_id: uuid.UUID) -> None:
    from app.application.travellers.retention import detach_submission_provenance

    await detach_submission_provenance(session, [submission_id])
    await session.execute(
        delete(PassportSubmissionModel).where(PassportSubmissionModel.id == submission_id)
    )
    await session.flush()
