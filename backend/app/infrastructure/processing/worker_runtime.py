"""Shared runtime entrypoint for Celery and in-process background tasks."""

from __future__ import annotations

import asyncio
import uuid

from app.application.use_cases.passports.process_passport_submission_job_use_case import (
    ProcessingJobBusy,
    ProcessingRetryRequested,
    ProcessPassportSubmissionJobUseCase,
)
from app.infrastructure.ai_priority import (
    AiPriorityAdmissionDeferred,
    AiPriorityCoordinator,
    MaintainPriorityLease,
    get_ai_priority_coordinator,
)


async def run_passport_processing_job(
    *,
    job_id: str,
    submission_id: str,
    allow_retry: bool = True,
    priority_coordinator: AiPriorityCoordinator | None = None,
) -> None:
    priority = priority_coordinator or get_ai_priority_coordinator()
    decision = await asyncio.to_thread(priority.try_start_extraction, job_id)
    if not decision.admitted:
        raise AiPriorityAdmissionDeferred(
            workload="extraction",
            reason=decision.reason,
            retry_after_ms=decision.retry_after_ms,
        )
    async with MaintainPriorityLease(priority, decision.lease):
        await _run_passport_processing_job_admitted(
            job_id=job_id,
            submission_id=submission_id,
            allow_retry=allow_retry,
        )


async def _run_passport_processing_job_admitted(
    *,
    job_id: str,
    submission_id: str,
    allow_retry: bool,
) -> None:
    from app.infrastructure.ai import GeminiPassportVerificationService
    from app.infrastructure.database.session import AsyncSessionFactory
    from app.infrastructure.ocr.passport_extraction_service import (
        PassportExtractionService,
    )
    from app.infrastructure.processing.job_repository import (
        PassportProcessingJobRepository,
    )
    from app.infrastructure.repositories.passport_submission_repository import (
        PassportSubmissionRepository,
    )
    from app.infrastructure.storage.minio_repository import (
        MinioStorageRepository,
    )

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
        except ProcessingJobBusy as exc:
            await asyncio.sleep(exc.retry_after_ms / 1_000)
        except AiPriorityAdmissionDeferred as exc:
            await asyncio.sleep(exc.retry_after_ms / 1_000)
