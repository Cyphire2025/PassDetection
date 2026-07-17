"""Focused reliability tests for persisted passport extraction jobs."""

from __future__ import annotations

import asyncio
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.application.interfaces.passport_extraction import PassportExtractionResult
from app.application.interfaces.passport_verification import PassportVerificationResult
from app.application.use_cases.passports.process_passport_submission_job_use_case import (
    PUBLIC_EXTRACTION_FAILURE,
    ProcessingRetryRequested,
    ProcessPassportSubmissionJobUseCase,
)
from app.application.use_cases.passports.submit_passport_use_case import SubmitPassportUseCase
from app.domain.entities.entities import PassportSubmission
from app.domain.exceptions.exceptions import StorageError
from app.infrastructure.processing.job_state import ProcessingJobStatus


class PassportProcessingReliabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        settings_patcher = patch(
            "app.application.use_cases.passports."
            "process_passport_submission_job_use_case.get_settings",
            return_value=SimpleNamespace(
                processing_job_timeout_seconds=60,
                passport_local_extraction_timeout_seconds=0.02,
                gemini_timeout_seconds=30.0,
            ),
        )
        self.addCleanup(settings_patcher.stop)
        settings_patcher.start()
        self.submission_id = uuid.uuid4()
        self.job_id = uuid.uuid4()
        self.revision = 3
        self.job = SimpleNamespace(
            id=self.job_id,
            submission_id=self.submission_id,
            status=ProcessingJobStatus.RUNNING,
            attempts=1,
            max_attempts=3,
            extraction_revision=self.revision,
            cancel_requested=False,
        )
        self.submission = SimpleNamespace(
            id=self.submission_id,
            image_s3_key="drafts/agency/group/passport-front.jpg",
            passport_back_s3_key="drafts/agency/group/passport-back.jpg",
            extraction_revision=self.revision,
        )
        self.passport_repo = AsyncMock()
        self.storage_repo = AsyncMock()
        self.extraction_service = AsyncMock()
        self.job_repo = AsyncMock()
        self.job_repo.claim_running.return_value = (self.job, True)
        self.job_repo.get.return_value = self.job
        self.passport_repo.get_by_id.return_value = self.submission

    def _use_case(
        self,
        *,
        allow_retry: bool = True,
        verification_service=None,
    ) -> ProcessPassportSubmissionJobUseCase:
        return ProcessPassportSubmissionJobUseCase(
            passport_repo=self.passport_repo,
            storage_repo=self.storage_repo,
            extraction_service=self.extraction_service,
            job_repo=self.job_repo,
            allow_retry=allow_retry,
            verification_service=verification_service,
        )

    async def test_success_extracts_only_the_persisted_front_image(self) -> None:
        self.storage_repo.get_file.return_value = b"front-image"
        self.extraction_service.extract.return_value = PassportExtractionResult(
            extracted_fields={"passport_number": "P1234567"},
            overall_confidence=0.91,
            confidence_score={"overall": 0.91},
            mrz_raw="MRZ",
        )
        self.passport_repo.apply_extraction_result.return_value = self.submission

        await self._use_case().execute(
            submission_id=self.submission_id,
            job_id=self.job_id,
        )

        self.storage_repo.get_file.assert_awaited_once_with(
            "drafts/agency/group/passport-front.jpg"
        )
        self.extraction_service.extract.assert_awaited_once_with(
            b"front-image",
            filename="passport-front.jpg",
            content_type="image/jpeg",
        )
        self.passport_repo.apply_extraction_result.assert_awaited_once()
        self.job_repo.mark_succeeded.assert_awaited_once_with(self.job_id)

    async def test_initial_job_sends_stored_front_image_to_ai_verification(self) -> None:
        self.storage_repo.get_file.return_value = b"canonical-front-image"
        self.extraction_service.extract.return_value = PassportExtractionResult(
            extracted_fields={},
            overall_confidence=0.0,
            confidence_score={"overall": 0.0},
        )
        verification_service = AsyncMock()
        verification_service.verify.return_value = PassportVerificationResult(
            merged_fields={
                "surname": "KUMAR",
                "given_names": "NIPUN",
                "passport_number": "A1234567",
            },
            metadata={"status": "enhanced"},
        )
        self.passport_repo.apply_extraction_result.return_value = self.submission

        await self._use_case(
            verification_service=verification_service
        ).execute(
            submission_id=self.submission_id,
            job_id=self.job_id,
        )

        verification_service.verify.assert_awaited_once_with(
            b"canonical-front-image",
            content_type="image/jpeg",
            extracted_fields={},
            timeout_seconds=30.0,
        )
        saved = self.passport_repo.apply_extraction_result.await_args.kwargs
        self.assertEqual(saved["extracted_fields"]["passport_number"], "A1234567")
        self.job_repo.mark_succeeded.assert_awaited_once_with(self.job_id)

    async def test_duplicate_delivery_does_not_read_or_extract_the_image(self) -> None:
        self.job_repo.claim_running.return_value = (self.job, False)

        with self.assertRaises(ProcessingRetryRequested):
            await self._use_case().execute(
                submission_id=self.submission_id,
                job_id=self.job_id,
            )

        self.storage_repo.get_file.assert_not_awaited()
        self.extraction_service.extract.assert_not_awaited()
        self.passport_repo.apply_extraction_result.assert_not_awaited()

    async def test_local_timeout_never_retries_ocr_or_the_processing_job(self) -> None:
        self.storage_repo.get_file.return_value = b"canonical-front-image"

        async def slow_extract(*_args, **_kwargs) -> PassportExtractionResult:
            await asyncio.sleep(0.2)
            raise AssertionError("the bounded extraction should have been cancelled")

        self.extraction_service.extract.side_effect = slow_extract
        verification_service = AsyncMock()
        verification_service.verify.return_value = PassportVerificationResult(
            merged_fields={
                "processing_note": "Local OCR timed out; AI image verification was attempted.",
                "ai_verification": {"status": "unavailable"},
            },
            metadata={"status": "unavailable"},
        )
        self.passport_repo.apply_extraction_result.return_value = self.submission

        await self._use_case(
            verification_service=verification_service,
        ).execute(
            submission_id=self.submission_id,
            job_id=self.job_id,
        )

        self.assertEqual(self.extraction_service.extract.await_count, 1)
        self.job_repo.mark_retryable_failure.assert_not_awaited()
        self.passport_repo.apply_extraction_result.assert_awaited_once()
        self.job_repo.mark_succeeded.assert_awaited_once_with(self.job_id)

    async def test_stale_extraction_result_is_discarded(self) -> None:
        self.storage_repo.get_file.return_value = b"front-image"
        self.extraction_service.extract.return_value = PassportExtractionResult(
            extracted_fields={"surname": "STALE"},
            overall_confidence=0.8,
            confidence_score={"overall": 0.8},
        )
        self.passport_repo.apply_extraction_result.return_value = None

        await self._use_case().execute(
            submission_id=self.submission_id,
            job_id=self.job_id,
        )

        self.job_repo.mark_cancelled.assert_awaited_once_with(
            self.job_id,
            "Superseded by newer passport changes",
        )
        self.job_repo.mark_succeeded.assert_not_awaited()

    async def test_transient_failure_requests_a_bounded_retry(self) -> None:
        self.storage_repo.get_file.side_effect = StorageError("provider detail")

        with self.assertRaises(ProcessingRetryRequested):
            await self._use_case().execute(
                submission_id=self.submission_id,
                job_id=self.job_id,
            )

        self.job_repo.mark_retryable_failure.assert_awaited_once_with(
            self.job_id,
            "Automatic extraction will be retried",
        )
        self.passport_repo.apply_extraction_failure.assert_not_awaited()

    async def test_terminal_ocr_failure_keeps_submission_reviewable(self) -> None:
        self.storage_repo.get_file.side_effect = StorageError("provider detail")
        self.passport_repo.apply_extraction_failure.return_value = self.submission

        await self._use_case(allow_retry=False).execute(
            submission_id=self.submission_id,
            job_id=self.job_id,
        )

        self.passport_repo.apply_extraction_failure.assert_awaited_once_with(
            submission_id=self.submission_id,
            expected_revision=self.revision,
            public_message=PUBLIC_EXTRACTION_FAILURE,
        )
        self.job_repo.mark_dead_letter.assert_awaited_once_with(
            self.job_id,
            PUBLIC_EXTRACTION_FAILURE,
        )
        self.assertNotIn("provider detail", PUBLIC_EXTRACTION_FAILURE)


class PassportUploadIdempotencyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.group_id = uuid.uuid4()
        self.agency_id = uuid.uuid4()
        self.idempotency_key = "upload-duplicate-safe-key"
        self.group = SimpleNamespace(
            id=self.group_id,
            agency_id=self.agency_id,
            require_selfie=False,
            is_active=lambda: True,
            require_allowed_acquisition_mode=lambda value: value,
        )
        self.existing = PassportSubmission.create(
            group_id=self.group_id,
            agency_id=self.agency_id,
            client_name="Existing Traveller",
            client_email=None,
            image_s3_key="drafts/existing-front.jpg",
            acquisition_mode="camera",
            upload_idempotency_key=self.idempotency_key,
        )
        self.existing.promote_passport_back("drafts/existing-back.jpg")
        self.client_group_repo = AsyncMock()
        self.client_group_repo.get_by_token.return_value = self.group
        self.passport_repo = AsyncMock()
        self.storage_repo = AsyncMock()
        self.storage_repo.upload_file.side_effect = (
            lambda *, file_content, file_name, content_type: file_name
        )
        self.job_repo = AsyncMock()

    def _use_case(self) -> SubmitPassportUseCase:
        return SubmitPassportUseCase(
            client_group_repo=self.client_group_repo,
            passport_repo=self.passport_repo,
            storage_repo=self.storage_repo,
            processing_job_repo=self.job_repo,
        )

    async def test_known_idempotency_key_returns_without_reuploading(self) -> None:
        self.passport_repo.get_by_upload_idempotency_key.return_value = self.existing

        result = await self._use_case().execute(
            token="public-token",
            file_content=b"new-front",
            content_type="image/jpeg",
            filename="front.jpg",
            client_name="Existing Traveller",
            passport_back=(b"new-back", "image/jpeg", "back.jpg"),
            acquisition_mode="camera",
            upload_idempotency_key=self.idempotency_key,
        )

        self.assertEqual(result.id, self.existing.id)
        self.storage_repo.upload_file.assert_not_awaited()
        self.passport_repo.save_idempotent.assert_not_awaited()
        self.job_repo.create.assert_not_awaited()

    async def test_concurrent_idempotency_collision_cleans_only_losing_uploads(self) -> None:
        self.passport_repo.get_by_upload_idempotency_key.return_value = None
        self.passport_repo.save_idempotent.return_value = (self.existing, False)

        result = await self._use_case().execute(
            token="public-token",
            file_content=b"new-front",
            content_type="image/jpeg",
            filename="front.jpg",
            client_name="Existing Traveller",
            passport_back=(b"new-back", "image/jpeg", "back.jpg"),
            acquisition_mode="camera",
            upload_idempotency_key=self.idempotency_key,
        )

        self.assertEqual(result.id, self.existing.id)
        self.assertEqual(self.storage_repo.upload_file.await_count, 2)
        self.storage_repo.delete_files.assert_awaited_once()
        losing_keys = self.storage_repo.delete_files.await_args.args[0]
        self.assertEqual(len(losing_keys), 2)
        self.assertNotIn(self.existing.image_s3_key, losing_keys)
        self.assertNotIn(self.existing.passport_back_s3_key, losing_keys)
        self.job_repo.create.assert_not_awaited()

    async def test_failed_upload_compensates_every_intended_attempt_key(self) -> None:
        self.passport_repo.get_by_upload_idempotency_key.return_value = None

        async def ambiguous_upload(
            *,
            file_content: bytes,
            file_name: str,
            content_type: str,
        ) -> str:
            del content_type
            if file_content == b"new-back":
                raise StorageError("The write response timed out")
            return file_name

        self.storage_repo.upload_file.side_effect = ambiguous_upload

        with self.assertRaises(StorageError):
            await self._use_case().execute(
                token="public-token",
                file_content=b"new-front",
                content_type="image/jpeg",
                filename="front.jpg",
                client_name="New Traveller",
                passport_back=(b"new-back", "image/jpeg", "back.jpg"),
                acquisition_mode="camera",
                upload_idempotency_key="another-safe-upload-key",
            )

        self.storage_repo.delete_files.assert_awaited_once()
        attempted_keys = self.storage_repo.delete_files.await_args.args[0]
        self.assertEqual(len(attempted_keys), 2)
        self.assertTrue(any(key.endswith(".jpg") for key in attempted_keys))
        self.assertTrue(any(key.endswith("-back.jpg") for key in attempted_keys))
        self.passport_repo.save_idempotent.assert_not_awaited()

    async def test_persisted_idempotent_replay_survives_group_closure(self) -> None:
        self.group.is_active = lambda: False
        self.passport_repo.get_by_upload_idempotency_key.return_value = self.existing

        result = await self._use_case().execute(
            token="public-token",
            file_content=b"new-front",
            content_type="image/jpeg",
            filename="front.jpg",
            client_name="Existing Traveller",
            passport_back=(b"new-back", "image/jpeg", "back.jpg"),
            acquisition_mode="camera",
            upload_idempotency_key=self.idempotency_key,
        )

        self.assertEqual(result.id, self.existing.id)
        self.storage_repo.upload_file.assert_not_awaited()
        self.passport_repo.save_idempotent.assert_not_awaited()
        self.job_repo.create.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
