"""Rerun extraction for a public upload without creating a new submission."""

from __future__ import annotations

import uuid

from app.application.dtos.passport_dtos import PassportSubmissionOutputDTO
from app.application.interfaces.passport_extraction import IPassportExtractionService
from app.domain.entities.entities import PassportProcessingStatus
from app.domain.exceptions.exceptions import EntityNotFoundError, ValidationError
from app.domain.repositories.interfaces import IClientGroupRepository, IObjectStorageRepository, IPassportSubmissionRepository


class RetryPublicPassportExtractionUseCase:
    """Refreshes automatic MRZ extraction on the stored passport image."""

    def __init__(
        self,
        *,
        passport_repo: IPassportSubmissionRepository,
        client_group_repo: IClientGroupRepository,
        storage_repo: IObjectStorageRepository,
        extraction_service: IPassportExtractionService,
    ) -> None:
        self._passport_repo = passport_repo
        self._client_group_repo = client_group_repo
        self._storage_repo = storage_repo
        self._extraction_service = extraction_service

    async def execute(self, *, token: str, submission_id: uuid.UUID) -> PassportSubmissionOutputDTO:
        group = await self._client_group_repo.get_by_token(token)
        if not group:
            raise EntityNotFoundError("ClientGroup", token)

        submission = await self._passport_repo.get_by_id(submission_id)
        if not submission or submission.group_id != group.id:
            raise EntityNotFoundError("PassportSubmission", submission_id)
        if submission.status == PassportProcessingStatus.CLIENT_SUBMITTED:
            raise ValidationError("Passport details were already submitted.", field="submission_id")

        image = await self._storage_repo.get_file(submission.image_s3_key)
        extraction = await self._extraction_service.extract(
            image,
            filename=submission.image_s3_key.rsplit("/", 1)[-1],
            content_type="image/jpeg",
        )

        merged_fields = self._merge_missing_fields(
            current=submission.extracted_fields or {},
            refreshed=extraction.extracted_fields,
        )
        submission.mark_review_required(
            extracted_fields=merged_fields,
            confidence=extraction.overall_confidence,
            confidence_score=extraction.confidence_score,
            mrz_raw=extraction.mrz_raw,
        )
        await self._passport_repo.update(submission)
        return self._to_dto(submission)

    @staticmethod
    def _merge_missing_fields(*, current: dict, refreshed: dict) -> dict:
        merged = dict(current)
        validation_keys = {
            "field_validation",
            "extraction_sources",
            "raw_mrz_ocr_text",
            "corrected_mrz_text",
            "field_provenance",
            "processing_note",
        }
        for key, value in refreshed.items():
            if key in validation_keys:
                merged[key] = value
            elif value and not merged.get(key):
                merged[key] = value
        return merged

    @staticmethod
    def _to_dto(submission) -> PassportSubmissionOutputDTO:  # type: ignore[no-untyped-def]
        return PassportSubmissionOutputDTO(
            id=submission.id,
            group_id=submission.group_id,
            agency_id=submission.agency_id,
            client_name=submission.client_name,
            client_email=submission.client_email,
            client_phone=submission.client_phone,
            image_s3_key=submission.image_s3_key,
            thumbnail_s3_key=submission.thumbnail_s3_key,
            status=submission.status.value,
            created_at=submission.created_at,
            updated_at=submission.updated_at,
            extracted_fields=submission.extracted_fields,
            confirmed_fields=submission.confirmed_fields,
            overall_confidence=submission.overall_confidence,
            confidence_score=submission.confidence_score,
            mrz_raw=submission.mrz_raw,
            error_message=submission.error_message,
            client_reviewed_at=submission.client_reviewed_at,
            confirmed_at=submission.confirmed_at,
        )
