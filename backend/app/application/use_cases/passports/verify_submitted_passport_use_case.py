"""Durable worker use case for second-pass verification after client submit."""

from __future__ import annotations

import uuid
from pathlib import PurePosixPath

from app.application.dtos.passport_dtos import (
    PassportSubmissionOutputDTO,
    passport_submission_output_from_entity,
)
from app.application.interfaces.post_submission_verification import (
    IPostSubmissionPassportVerificationService,
    PostSubmissionVerificationResult,
)
from app.core.logging.logger import get_logger
from app.domain.entities.entities import PassportProcessingStatus
from app.domain.repositories.interfaces import (
    IObjectStorageRepository,
    IPassportSubmissionRepository,
)

logger = get_logger(__name__)


class VerifySubmittedPassportUseCase:
    def __init__(
        self,
        *,
        passport_repo: IPassportSubmissionRepository,
        storage_repo: IObjectStorageRepository,
        verification_service: IPostSubmissionPassportVerificationService,
    ) -> None:
        self._passport_repo = passport_repo
        self._storage_repo = storage_repo
        self._verification_service = verification_service

    async def execute(
        self,
        *,
        submission_id: uuid.UUID,
        expected_revision: int,
    ) -> PassportSubmissionOutputDTO | None:
        submission = await self._passport_repo.get_by_id(submission_id)
        if (
            submission is None
            or submission.status != PassportProcessingStatus.SUBMITTED
            or submission.post_submission_verification_revision != expected_revision
        ):
            return None

        submitted_fields = dict(submission.confirmed_fields or {})
        try:
            image_content = await self._storage_repo.get_file(submission.image_s3_key)
        except Exception as exc:
            logger.warning(
                "post_submission_verification_storage_fallback",
                submission_id=str(submission_id),
                error_type=type(exc).__name__,
            )
            verification = PostSubmissionVerificationResult.fallback(
                provider_status="storage_unavailable",
                reason_code="passport_image_unavailable",
                submitted_fields=submitted_fields,
            )
        else:
            try:
                verification = await self._verification_service.verify(
                    image_content,
                    content_type=self._content_type(submission.image_s3_key),
                    submitted_fields=submitted_fields,
                )
            except Exception as exc:
                logger.error(
                    "post_submission_verification_internal_fallback",
                    submission_id=str(submission_id),
                    error_type=type(exc).__name__,
                )
                verification = PostSubmissionVerificationResult.fallback(
                    provider_status="internal_error",
                    reason_code="verification_internal_error",
                    submitted_fields=submitted_fields,
                )

        applied = await self._passport_repo.apply_post_submission_verification(
            submission_id=submission_id,
            expected_revision=expected_revision,
            decision=verification.decision.value,
            verification=verification.to_dict(),
        )
        return passport_submission_output_from_entity(applied) if applied else None

    @staticmethod
    def _content_type(storage_key: str) -> str:
        suffix = PurePosixPath(storage_key).suffix.lower()
        return {
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(suffix, "image/jpeg")
