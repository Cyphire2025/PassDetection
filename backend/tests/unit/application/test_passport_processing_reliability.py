"""Focused reliability tests for persisted passport extraction jobs."""

from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.application.interfaces.passport_extraction import PassportExtractionResult
from app.application.interfaces.passport_verification import PassportVerificationResult
from app.application.mobile.group_capacity import GroupPassengerCapacityGuard
from app.application.use_cases.passports.process_passport_submission_job_use_case import (
    PUBLIC_DOCUMENT_VERIFICATION_UNAVAILABLE,
    PUBLIC_EXTRACTION_FAILURE,
    ProcessingJobBusy,
    ProcessingRetryRequested,
    ProcessPassportSubmissionJobUseCase,
)
from app.application.use_cases.passports.submit_passport_use_case import SubmitPassportUseCase
from app.domain.entities.entities import PassportSubmission
from app.domain.exceptions.exceptions import EntityNotFoundError, StorageError, ValidationError
from app.infrastructure.processing.job_state import ProcessingJobStatus


class _VerifiedPassthroughVerifier:
    async def verify(  # type: ignore[no-untyped-def]
        self,
        _image_content,
        *,
        content_type,
        extracted_fields,
        timeout_seconds=None,
    ) -> PassportVerificationResult:
        del content_type, timeout_seconds
        metadata = {"status": "verified", "available": True}
        merged = dict(extracted_fields)
        merged.setdefault("passport_number", "P1234567")
        merged["ai_verification"] = metadata
        return PassportVerificationResult(merged_fields=merged, metadata=metadata)


