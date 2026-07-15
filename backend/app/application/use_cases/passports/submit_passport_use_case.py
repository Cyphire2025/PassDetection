"""
Submit Passport Use Case
========================
"""

from __future__ import annotations

import uuid
import mimetypes

from app.application.dtos.passport_dtos import PassportSubmissionOutputDTO
from app.application.interfaces.passport_extraction import IPassportExtractionService
from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.domain.entities.entities import PassportSubmission
from app.domain.exceptions.exceptions import (
    EntityNotFoundError,
    GroupClosedError,
    PassDetectionError,
)
from app.domain.repositories.interfaces import (
    IObjectStorageRepository,
    IPassportSubmissionRepository,
    IClientGroupRepository,
)
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository
from app.infrastructure.ocr.passport_back_extraction_service import PassportBackPageExtractionService

logger = get_logger(__name__)


class SubmitPassportUseCase:
    """Handles client passport image upload via secure link."""

    def __init__(
        self,
        client_group_repo: IClientGroupRepository,
        passport_repo: IPassportSubmissionRepository,
        storage_repo: IObjectStorageRepository,
        extraction_service: IPassportExtractionService | None = None,
        processing_job_repo: PassportProcessingJobRepository | None = None,
        back_extraction_service: PassportBackPageExtractionService | None = None,
    ) -> None:
        self._client_group_repo = client_group_repo
        self._passport_repo = passport_repo
        self._storage_repo = storage_repo
        self._extraction_service = extraction_service
        self._processing_job_repo = processing_job_repo
        self._back_extraction_service = back_extraction_service or PassportBackPageExtractionService()

    async def execute(
        self,
        token: str,
        file_content: bytes,
        content_type: str,
        filename: str,
        client_name: str,
        passport_photo: tuple[bytes, str, str] | None = None,
        passport_back: tuple[bytes, str, str] | None = None,
    ) -> PassportSubmissionOutputDTO:
        # 1. Validate the link
        group = await self._client_group_repo.get_by_token(token)
        if not group:
            raise EntityNotFoundError("ClientGroup", token)

        if not group.is_active():
            raise GroupClosedError()

        # 2. Upload image to Object Storage
        ext = mimetypes.guess_extension(content_type) or ".jpg"
        unique_id = uuid.uuid4()
        # Draft images are isolated from permanent passport storage until the
        # client explicitly submits the reviewed details.
        s3_key = f"drafts/{group.agency_id}/{group.id}/{unique_id}{ext}"
        
        await self._storage_repo.upload_file(
            file_content=file_content,
            file_name=s3_key,
            content_type=content_type,
        )

        # 3. Create PassportSubmission entity
        submission = PassportSubmission.create(
            group_id=group.id,
            agency_id=group.agency_id,
            client_name=client_name,
            client_email=None,
            image_s3_key=s3_key,
        )
        for document_type, upload in (("photo", passport_photo), ("back", passport_back)):
            if not upload:
                continue
            upload_content, upload_content_type, _upload_filename = upload
            upload_ext = mimetypes.guess_extension(upload_content_type) or ".jpg"
            upload_key = f"drafts/{group.agency_id}/{group.id}/{unique_id}-{document_type}{upload_ext}"
            await self._storage_repo.upload_file(
                file_content=upload_content,
                file_name=upload_key,
                content_type=upload_content_type,
            )
            if document_type == "photo":
                submission.promote_passport_photo(upload_key)
            else:
                submission.promote_passport_back(upload_key)

        # 4. Save submission and run the MRZ-only extraction inline. Public
        # uploads should not depend on Celery health for the review screen.
        await self._passport_repo.save(submission)

        submission.mark_processing()
        await self._passport_repo.update(submission)

        job = None
        if self._extraction_service is not None:
            try:
                extraction = await self._extraction_service.extract(
                    file_content,
                    filename=validated_filename(filename, s3_key),
                    content_type=content_type,
                )
                extracted_fields = dict(extraction.extracted_fields)
                if passport_back:
                    back_result = await self._back_extraction_service.extract(passport_back[0])
                    if back_result.fields.get("raw_text"):
                        extracted_fields["passport_back"] = back_result.fields
                submission.mark_review_required(
                    extracted_fields=extracted_fields,
                    confidence=extraction.overall_confidence,
                    confidence_score=extraction.confidence_score,
                    mrz_raw=extraction.mrz_raw,
                )
                await self._passport_repo.update(submission)
                logger.info(
                    "passport_public_upload_extracted_inline",
                    submission_id=str(submission.id),
                    group_id=str(group.id),
                    agency_id=str(group.agency_id),
                    confidence=extraction.overall_confidence,
                )
            except PassDetectionError as exc:
                submission.mark_failed(exc.message)
                await self._passport_repo.update(submission)
                logger.warning(
                    "passport_public_upload_inline_extraction_failed",
                    submission_id=str(submission.id),
                    error=exc.message,
                )
            except Exception as exc:
                submission.mark_failed("Automatic passport extraction failed")
                await self._passport_repo.update(submission)
                logger.exception(
                    "passport_public_upload_inline_extraction_unexpected_failed",
                    submission_id=str(submission.id),
                    error=str(exc),
                )
        elif self._processing_job_repo is not None:
            job = await self._processing_job_repo.create(
                submission_id=submission.id,
                max_attempts=get_settings().processing_job_max_attempts,
            )
            logger.info(
                "passport_processing_queued",
                submission_id=str(submission.id),
                job_id=str(job.id),
                group_id=str(group.id),
                agency_id=str(group.agency_id),
            )

        return PassportSubmissionOutputDTO(
            id=submission.id,
            group_id=submission.group_id,
            agency_id=submission.agency_id,
            client_name=submission.client_name,
            client_email=submission.client_email,
            client_phone=submission.client_phone,
            departure_city=submission.departure_city,
            submission_mode=submission.submission_mode,
            family_group_id=submission.family_group_id,
            family_member_index=submission.family_member_index,
            family_relation=submission.family_relation,
            family_gender=submission.family_gender,
            family_head_name=submission.family_head_name,
            family_head_email=submission.family_head_email,
            family_head_phone=submission.family_head_phone,
            family_broadcast_to_member=submission.family_broadcast_to_member,
            image_s3_key=submission.image_s3_key,
            thumbnail_s3_key=submission.thumbnail_s3_key,
            passport_photo_s3_key=submission.passport_photo_s3_key,
            passport_back_s3_key=submission.passport_back_s3_key,
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
            processing_job_id=job.id if job else None,
            processing_job_status=job.status.value if job else None,
            processing_progress=job.progress if job else None,
            processing_stage=job.current_stage if job else None,
        )


def validated_filename(filename: str, fallback_key: str) -> str:
    return filename or fallback_key.rsplit("/", 1)[-1]
