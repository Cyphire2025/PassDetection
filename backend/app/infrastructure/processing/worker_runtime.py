"""Shared runtime entrypoint for Celery and in-process background tasks."""

from __future__ import annotations

import asyncio
import uuid

from app.application.use_cases.passports.process_passport_submission_job_use_case import (
    ProcessingRetryRequested,
    ProcessPassportSubmissionJobUseCase,
)
from app.infrastructure.ai import GeminiPassportVerificationService
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.ocr.passport_extraction_service import PassportExtractionService
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository


async def run_passport_processing_job(*, job_id: str, submission_id: str, allow_retry: bool = True) -> None:
    async with AsyncSessionFactory() as session:
        try:
            use_case = ProcessPassportSubmissionJobUseCase(
                passport_repo=PassportSubmissionRepository(session),
                storage_repo=MinioStorageRepository(),
                extraction_service=PassportExtractionService(),
                job_repo=PassportProcessingJobRepository(session),
                verification_service=GeminiPassportVerificationService(),
                allow_retry=allow_retry,
            )
            await use_case.execute(
                submission_id=uuid.UUID(submission_id),
                job_id=uuid.UUID(job_id),
            )
            await session.commit()
        except ProcessingRetryRequested:
            await session.commit()
            raise
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def run_passport_processing_job_locally(*, job_id: str, submission_id: str) -> None:
    """Run bounded retries when no external queue is configured."""

    retry_number = 0
    while True:
        try:
            await run_passport_processing_job(
                job_id=job_id,
                submission_id=submission_id,
                allow_retry=True,
            )
            return
        except ProcessingRetryRequested:
            retry_number += 1
            await asyncio.sleep(min(15, 2 ** retry_number))
