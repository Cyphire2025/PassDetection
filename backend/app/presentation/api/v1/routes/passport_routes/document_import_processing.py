"""Durable AI processing intent and caller-owned import publication."""

from __future__ import annotations

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.passport_dtos import PassportSubmissionOutputDTO
from app.application.use_cases.passports.reextract_passport_submission_use_case import (
    ReextractPassportSubmissionUseCase,
)
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.processing.dispatcher import PassportProcessingDispatcher
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)


async def _stage_ocr_for_complete_staff_bundles(
    *,
    submissions: list[PassportSubmissionModel],
    session: AsyncSession,
) -> list[PassportSubmissionOutputDTO]:
    required_fields = (
        "passport_number",
        "surname",
        "given_names",
        "date_of_birth",
        "date_of_expiry",
    )
    ocr_targets = []
    for submission in submissions:
        fields = submission.confirmed_fields or submission.extracted_fields or {}
        has_all_images = (
            bool(submission.image_s3_key)
            and bool(getattr(submission, "passport_photo_s3_key", None))
            and bool(getattr(submission, "passport_back_s3_key", None))
        )
        if has_all_images and any(
            not str(fields.get(field, "")).strip() for field in required_fields
        ):
            ocr_targets.append(submission.id)
    if not ocr_targets:
        return []
    reextract = ReextractPassportSubmissionUseCase(
        passport_repo=PassportSubmissionRepository(session),
        processing_job_repo=PassportProcessingJobRepository(session),
    )
    return [await reextract.execute(submission_id) for submission_id in ocr_targets]


async def _queue_ocr_for_complete_staff_bundles(
    *,
    submissions: list[PassportSubmissionModel],
    session: AsyncSession,
    background_tasks: BackgroundTasks,
) -> None:
    """Compatibility helper for callers that own their import transaction."""
    jobs = await _stage_ocr_for_complete_staff_bundles(submissions=submissions, session=session)
    await session.commit()
    for job in jobs:
        if job.processing_job_id:
            await PassportProcessingDispatcher().dispatch_async(
                job_id=job.processing_job_id,
                submission_id=job.id,
                background_tasks=background_tasks,
            )


# Preserve established private helper import/pickle identities.
_stage_ocr_for_complete_staff_bundles.__module__ = (
    "app.presentation.api.v1.routes.passport_routes.document_import"
)
_queue_ocr_for_complete_staff_bundles.__module__ = (
    "app.presentation.api.v1.routes.passport_routes.document_import"
)
