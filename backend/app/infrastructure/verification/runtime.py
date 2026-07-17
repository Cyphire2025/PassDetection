"""Shared post-submit verification runtime for Celery and local fallback."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.interfaces.post_submission_verification import (
    PostSubmissionVerificationResult,
)
from app.application.use_cases.passports.verify_submitted_passport_use_case import (
    VerifySubmittedPassportUseCase,
)
from app.core.logging.logger import get_logger
from app.infrastructure.ai.gemini_post_submission_verification_service import (
    GeminiPostSubmissionVerificationService,
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.qr.approved_passenger_qr_issuer import (
    ensure_approved_passenger_qr,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.infrastructure.verification.job_repository import (
    PostSubmissionVerificationJobRepository,
)

logger = get_logger(__name__)


class PostSubmissionVerificationRetryRequested(RuntimeError):
    pass


async def _persist_terminal_needs_review(
    *,
    session: AsyncSession,
    submission_id: uuid.UUID,
    verification_revision: int,
) -> None:
    fallback = PostSubmissionVerificationResult.fallback(
        provider_status="internal_error",
        reason_code="verification_job_failed",
    )
    applied = await PassportSubmissionRepository(
        session
    ).apply_post_submission_verification(
        submission_id=submission_id,
        expected_revision=verification_revision,
        decision=fallback.decision.value,
        verification=fallback.to_dict(),
    )
    if applied is None:
        return
    # Persist the conservative workflow state independently from audit
    # availability so the office UI cannot poll Submitted forever.
    await session.commit()
    try:
        await AuditLogRepository(session).record(
            action="passport_post_submission_verification_failed",
            entity_type="passport_submission",
            entity_id=str(applied.id),
            agency_id=applied.agency_id,
            metadata={
                "group_id": str(applied.group_id),
                "verification_status": "needs_review",
                "verification_revision": verification_revision,
                "reason_code": "verification_job_failed",
            },
        )
        await session.commit()
    except Exception as audit_exc:
        await session.rollback()
        logger.warning(
            "post_submission_verification_failure_audit_deferred",
            submission_id=str(applied.id),
            error_type=type(audit_exc).__name__,
        )


async def run_post_submission_verification(
    *,
    job_id: str,
    submission_id: str,
    verification_revision: int,
) -> None:
    job_uuid = uuid.UUID(job_id)
    submission_uuid = uuid.UUID(submission_id)
    async with AsyncSessionFactory() as session:
        job_repo = PostSubmissionVerificationJobRepository(session)
        job, claimed = await job_repo.claim_running(job_uuid)
        if job is None:
            await session.commit()
            return
        if not claimed:
            if job.status == "failed":
                await _persist_terminal_needs_review(
                    session=session,
                    submission_id=submission_uuid,
                    verification_revision=verification_revision,
                )
            else:
                await session.commit()
            return
        await session.commit()
        try:
            result = await VerifySubmittedPassportUseCase(
                passport_repo=PassportSubmissionRepository(session),
                storage_repo=MinioStorageRepository(),
                verification_service=GeminiPostSubmissionVerificationService(),
            ).execute(
                submission_id=submission_uuid,
                expected_revision=verification_revision,
            )
            if result is not None:
                verification = result.post_submission_verification or {}
                await AuditLogRepository(session).record(
                    action="passport_post_submission_verified",
                    entity_type="passport_submission",
                    entity_id=str(result.id),
                    agency_id=result.agency_id,
                    metadata={
                        "group_id": str(result.group_id),
                        "verification_status": result.status,
                        "provider_status": verification.get("provider_status"),
                        "incorrect_count": len(
                            verification.get("incorrect_fields") or []
                        ),
                        "suspicious_count": len(
                            verification.get("suspicious_fields") or []
                        ),
                        "verification_revision": verification_revision,
                    },
                )
                if result.status == "ai_approved":
                    try:
                        # QR delivery is an approved-passenger side effect, not
                        # evidence for the Gemini decision. Keep a transient QR
                        # failure from downgrading a valid AI approval; approved
                        # QR screens will idempotently retry creation on demand.
                        async with session.begin_nested():
                            await ensure_approved_passenger_qr(
                                session,
                                result.id,
                            )
                    except Exception as qr_exc:
                        logger.warning(
                            "ai_approved_passenger_qr_deferred",
                            submission_id=str(result.id),
                            error_type=type(qr_exc).__name__,
                        )
            await job_repo.mark_succeeded(job_uuid)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            job_repo = PostSubmissionVerificationJobRepository(session)
            await job_repo.mark_retryable(job_uuid, type(exc).__name__)
            refreshed = await job_repo.get(job_uuid)
            if refreshed and refreshed.status == "queued":
                await session.commit()
                raise PostSubmissionVerificationRetryRequested() from exc
            if refreshed and refreshed.status == "failed":
                await _persist_terminal_needs_review(
                    session=session,
                    submission_id=submission_uuid,
                    verification_revision=verification_revision,
                )
                return
            await session.commit()
            raise


async def run_post_submission_verification_locally(
    *,
    job_id: str,
    submission_id: str,
    verification_revision: int,
) -> None:
    while True:
        try:
            await run_post_submission_verification(
                job_id=job_id,
                submission_id=submission_id,
                verification_revision=verification_revision,
            )
            return
        except PostSubmissionVerificationRetryRequested:
            await asyncio.sleep(2)
