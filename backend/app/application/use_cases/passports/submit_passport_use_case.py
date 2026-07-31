"""Persist public passport images and enqueue extraction as separate stages."""

from __future__ import annotations

import asyncio
import mimetypes
import uuid

from app.application.dtos.passport_dtos import (
    PassportSubmissionOutputDTO,
    passport_submission_output_from_entity,
)
from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.core.security.upload_session import is_valid_upload_credential
from app.domain.entities.entities import ClientGroup, PassportSubmission, QualifierSelection
from app.domain.exceptions.exceptions import (
    EntityNotFoundError,
    GroupClosedError,
    PassDetectionError,
    StorageError,
    ValidationError,
)
from app.domain.repositories.interfaces import (
    IClientGroupRepository,
    IObjectStorageRepository,
    IPassportSubmissionRepository,
    IQualifierSelectionRepository,
)
from app.domain.value_objects.qualifier_relations import (
    hash_qualifier_selection_token,
)
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository
from app.infrastructure.processing.job_state import ProcessingJobStatus

logger = get_logger(__name__)


class SubmitPassportUseCase:
    """Save every required image before scheduling best-effort OCR."""

    def __init__(
        self,
        client_group_repo: IClientGroupRepository,
        passport_repo: IPassportSubmissionRepository,
        storage_repo: IObjectStorageRepository,
        processing_job_repo: PassportProcessingJobRepository | None = None,
        qualifier_selection_repo: IQualifierSelectionRepository | None = None,
    ) -> None:
        self._client_group_repo = client_group_repo
        self._passport_repo = passport_repo
        self._storage_repo = storage_repo
        self._processing_job_repo = processing_job_repo
        self._qualifier_selection_repo = qualifier_selection_repo

    async def execute(
        self,
        token: str,
        file_content: bytes,
        content_type: str,
        filename: str,
        client_name: str,
        passport_photo: tuple[bytes, str, str] | None = None,
        passport_back: tuple[bytes, str, str] | None = None,
        *,
        acquisition_mode: str = "file",
        upload_idempotency_key: str | None = None,
        qualifier_selection_token: str | None = None,
    ) -> PassportSubmissionOutputDTO:
        group = await self._client_group_repo.get_by_token(
            token,
            for_update=True,
        )
        if not group:
            raise EntityNotFoundError("ClientGroup", token)

        normalized_key = upload_idempotency_key.strip() if upload_idempotency_key else None
        if normalized_key and not is_valid_upload_credential(normalized_key):
            raise ValidationError(
                "Upload recovery credential is invalid.",
                field="upload_idempotency_key",
            )
        existing = None
        if normalized_key:
            existing = await self._passport_repo.get_by_upload_idempotency_key(
                group.id,
                normalized_key,
            )

        qualifier_selection = None
        qualifier_replay = None
        if getattr(group, "relation_with_qualifier_enabled", False):
            qualifier_selection, qualifier_replay = (
                await self._require_qualifier_selection(
                    group_id=group.id,
                    selection_token=qualifier_selection_token,
                    upload_idempotency_key=normalized_key,
                )
            )

        if existing is not None:
            if (
                qualifier_selection is not None
                and existing.qualifier_selection_id != qualifier_selection.id
            ):
                raise ValidationError(
                    "This upload attempt belongs to a different qualifier selection.",
                    field="qualifier_selection_token",
                )
            return await self._idempotent_replay_result(existing, group)
        if qualifier_replay is not None:
            return await self._idempotent_replay_result(qualifier_replay, group)

        if not group.is_active():
            raise GroupClosedError()

        acquisition_mode = group.require_allowed_acquisition_mode(acquisition_mode)
        if not file_content:
            raise ValidationError("Passport front image is required.", field="file")
        if not passport_back or not passport_back[0]:
            raise ValidationError("Passport back image is required.", field="passport_back_file")
        if group.require_selfie and (not passport_photo or not passport_photo[0]):
            raise ValidationError(
                "Visa Photo is required for this upload link.",
                field="passport_photo_file",
            )

        unique_id = uuid.uuid4()
        uploaded_keys: list[str] = []
        try:
            front_key = self._draft_key(
                agency_id=group.agency_id,
                group_id=group.id,
                unique_id=unique_id,
                document_type=None,
                content_type=content_type,
            )
            upload_specs: list[tuple[str | None, bytes, str, str]] = [
                (None, file_content, content_type, front_key),
            ]
            for document_type, upload in (("back", passport_back), ("photo", passport_photo)):
                if not upload:
                    continue
                upload_content, upload_content_type, _upload_filename = upload
                upload_specs.append(
                    (
                        document_type,
                        upload_content,
                        upload_content_type,
                        self._draft_key(
                            agency_id=group.agency_id,
                            group_id=group.id,
                            unique_id=unique_id,
                            document_type=document_type,
                            content_type=upload_content_type,
                        ),
                    )
                )
            # All keys are unique to this attempt and deleting a missing object
            # is safe. Compensate every intended key because an S3 write may
            # have succeeded even when its response timed out.
            uploaded_keys = [upload_key for *_upload, upload_key in upload_specs]

            # The pages are independent objects. Persist them concurrently so
            # the public request has one bounded S3 timeout window rather than
            # multiplying that window by front/back/selfie.
            upload_results = await asyncio.gather(
                *[
                    self._storage_repo.upload_file(
                        file_content=upload_content,
                        file_name=upload_key,
                        content_type=upload_content_type,
                    )
                    for _document_type, upload_content, upload_content_type, upload_key
                    in upload_specs
                ],
                return_exceptions=True,
            )
            upload_error = next(
                (
                    result
                    for result in upload_results
                    if isinstance(result, BaseException)
                ),
                None,
            )
            if upload_error:
                raise upload_error

            submission = PassportSubmission.create(
                group_id=group.id,
                agency_id=group.agency_id,
                client_name=client_name,
                client_email=None,
                image_s3_key=front_key,
                acquisition_mode=acquisition_mode,
                upload_idempotency_key=normalized_key,
            )
            if qualifier_selection is not None:
                submission.attach_qualifier_selection(qualifier_selection)
            for stored_document_type, _content, _content_type, upload_key in upload_specs:
                if stored_document_type is None:
                    continue
                if stored_document_type == "photo":
                    submission.promote_passport_photo(upload_key)
                else:
                    # Back pages are persisted and displayed only. They are not
                    # passed to any field extraction service.
                    submission.promote_passport_back(upload_key)

            submission, created = await self._passport_repo.save_idempotent(submission)
            if not created:
                if (
                    qualifier_selection is not None
                    and submission.qualifier_selection_id
                    != qualifier_selection.id
                ):
                    raise ValidationError(
                        "This upload attempt belongs to a different qualifier selection.",
                        field="qualifier_selection_token",
                    )
                await self._cleanup_uploads(uploaded_keys)
                logger.info(
                    "passport_upload_concurrent_replay_resolved",
                    submission_id=str(submission.id),
                    group_id=str(group.id),
                    agency_id=str(group.agency_id),
                )
                return passport_submission_output_from_entity(submission)
            extraction_revision = submission.mark_processing()
            await self._passport_repo.update(submission)

            job = None
            if self._processing_job_repo is not None:
                job = await self._processing_job_repo.create(
                    submission_id=submission.id,
                    extraction_revision=extraction_revision,
                    max_attempts=get_settings().processing_job_max_attempts,
                )
                logger.info(
                    "passport_upload_persisted_and_extraction_queued",
                    submission_id=str(submission.id),
                    job_id=str(job.id),
                    group_id=str(group.id),
                    agency_id=str(group.agency_id),
                    acquisition_mode=acquisition_mode,
                )

            return passport_submission_output_from_entity(submission, job=job)
        except PassDetectionError:
            await self._cleanup_uploads(uploaded_keys)
            raise
        except Exception as exc:
            await self._cleanup_uploads(uploaded_keys)
            logger.error(
                "passport_upload_persistence_failed",
                group_id=str(group.id),
                agency_id=str(group.agency_id),
                error_type=type(exc).__name__,
            )
            raise StorageError(
                "Passport images could not be saved. Please try the upload again."
            ) from exc

    async def _require_qualifier_selection(
        self,
        *,
        group_id: uuid.UUID,
        selection_token: str | None,
        upload_idempotency_key: str | None,
    ) -> tuple[QualifierSelection, PassportSubmission | None]:
        if not selection_token:
            raise ValidationError(
                "Select Self or the passenger's relationship before uploading.",
                field="qualifier_selection_token",
            )
        if self._qualifier_selection_repo is None:
            raise ValidationError(
                "The qualifier selection could not be verified.",
                field="qualifier_selection_token",
            )
        selection = await self._qualifier_selection_repo.get_by_token_hash(
            group_id,
            hash_qualifier_selection_token(selection_token),
            for_update=True,
        )
        if selection is None:
            raise ValidationError(
                "The qualifier selection is invalid.",
                field="qualifier_selection_token",
            )
        if selection.group_id != group_id:
            raise ValidationError(
                "The qualifier selection does not belong to this upload link.",
                field="qualifier_selection_token",
            )
        associated_submission_id = (
            await self._qualifier_selection_repo.get_submission_id(selection.id)
        )
        if associated_submission_id is not None:
            associated = await self._passport_repo.get_by_id(
                associated_submission_id
            )
            if (
                associated is not None
                and associated.group_id == group_id
                and upload_idempotency_key
                and associated.upload_idempotency_key
                == upload_idempotency_key
            ):
                return selection, associated
            raise ValidationError(
                "This qualifier selection has already been used.",
                field="qualifier_selection_token",
            )
        if selection.is_expired():
            raise ValidationError(
                "This qualifier selection has expired. Please choose again.",
                field="qualifier_selection_token",
            )
        return selection, None

    async def _idempotent_replay_result(
        self,
        existing: PassportSubmission,
        group: ClientGroup,
    ) -> PassportSubmissionOutputDTO:
        queued_job = None
        if self._processing_job_repo is not None:
            active_job = await self._processing_job_repo.active_for_submission(
                existing.id,
                extraction_revision=existing.extraction_revision,
            )
            if active_job and active_job.status == ProcessingJobStatus.QUEUED:
                # A process may have stopped after the durable commit but
                # before dispatch. Re-delivery is safe because workers claim
                # durable jobs atomically.
                queued_job = active_job
        logger.info(
            "passport_upload_idempotent_replay",
            submission_id=str(existing.id),
            group_id=str(group.id),
            agency_id=str(group.agency_id),
        )
        return passport_submission_output_from_entity(
            existing,
            job=queued_job,
        )

    async def _cleanup_uploads(self, keys: list[str]) -> None:
        if not keys:
            return
        try:
            await self._storage_repo.delete_files(keys)
        except Exception as exc:
            logger.warning(
                "passport_upload_compensation_failed",
                object_count=len(keys),
                error_type=type(exc).__name__,
            )

    @staticmethod
    def _draft_key(
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        unique_id: uuid.UUID,
        document_type: str | None,
        content_type: str,
    ) -> str:
        extension = mimetypes.guess_extension(content_type) or ".jpg"
        suffix = f"-{document_type}" if document_type else ""
        return f"drafts/{agency_id}/{group_id}/{unique_id}{suffix}{extension}"