_DEFAULT_VERIFIER = _VerifiedPassthroughVerifier()


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
        verification_service=_DEFAULT_VERIFIER,
    ) -> ProcessPassportSubmissionJobUseCase:
        return ProcessPassportSubmissionJobUseCase(
            passport_repo=self.passport_repo,
            storage_repo=self.storage_repo,
            extraction_service=self.extraction_service,
            job_repo=self.job_repo,
            allow_retry=allow_retry,
            verification_service=verification_service,
        )

    async def test_success_uses_only_persisted_front_image_for_gemini(self) -> None:
        self.storage_repo.get_file.return_value = b"front-image"
        verification_service = AsyncMock()
        verification_service.verify.return_value = PassportVerificationResult(
            merged_fields={"passport_number": "P1234567"},
            metadata={
                "status": "enhanced",
                "available": True,
                "classification_confidence": 0.99,
                "field_confidences": {"passport_number": 0.91},
            },
        )
        self.passport_repo.apply_extraction_result.return_value = self.submission

        await self._use_case(verification_service=verification_service).execute(
            submission_id=self.submission_id,
            job_id=self.job_id,
        )

        self.storage_repo.get_file.assert_awaited_once_with(
            "drafts/agency/group/passport-front.jpg"
        )
        verification_service.verify.assert_awaited_once_with(
            b"front-image",
            content_type="image/jpeg",
            extracted_fields={},
            timeout_seconds=30.0,
        )
        self.extraction_service.extract.assert_not_awaited()
        saved = self.passport_repo.apply_extraction_result.await_args.kwargs
        self.assertEqual(saved["extracted_fields"]["passport_number"], "P1234567")
        self.assertEqual(saved["confidence"], 0.1011)
        self.assertIsNone(saved["mrz_raw"])
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
            metadata={
                "status": "enhanced",
                "available": True,
                "classification_confidence": 0.99,
                "field_confidences": {
                    "surname": 0.95,
                    "given_names": 0.96,
                    "passport_number": 0.97,
                },
            },
        )
        self.passport_repo.apply_extraction_result.return_value = self.submission

        await self._use_case(verification_service=verification_service).execute(
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
        self.assertEqual(saved["confidence"], 0.32)
        self.assertEqual(
            saved["confidence_score"]["pipeline"]["name"],
            "gemini_image_primary",
        )
        self.assertFalse(saved["confidence_score"]["pipeline"]["local_ocr_mrz_invoked"])
        self.extraction_service.extract.assert_not_awaited()
        self.job_repo.mark_succeeded.assert_awaited_once_with(self.job_id)

    def test_verified_absent_surname_counts_toward_gemini_field_coverage(
        self,
    ) -> None:
        fields = {
            "surname": "",
            "given_names": "MOHIT",
            "passport_number": "W6905713",
            "nationality": "IND",
            "place_of_issue": "CHENNAI",
            "date_of_birth": "1998-09-08",
            "date_of_issue": "2023-04-13",
            "date_of_expiry": "2033-04-12",
            "sex": "M",
            "ai_verification": {
                "absent_fields": ["surname"],
                "classification_confidence": 0.99,
                "field_confidences": {
                    field: 0.99
                    for field in (
                        "surname",
                        "given_names",
                        "passport_number",
                        "nationality",
                        "place_of_issue",
                        "date_of_birth",
                        "date_of_issue",
                        "date_of_expiry",
                        "sex",
                    )
                },
            },
        }

        result = ProcessPassportSubmissionJobUseCase._gemini_extraction_result(fields)

        self.assertEqual(result.overall_confidence, 0.99)
        self.assertEqual(result.confidence_score["field_coverage"], 1.0)
        self.assertEqual(
            result.confidence_score["field_confidences"]["surname"],
            0.99,
        )

    async def test_wrong_document_is_persisted_as_safe_recapture_failure(self) -> None:
        self.storage_repo.get_file.return_value = b"not-a-passport"
        self.extraction_service.extract.return_value = PassportExtractionResult(
            extracted_fields={},
            overall_confidence=0.0,
            confidence_score={"overall": 0.0},
        )
        verification_service = AsyncMock()
        classification = {
            "status": "wrong_document",
            "available": False,
            "model": "gemini-test",
            "document_class": "aadhaar",
            "page_type": "not_applicable",
            "image_quality": "acceptable",
            "classification_confidence": 0.99,
            "reason_code": "wrong_document",
        }
        verification_service.verify.return_value = PassportVerificationResult(
            merged_fields={"ai_verification": classification},
            metadata=classification,
        )
        self.passport_repo.apply_extraction_failure.return_value = self.submission

        await self._use_case(verification_service=verification_service).execute(
            submission_id=self.submission_id,
            job_id=self.job_id,
        )

        failure = self.passport_repo.apply_extraction_failure.await_args.kwargs
        self.assertEqual(failure["diagnostics"]["ai_verification"], classification)
        self.assertIn("aadhaar card", failure["public_message"].lower())
        self.assertIn("passport", failure["public_message"].lower())
        self.passport_repo.apply_extraction_result.assert_not_awaited()
        self.job_repo.mark_dead_letter.assert_awaited_once()
        self.job_repo.mark_succeeded.assert_not_awaited()

    async def test_lower_confidence_wrong_document_message_stays_generic(self) -> None:
        self.storage_repo.get_file.return_value = b"not-a-passport"
        self.extraction_service.extract.return_value = PassportExtractionResult(
            extracted_fields={},
            overall_confidence=0.0,
            confidence_score={"overall": 0.0},
        )
        verification_service = AsyncMock()
        classification = {
            "status": "wrong_document",
            "available": False,
            "document_class": "aadhaar",
            "classification_confidence": 0.85,
            "reason_code": "wrong_document",
        }
        verification_service.verify.return_value = PassportVerificationResult(
            merged_fields={"ai_verification": classification},
            metadata=classification,
        )
        self.passport_repo.apply_extraction_failure.return_value = self.submission

        await self._use_case(verification_service=verification_service).execute(
            submission_id=self.submission_id,
            job_id=self.job_id,
        )

        failure = self.passport_repo.apply_extraction_failure.await_args.kwargs
        self.assertNotIn("aadhaar", failure["public_message"].lower())
        self.assertIn("not a passport", failure["public_message"].lower())
        self.passport_repo.apply_extraction_result.assert_not_awaited()
        self.job_repo.mark_succeeded.assert_not_awaited()

    async def test_duplicate_delivery_does_not_read_or_extract_the_image(self) -> None:
        self.job_repo.claim_running.return_value = (self.job, False)

        with self.assertRaises(ProcessingJobBusy):
            await self._use_case().execute(
                submission_id=self.submission_id,
                job_id=self.job_id,
            )

        self.storage_repo.get_file.assert_not_awaited()
        self.extraction_service.extract.assert_not_awaited()
        self.passport_repo.apply_extraction_result.assert_not_awaited()
        self.job_repo.mark_retryable_failure.assert_not_awaited()

    async def test_crash_delivery_recovers_after_running_claim_expires(
        self,
    ) -> None:
        recovered_job = SimpleNamespace(
            **{
                **vars(self.job),
                "attempts": 2,
            }
        )
        self.job_repo.claim_running.side_effect = [
            (self.job, False),
            (recovered_job, True),
        ]
        self.storage_repo.get_file.return_value = b"front-image"
        self.extraction_service.extract.return_value = PassportExtractionResult(
            extracted_fields={"passport_number": "P1234567"},
            overall_confidence=0.91,
            confidence_score={"overall": 0.91},
            mrz_raw="MRZ",
        )
        self.passport_repo.apply_extraction_result.return_value = self.submission

        with self.assertRaises(ProcessingJobBusy):
            await self._use_case().execute(
                submission_id=self.submission_id,
                job_id=self.job_id,
            )
        await self._use_case().execute(
            submission_id=self.submission_id,
            job_id=self.job_id,
        )

        self.assertEqual(self.job.attempts, 1)
        self.extraction_service.extract.assert_not_awaited()
        self.job_repo.mark_succeeded.assert_awaited_once_with(self.job_id)
        self.job_repo.mark_retryable_failure.assert_not_awaited()

    async def test_dormant_local_extractor_is_not_called_when_gemini_fails(self) -> None:
        self.storage_repo.get_file.return_value = b"canonical-front-image"

        self.extraction_service.extract.side_effect = AssertionError(
            "local OCR/MRZ must remain dormant"
        )
        verification_service = AsyncMock()
        verification_service.verify.return_value = PassportVerificationResult(
            merged_fields={
                "ai_verification": {"status": "unavailable"},
            },
            metadata={"status": "unavailable"},
        )
        self.passport_repo.apply_extraction_failure.return_value = self.submission

        await self._use_case(
            verification_service=verification_service,
        ).execute(
            submission_id=self.submission_id,
            job_id=self.job_id,
        )

        self.extraction_service.extract.assert_not_awaited()
        self.job_repo.mark_retryable_failure.assert_not_awaited()
        self.passport_repo.apply_extraction_result.assert_not_awaited()
        self.passport_repo.apply_extraction_failure.assert_awaited_once()
        failure = self.passport_repo.apply_extraction_failure.await_args.kwargs
        self.assertEqual(
            failure["public_message"],
            PUBLIC_DOCUMENT_VERIFICATION_UNAVAILABLE,
        )
        self.job_repo.mark_dead_letter.assert_awaited_once_with(
            self.job_id,
            PUBLIC_DOCUMENT_VERIFICATION_UNAVAILABLE,
        )
        self.job_repo.mark_succeeded.assert_not_awaited()

    async def test_empty_verified_result_is_persisted_as_extraction_failure(
        self,
    ) -> None:
        self.storage_repo.get_file.return_value = b"canonical-front-image"
        verification_service = AsyncMock()
        classification = {
            "status": "verified",
            "available": True,
            "model": "gemini-fallback",
            "attempts": 2,
        }
        verification_service.verify.return_value = PassportVerificationResult(
            merged_fields={"ai_verification": classification},
            metadata=classification,
        )
        self.passport_repo.apply_extraction_failure.return_value = self.submission

        await self._use_case(verification_service=verification_service).execute(
            submission_id=self.submission_id,
            job_id=self.job_id,
        )

        self.extraction_service.extract.assert_not_awaited()
        self.passport_repo.apply_extraction_result.assert_not_awaited()
        self.passport_repo.apply_extraction_failure.assert_awaited_once_with(
            submission_id=self.submission_id,
            expected_revision=self.revision,
            public_message=PUBLIC_EXTRACTION_FAILURE,
            diagnostics={"ai_verification": classification},
        )
        self.job_repo.mark_dead_letter.assert_awaited_once_with(
            self.job_id,
            PUBLIC_EXTRACTION_FAILURE,
        )
        self.job_repo.mark_succeeded.assert_not_awaited()

    async def test_all_unavailable_classification_statuses_fail_closed(self) -> None:
        unavailable_statuses = (
            "disabled",
            "not_configured",
            "deadline_exhausted",
            "timeout",
            "provider_unavailable",
            "invalid_response",
            "internal_error",
        )
        for status in unavailable_statuses:
            with self.subTest(status=status):
                self.passport_repo.reset_mock()
                self.storage_repo.reset_mock()
                self.extraction_service.reset_mock()
                self.job_repo.reset_mock()
                self.job_repo.claim_running.return_value = (self.job, True)
                self.job_repo.get.return_value = self.job
                self.passport_repo.get_by_id.return_value = self.submission
                self.passport_repo.apply_extraction_failure.return_value = self.submission
                self.storage_repo.get_file.return_value = b"unclassified-image"
                self.extraction_service.extract.return_value = PassportExtractionResult(
                    extracted_fields={"passport_number": "LOCAL123"},
                    overall_confidence=0.92,
                    confidence_score={"overall": 0.92},
                )
                verification_service = AsyncMock()
                classification = {"status": status, "available": False}
                verification_service.verify.return_value = PassportVerificationResult(
                    merged_fields={
                        "passport_number": "LOCAL123",
                        "ai_verification": classification,
                    },
                    metadata=classification,
                )

                await self._use_case(verification_service=verification_service).execute(
                    submission_id=self.submission_id,
                    job_id=self.job_id,
                )

                self.passport_repo.apply_extraction_result.assert_not_awaited()
                failure = self.passport_repo.apply_extraction_failure.await_args.kwargs
                self.assertEqual(
                    failure["public_message"],
                    PUBLIC_DOCUMENT_VERIFICATION_UNAVAILABLE,
                )
                self.assertEqual(
                    failure["diagnostics"]["ai_verification"]["status"],
                    status,
                )
                self.job_repo.mark_dead_letter.assert_awaited_once_with(
                    self.job_id,
                    PUBLIC_DOCUMENT_VERIFICATION_UNAVAILABLE,
                )
                self.job_repo.mark_succeeded.assert_not_awaited()

    async def test_missing_verifier_fails_closed(self) -> None:
        self.storage_repo.get_file.return_value = b"unclassified-image"
        self.extraction_service.extract.return_value = PassportExtractionResult(
            extracted_fields={"passport_number": "LOCAL123"},
            overall_confidence=0.92,
            confidence_score={"overall": 0.92},
        )
        self.passport_repo.apply_extraction_failure.return_value = self.submission

        await self._use_case(verification_service=None).execute(
            submission_id=self.submission_id,
            job_id=self.job_id,
        )

        self.passport_repo.apply_extraction_result.assert_not_awaited()
        failure = self.passport_repo.apply_extraction_failure.await_args.kwargs
        self.assertEqual(
            failure["diagnostics"]["ai_verification"]["status"],
            "unavailable",
        )
        self.job_repo.mark_succeeded.assert_not_awaited()

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
        self.idempotency_key = "upload-duplicate-safe-key-1234567890"
        self.group = SimpleNamespace(
            id=self.group_id,
            agency_id=self.agency_id,
            require_selfie=False,
            is_active=lambda: True,
            deleted_at=None,
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
        self.capacity_guard = AsyncMock(spec=GroupPassengerCapacityGuard)

    def _use_case(self) -> SubmitPassportUseCase:
        return SubmitPassportUseCase(
            client_group_repo=self.client_group_repo,
            passport_repo=self.passport_repo,
            storage_repo=self.storage_repo,
            processing_job_repo=self.job_repo,
            group_capacity_guard=self.capacity_guard,
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

    async def test_group_capacity_is_checked_under_lock_before_persistence(self) -> None:
        self.passport_repo.get_by_upload_idempotency_key.return_value = None
        self.capacity_guard.assert_available.side_effect = ValidationError(
            "This group supports at most 10,000 passenger records.",
            field="group_capacity",
        )

        with self.assertRaises(ValidationError):
            await self._use_case().execute(
                token="public-token",
                file_content=b"new-front",
                content_type="image/jpeg",
                filename="front.jpg",
                client_name="New Traveller",
                passport_back=(b"new-back", "image/jpeg", "back.jpg"),
                acquisition_mode="camera",
                upload_idempotency_key="capacity-safe-upload-key-123456789",
            )

        self.capacity_guard.lock_group.assert_awaited_once_with(
            agency_id=self.agency_id,
            group_id=self.group_id,
        )
        self.capacity_guard.assert_available.assert_awaited_once_with(
            agency_id=self.agency_id,
            group_id=self.group_id,
            additional_passengers=1,
        )
        self.passport_repo.save_idempotent.assert_not_awaited()
        self.storage_repo.delete_files.assert_awaited_once()

    async def test_locked_idempotent_replay_does_not_consume_group_capacity(self) -> None:
        self.passport_repo.get_by_upload_idempotency_key.side_effect = [
            None,
            self.existing,
        ]

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
        self.capacity_guard.lock_group.assert_awaited_once()
        self.capacity_guard.assert_available.assert_not_awaited()
        self.passport_repo.save_idempotent.assert_not_awaited()
        self.storage_repo.delete_files.assert_awaited_once()

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
                upload_idempotency_key=("another-safe-upload-key-1234567890"),
            )

        self.storage_repo.delete_files.assert_awaited_once()
        attempted_keys = self.storage_repo.delete_files.await_args.args[0]
        self.assertEqual(len(attempted_keys), 2)
        self.assertTrue(any(key.endswith(".jpg") for key in attempted_keys))
        self.assertTrue(any(key.endswith("-back.jpg") for key in attempted_keys))
        self.passport_repo.save_idempotent.assert_not_awaited()

    async def test_persisted_idempotent_replay_cannot_bypass_group_closure(self) -> None:
        self.group.is_active = lambda: False
        self.passport_repo.get_by_upload_idempotency_key.return_value = self.existing

        with self.assertRaises(EntityNotFoundError):
            await self._use_case().execute(
                token="public-token",
                file_content=b"new-front",
                content_type="image/jpeg",
                filename="front.jpg",
                client_name="Existing Traveller",
                passport_back=(b"new-back", "image/jpeg", "back.jpg"),
                acquisition_mode="camera",
                upload_idempotency_key=self.idempotency_key,
            )

        self.passport_repo.get_by_upload_idempotency_key.assert_not_awaited()
        self.storage_repo.upload_file.assert_not_awaited()
        self.passport_repo.save_idempotent.assert_not_awaited()
        self.job_repo.create.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
