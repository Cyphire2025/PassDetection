"""Public outage fallback stays pending a real, revision-fenced staff decision."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError as SchemaValidationError

from app.application.dtos.passport_dtos import passport_submission_output_from_entity
from app.application.platform_policies import PlatformPolicies
from app.application.use_cases.passports.client_submit_passport_use_case import (
    ClientSubmitPassportUseCase,
)
from app.domain.entities.entities import (
    OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES,
    ClientGroup,
    PassportProcessingStatus,
    PassportSubmission,
    StaffApprovalOutcome,
)
from app.domain.exceptions.exceptions import ValidationError
from app.domain.value_objects.passport_document_classification import (
    MANUAL_REVIEW_REASON_CODE,
    PASSPORT_PROVIDER_FAILURE_STATUSES,
    REJECTED_PASSPORT_DOCUMENT_STATUSES,
    classification_outcome,
)
from app.infrastructure.processing.job_state import ProcessingJobStatus
from app.presentation.api.v1.routes.passport_routes.response_support import (
    _manual_review_response_fields,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    ClientSubmitPassportRequest,
    PassportSubmissionResponse,
)


def _draft(status: str = "timeout"):
    group = ClientGroup.create(
        name="Outage review", token="public-group-token",
        agency_id=uuid.uuid4(), created_by_user_id=uuid.uuid4(),
    )
    submission = PassportSubmission.create(
        group_id=group.id, agency_id=group.agency_id,
        client_name="Traveller", client_email=None,
        image_s3_key="drafts/agency/group/front.jpg",
    )
    submission.passport_back_s3_key = "drafts/agency/group/back.jpg"
    revision = submission.mark_processing()
    classification = {"status": status, "available": False}
    classification.update(classification_outcome(classification, extraction_revision=revision))
    submission.mark_extraction_failed(
        expected_revision=revision,
        diagnostics={"ai_verification": classification},
    )
    passports = AsyncMock()
    passports.get_by_id_for_update.return_value = submission
    passports.exists_contact_in_group.return_value = False
    groups = AsyncMock()
    groups.get_by_token.return_value = group
    storage = AsyncMock()
    storage.get_file.return_value = b"already-validated-image"
    policies = AsyncMock()
    policies.load.return_value = PlatformPolicies(
        require_client_email=False, require_client_phone=False,
    )
    use_case = ClientSubmitPassportUseCase(passports, groups, storage, policies)
    return group, submission, use_case, passports, storage


async def _submit(group, submission, use_case, **changes):
    return await use_case.execute(submission.id, **{
        "group_token": group.token,
        "confirmed_fields": {"given_names": "AMAN", "passport_number": "P1234567"},
        "client_email": "traveller@example.com",
        "client_phone": "98765 43210",
        **changes,
    })


@pytest.mark.parametrize("provider_status", sorted(PASSPORT_PROVIDER_FAILURE_STATUSES))
async def test_current_provider_failure_submits_for_staff_review(provider_status):
    group, submission, use_case, passports, storage = _draft(provider_status)
    previous_revision = submission.extraction_revision
    draft = PassportSubmissionResponse.model_validate(passport_submission_output_from_entity(submission))
    assert draft.manual_review_submission_allowed
    assert draft.manual_review_reason_code == "AI_EXTRACTION_UNAVAILABLE"

    result = await _submit(group, submission, use_case)

    assert result.status == "needs_review"
    assert result.status not in OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES
    assert result.client_phone == "+919876543210"
    assert result.extraction_revision == previous_revision + 1
    assert result.post_submission_verification_revision == 1
    assert result.post_submission_verified_at is None
    assert result.post_submission_verification["reason_code"] == MANUAL_REVIEW_REASON_CODE
    assert not result.manual_review_submission_allowed
    assert result.image_s3_key.startswith(str(group.agency_id))
    assert len(result.storage_cleanup_keys) == 2
    storage.upload_file.assert_awaited()
    passports.update.assert_awaited_once()
    PassportSubmissionResponse.model_validate(result)


@pytest.mark.parametrize("status", sorted(REJECTED_PASSPORT_DOCUMENT_STATUSES) + ["unknown"])
async def test_rejected_or_unknown_document_still_cannot_submit(status):
    group, submission, use_case, passports, storage = _draft(status)
    assert not submission.manual_review_submission_allowed
    with pytest.raises(ValidationError, match="passport photo and details page"):
        await _submit(group, submission, use_case)
    passports.update.assert_not_awaited()
    storage.upload_file.assert_not_awaited()


@pytest.mark.parametrize("change", ["missing_evidence", "stale", "processing", "cancelled", "storage_error"])
async def test_missing_stale_or_nonprovider_failure_cannot_authorize_manual_submit(change):
    group, submission, use_case, _, _ = _draft()
    classification = submission.extracted_fields["ai_verification"]
    if change == "missing_evidence":
        classification.pop("outcome_kind")
    elif change == "stale":
        classification["extraction_revision"] -= 1
    elif change == "processing":
        submission.mark_processing()
    elif change == "cancelled":
        submission.extracted_fields = None
    else:
        classification["status"] = "storage_unavailable"
    with pytest.raises(ValidationError):
        await _submit(group, submission, use_case)


async def test_replay_preserves_pending_review_and_promoted_images_once():
    group, submission, use_case, passports, storage = _draft()
    first = await _submit(group, submission, use_case)
    replay = await _submit(group, submission, use_case, client_phone="0091-98765-43210")
    assert replay.idempotent_replay
    assert replay.status == "needs_review"
    assert replay.extraction_revision == first.extraction_revision
    assert replay.post_submission_verification_revision == first.post_submission_verification_revision
    assert storage.upload_file.await_count == 2
    passports.update.assert_awaited_once()
    with pytest.raises(ValidationError, match="already submitted"):
        await _submit(group, submission, use_case, confirmed_fields={"given_names": "CHANGED"})


@pytest.mark.parametrize("job_status", ["dead_letter", "cancelled", "running", "queued", "succeeded"])
async def test_legacy_outage_needs_matching_terminal_server_job(job_status):
    group, submission, use_case, _, _ = _draft()
    evidence = submission.extracted_fields["ai_verification"]
    evidence.pop("outcome_kind")
    evidence.pop("extraction_revision")
    assert not submission.manual_review_submission_allowed
    job = SimpleNamespace(extraction_revision=submission.extraction_revision, status=ProcessingJobStatus(job_status))
    jobs = AsyncMock()
    jobs.latest_for_submission.return_value = job
    use_case._processing_job_repo = jobs
    response = _manual_review_response_fields(submission, job.extraction_revision, job_status)
    assert response["manual_review_submission_allowed"] == (job_status == "dead_letter")
    if job_status == "dead_letter":
        result = await _submit(group, submission, use_case)
        assert result.status == "needs_review"
        assert submission.extracted_fields["ai_verification"]["outcome_kind"] == "provider_failure"
    else:
        with pytest.raises(ValidationError):
            await _submit(group, submission, use_case)


async def test_late_ai_cannot_replace_review_and_staff_approval_is_revision_fenced():
    group, submission, use_case, _, _ = _draft()
    old_extraction_revision = submission.extraction_revision
    await _submit(group, submission, use_case)
    assert not submission.mark_review_required(
        {"given_names": "WRONG"}, 1.0, expected_revision=old_extraction_revision,
    )
    assert not submission.apply_post_submission_verification(
        expected_revision=submission.post_submission_verification_revision,
        decision="ai_approved", verification={"verification_status": "ai_approved"},
    )
    with pytest.raises(ValidationError, match="requires staff approval"):
        submission.request_post_submission_verification_retry()
    submission.update_reviewed_fields({"given_names": "AMAN REVIEWED"})
    assert submission.post_submission_verification["reason_code"] == MANUAL_REVIEW_REASON_CODE
    reviewer = uuid.uuid4()
    revision = submission.extraction_revision
    outcome = submission.staff_approve_verification(
        reviewer_id=reviewer, reviewer_name="Reviewer", expected_extraction_revision=revision,
    )
    assert outcome == StaffApprovalOutcome.APPROVED
    assert submission.status == PassportProcessingStatus.STAFF_APPROVED
    assert submission.verification_reviewed_by_user_id == reviewer
    assert submission.staff_approve_verification(
        reviewer_id=reviewer, reviewer_name="Reviewer", expected_extraction_revision=revision,
    ) == StaffApprovalOutcome.ALREADY_APPROVED


def test_public_request_cannot_assert_manual_review_eligibility():
    with pytest.raises(SchemaValidationError):
        ClientSubmitPassportRequest(
            confirmed_fields={"given_names": "AMAN"}, group_token="public-group-token",
            manual_review_submission_allowed=True,
        )


@pytest.mark.parametrize("number", ["++919876543210", "1234567890123456", "call9876543210", "+01234567890", "1234567"])
async def test_use_case_rejects_invalid_phones_even_for_direct_callers(number):
    group, submission, use_case, passports, storage = _draft()
    with pytest.raises(ValidationError):
        await _submit(group, submission, use_case, client_phone=number)
    passports.update.assert_not_awaited()
    storage.upload_file.assert_not_awaited()
