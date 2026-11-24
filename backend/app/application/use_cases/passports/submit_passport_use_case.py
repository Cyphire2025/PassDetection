"""Persist public passport images and enqueue extraction as separate stages."""

from __future__ import annotations

import asyncio
import mimetypes
import uuid
from functools import partial

from app.application.dtos.passport_dtos import (
    PassportSubmissionOutputDTO,
    passport_submission_output_from_entity,
)
from app.application.mobile.group_capacity import GroupPassengerCapacityGuard
from app.application.security.public_upload_capability import require_active_public_upload
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
    hash_qualifier_selection_token as hash_qualifier_selection_token,
)
from app.domain.value_objects.qualifier_relations import (
    require_enabled_qualifier_choice,
)
from app.domain.value_objects.upload_configuration import (
    configuration_for,
    validate_documents,
    validate_visa_photo_source,
)
from app.infrastructure.documents.storage_transfers import (
    finish_cleanup_despite_cancellation,
    run_bounded_storage_operations,
)
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository
from app.infrastructure.processing.job_state import ProcessingJobStatus

from .passport_upload_plan import prepare_passport_uploads
from .passport_upload_selection import require_qualifier_selection
from .passport_upload_submission import prepare_passport_submission

logger = get_logger(__name__)


class SubmitPassportUseCase:
    """Save every required image before scheduling best-effort AI extraction."""

    def __init__(
        self,
        client_group_repo: IClientGroupRepository,
        passport_repo: IPassportSubmissionRepository,
        storage_repo: IObjectStorageRepository,
        processing_job_repo: PassportProcessingJobRepository | None = None,
        qualifier_selection_repo: IQualifierSelectionRepository | None = None,
        group_capacity_guard: GroupPassengerCapacityGuard | None = None,
    ) -> None:
        self._client_group_repo = client_group_repo
        self._passport_repo = passport_repo
        self._storage_repo = storage_repo
        self._processing_job_repo = processing_job_repo
        self._qualifier_selection_repo = qualifier_selection_repo
        self._group_capacity_guard = group_capacity_guard

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
        passport_cover: tuple[bytes, str, str] | None = None,
        passport_back_cover: tuple[bytes, str, str] | None = None,
        visa_photo_source: str | None = None,
        upload_idempotency_key: str | None = None,
        qualifier_selection_token: str | None = None,
    ) -> PassportSubmissionOutputDTO:
        group = await self._client_group_repo.get_by_token(token)
        if not group:
            raise EntityNotFoundError("ClientGroup", token)

        require_active_public_upload(group)

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
        config = configuration_for(group)
        if getattr(group, "relation_with_qualifier_enabled", False) and (
            config.required("relation_with_qualifier") or qualifier_selection_token
        ):
            qualifier_selection, qualifier_replay = await self._require_qualifier_selection(
                group_id=group.id,
                selection_token=qualifier_selection_token,
                upload_idempotency_key=normalized_key,
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

        if qualifier_selection is not None:
            require_enabled_qualifier_choice(
                group,
                is_self=qualifier_selection.is_self,
                relation_code=qualifier_selection.relation_code,
            )

        if not group.is_active():
            raise GroupClosedError()

        acquisition_mode = acquisition_mode.strip().lower()
        if acquisition_mode not in {"camera", "file"}:
            raise ValidationError(
                "Select a valid passport collection method.", field="acquisition_mode"
            )
        validate_documents(
            group,
            pages={
                "front": file_content,
                "back": passport_back and passport_back[0],
                "cover": passport_cover and passport_cover[0],
                "back_cover": passport_back_cover and passport_back_cover[0],
            },
            mode=acquisition_mode,
            photo=passport_photo and passport_photo[0],
        )
        validate_visa_photo_source(group, photo=passport_photo, source=visa_photo_source)

        unique_id = uuid.uuid4()
        uploaded_keys: list[str] = []
        try:
            front_key, upload_specs = prepare_passport_uploads(
                group=group,
                unique_id=unique_id,
                file_content=file_content,
                content_type=content_type,
                passport_back=passport_back,
                passport_photo=passport_photo,
                passport_cover=passport_cover,
                passport_back_cover=passport_back_cover,
                draft_key=self._draft_key,
            )
            # All keys are unique to this attempt and deleting a missing object
            # is safe. Compensate every intended key because an S3 write may
            # have succeeded even when its response timed out.
            uploaded_keys = [upload_key for *_upload, upload_key in upload_specs]

            # The pages are independent objects. Persist them concurrently so
            # the public request has one bounded S3 timeout window rather than
            # multiplying that window by front/back/selfie.
            await run_bounded_storage_operations(
                [
                    partial(
                        self._storage_repo.upload_file,
                        file_content=upload_content,
                        file_name=upload_key,
                        content_type=upload_content_type,
                    )
                    for _document_type, upload_content, upload_content_type, upload_key in upload_specs
                ],
            )

            if self._group_capacity_guard is not None:
                # Lock only after object writes finish, so a slow storage call
                # never holds the shared group creation lane. Re-check the
                # idempotency key under that lock before consuming capacity.
                await self._group_capacity_guard.lock_group(
                    agency_id=group.agency_id,
                    group_id=group.id,
                )
                if normalized_key:
                    locked_existing = await self._passport_repo.get_by_upload_idempotency_key(
                        group.id,
                        normalized_key,
                    )
                    if locked_existing is not None:
                        if (
                            qualifier_selection is not None
                            and locked_existing.qualifier_selection_id != qualifier_selection.id
                        ):
                            raise ValidationError(
                                "This upload attempt belongs to a different qualifier selection.",
                                field="qualifier_selection_token",
                            )
                        await self._cleanup_uploads(uploaded_keys)
                        return await self._idempotent_replay_result(
                            locked_existing,
                            group,
                        )
                await self._group_capacity_guard.assert_available(
                    agency_id=group.agency_id,
                    group_id=group.id,
                    additional_passengers=1,
                )

            submission = prepare_passport_submission(
                group=group,
                client_name=client_name,
                front_key=front_key,
                acquisition_mode=acquisition_mode,
                normalized_key=normalized_key,
                qualifier_selection=qualifier_selection,
                upload_specs=upload_specs,
            )

            submission, created = await self._passport_repo.save_idempotent(submission)
            if not created:
                if (
                    qualifier_selection is not None
                    and submission.qualifier_selection_id != qualifier_selection.id
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
            if not front_key:
                # Photo-only or details-only collection is a durable review
                # draft. No passport OCR or classification job can run.
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
        except asyncio.CancelledError:
            await finish_cleanup_despite_cancellation(self._cleanup_uploads(uploaded_keys))
            raise
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
        return await require_qualifier_selection(
            group_id=group_id,
            selection_token=selection_token,
            upload_idempotency_key=upload_idempotency_key,
            selection_repo=self._qualifier_selection_repo,
            passport_repo=self._passport_repo,
        )

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
