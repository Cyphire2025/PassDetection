"""Reuse existing image verification; never treat an approval label as proof.

The nine stored field results are bounded and checked against the current
confirmed input. No provider request, nationality inference or OCR repair occurs.
"""

from __future__ import annotations

from app.application.interfaces.post_submission_verification import POST_SUBMISSION_PASSPORT_FIELDS
from app.application.travellers.versioning import EnrollmentError, accepted_dates
from app.domain.exceptions.exceptions import ValidationError
from app.domain.services.traveller_verification import (
    UNKNOWN_ISSUING_COUNTRY,
    exact_passport_number,
    utc,
)
from app.infrastructure.database.models import PassportSubmissionModel

AI_ACCEPTANCE_RULE = "client_reviewed_current_ai_v1"


def accepted_ai_fields(source: PassportSubmissionModel, fields: dict[str, str]) -> dict[str, str]:
    rows = _current_decision_fields(source)
    checked: set[str] = set()
    for row in rows:
        key = _verified_field(row, fields)
        if key in checked:
            raise EnrollmentError("verified_source_fields_required")
        checked.add(key)
    try:
        exact_passport_number(fields.get("passport_number", ""))
        dates = accepted_dates(fields)
        if "date_of_birth" not in dates or "expiry_date" not in dates:
            raise ValueError("missing_dates")
    except (ValueError, ValidationError) as exc:
        raise EnrollmentError("verified_source_dates_required") from exc
    return {**fields, "issuing_country": UNKNOWN_ISSUING_COUNTRY, "document_type": "P"}


def _current_decision_fields(source: PassportSubmissionModel) -> list[object]:
    verification = source.post_submission_verification
    if (source.status != "ai_approved" or source.client_reviewed_at is None
            or source.post_submission_verified_at is None
            or utc(source.post_submission_verified_at) < utc(source.client_reviewed_at)
            or source.post_submission_verification_revision < 1
            or not isinstance(verification, dict)
            or verification.get("verification_status") != "ai_approved"
            or verification.get("provider_status") != "verified"
            or verification.get("incorrect_fields") != [] or verification.get("suspicious_fields") != []):
        raise EnrollmentError("current_ai_approval_required")
    rows = verification.get("fields")
    if not isinstance(rows, list) or len(rows) != len(POST_SUBMISSION_PASSPORT_FIELDS):
        raise EnrollmentError("verified_source_fields_required")
    return rows


def _verified_field(row: object, fields: dict[str, str]) -> str:
    if not isinstance(row, dict):
        raise EnrollmentError("verified_source_fields_required")
    key = row.get("field")
    if not isinstance(key, str) or key not in POST_SUBMISSION_PASSPORT_FIELDS:
        raise EnrollmentError("verified_source_fields_required")
    expected = fields.get(key)
    # The existing decision may explicitly verify an absent surname. Missing
    # identity/date observations must never become reliable evidence here.
    absent_surname = key == "surname" and expected == "" and row.get("reason_code") == "not_present"
    observed = row.get("observed_value")
    if row.get("verdict") != "correct" or not isinstance(expected, str) or len(expected) > 160:
        raise EnrollmentError("verified_source_fields_required")
    if not (absent_surname and observed in (None, "")) and (not expected or observed != expected):
        raise EnrollmentError("verified_source_fields_changed")
    return key
