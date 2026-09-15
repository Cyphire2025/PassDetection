"""Deterministic server-side passport information-page classification gates."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

ACCEPTED_PASSPORT_DOCUMENT_STATUSES = frozenset({"verified", "enhanced"})
REJECTED_PASSPORT_DOCUMENT_STATUSES = frozenset({
    "passport_cover", "wrong_passport_page", "wrong_document",
    "document_low_quality", "document_unreadable", "document_uncertain",
})
PASSPORT_PROVIDER_FAILURE_STATUSES = frozenset({
    "not_configured", "unavailable", "deadline_exhausted", "timeout",
    "network_error", "rate_limited", "provider_unavailable", "permission_denied",
    "provider_rejected_request", "invalid_response", "internal_error",
})
MANUAL_REVIEW_REASON_CODE = "AI_EXTRACTION_UNAVAILABLE_MANUAL_SUBMISSION"


def classification_outcome(
    classification: Mapping[str, Any], *, extraction_revision: int,
) -> dict[str, object]:
    """Stamp trusted worker evidence; provider output cannot choose this outcome."""

    status = classification.get("status")
    if isinstance(status, str) and status in REJECTED_PASSPORT_DOCUMENT_STATUSES:
        outcome = "document_rejected"
    elif is_accepted_passport_information_page(classification):
        outcome = "accepted"
    elif (
        isinstance(status, str)
        and status in PASSPORT_PROVIDER_FAILURE_STATUSES
        and classification.get("available") is False
    ):
        outcome = "provider_failure"
    else:
        outcome = "unclassified"
    return {"outcome_kind": outcome, "extraction_revision": extraction_revision}


def manual_review_submission_allowed(
    *, extracted_fields: Mapping[str, Any] | None, extraction_revision: int,
    extraction_status: str, status: str, image_s3_key: str,
    processing_job_revision: int | None = None, processing_job_status: str | None = None,
) -> bool:
    """Only a persisted current-revision provider failure permits this route."""

    classification = passport_document_classification(extracted_fields)
    if not classification:
        return False
    current_failure = (
        classification.get("outcome_kind") == "provider_failure"
        and type(classification.get("extraction_revision")) is int
        and classification.get("extraction_revision") == extraction_revision
    )
    # Older workers stored explicit provider diagnostics but no outcome stamp.
    # A matching terminal job supplies the missing revision evidence. Never
    # upgrade an existing (possibly stale) stamp or infer from public copy.
    legacy_failure = (
        "outcome_kind" not in classification
        and "extraction_revision" not in classification
        and processing_job_status == "dead_letter"
        and processing_job_revision == extraction_revision
    )
    return bool(
        status == "ready_for_client_review"
        and extraction_status == "extraction_failed"
        and image_s3_key
        and not image_s3_key.startswith("excel-imports/")
        and (current_failure or legacy_failure)
        and classification.get("available") is False
        and isinstance(classification.get("status"), str)
        and classification.get("status") in PASSPORT_PROVIDER_FAILURE_STATUSES
    )


def requires_manual_staff_review(verification: Mapping[str, object] | None) -> bool:
    return bool(verification and verification.get("reason_code") == MANUAL_REVIEW_REASON_CODE)


def is_accepted_passport_information_page(value: object) -> bool:
    """Return true only for a positive, structured server-side classification."""

    if not isinstance(value, Mapping):
        return False
    status = value.get("status")
    available = value.get("available")
    return (
        isinstance(status, str)
        and status in ACCEPTED_PASSPORT_DOCUMENT_STATUSES
        and available is True
    )


def passport_document_classification(
    extracted_fields: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    """Read the bounded classification object from extracted fields."""

    if not isinstance(extracted_fields, Mapping):
        return None
    raw = extracted_fields.get("ai_verification")
    return raw if isinstance(raw, Mapping) else None
