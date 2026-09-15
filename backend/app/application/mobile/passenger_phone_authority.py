"""Collection-submitted contact authority shared by login and live sessions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES
from app.domain.value_objects.client_collection_provenance import (
    CLIENT_COLLECTION_SUBMITTED_KEY,
    CLIENT_COLLECTION_SUBMITTED_VALUE,
)
from app.domain.value_objects.phone_number import normalize_phone_number


class PassengerSubmissionAuthority(Protocol):
    @property
    def status(self) -> str: ...

    @property
    def client_phone(self) -> str | None: ...


def authoritative_submission_phone(submission: PassengerSubmissionAuthority) -> str | None:
    """Return only a completed collection contact, never an imported roster phone.

    Legacy public submissions predate the explicit collection marker. Their
    completed review timestamp remains valid unless known import provenance
    says otherwise. New public completions can explicitly supersede an import.
    """

    if submission.status not in OFFICE_VISIBLE_PASSPORT_STATUS_VALUES:
        return None
    if getattr(submission, "client_reviewed_at", None) is None:
        return None
    metadata = getattr(submission, "staff_metadata", None)
    explicitly_submitted = (
        isinstance(metadata, Mapping)
        and metadata.get(CLIENT_COLLECTION_SUBMITTED_KEY) == CLIENT_COLLECTION_SUBMITTED_VALUE
    )
    confidence = getattr(submission, "confidence_score", None)
    known_import = (
        isinstance(confidence, Mapping) and confidence.get("source") == "excel_import"
    ) or str(getattr(submission, "image_s3_key", "") or "").startswith("excel-imports/")
    if known_import and not explicitly_submitted:
        return None
    return normalize_phone_number(submission.client_phone)


def submitted_phone_matches_identity(identity: object, submission: PassengerSubmissionAuthority) -> bool:
    """Check the complete identity scope as well as the current submitted number."""

    phone = authoritative_submission_phone(submission)
    return (
        phone is not None
        and getattr(identity, "passenger_submission_id", None) == getattr(submission, "id", None)
        and getattr(identity, "agency_id", None) == getattr(submission, "agency_id", None)
        and getattr(identity, "group_id", None) == getattr(submission, "group_id", None)
        and getattr(identity, "normalized_phone_number", None) == phone
    )
