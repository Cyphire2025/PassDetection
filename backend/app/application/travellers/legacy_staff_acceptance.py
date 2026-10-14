"""Accept the canonical staff decision without inventing missing passport context.

The existing staff transition publishes reviewer/time and both revisions in one
transaction; subsequent edits clear that decision. Audit is release evidence,
not a second approval system. All checks and frozen-proof work are O(1).
"""

import hmac
import uuid

import pycountry

from app.application.travellers.source_evidence import source_evidence_digest
from app.application.travellers.versioning import EnrollmentError, accepted_dates
from app.core.config.traveller_reuse import get_traveller_reuse_settings
from app.domain.exceptions.exceptions import ValidationError
from app.domain.services.traveller_verification import (
    UNKNOWN_ISSUING_COUNTRY,
    exact_passport_number,
    issuing_context,
    utc,
)
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.traveller_reuse_models import TravellerDocumentRevisionModel
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto

STAFF_ACCEPTANCE_RULE = "staff_reviewed_current_v1"


def needs_staff_compatibility(source: PassportSubmissionModel, fields: dict[str, str]) -> bool:
    return (source.status == "staff_approved" and not source.mrz_raw
        and (not fields.get("issuing_country") or not fields.get("document_type")))


def accepted_staff_fields(source: PassportSubmissionModel, fields: dict[str, str]) -> dict[str, str]:
    reviewed = source.verification_reviewed_at
    if (source.status != "staff_approved" or not isinstance(source.verification_reviewed_by_user_id, uuid.UUID)
            or reviewed is None or source.confirmed_at is None or utc(source.confirmed_at) != utc(reviewed)
            or type(source.extraction_revision) is not int or source.extraction_revision < 1
            or type(source.post_submission_verification_revision) is not int or source.post_submission_verification_revision < 1
            or (source.client_reviewed_at is not None and utc(source.client_reviewed_at) > utc(reviewed))
            or (source.post_submission_verified_at is not None and utc(source.post_submission_verified_at) > utc(reviewed))):
        raise EnrollmentError("current_staff_approval_required")
    try:
        exact_passport_number(fields.get("passport_number", ""))
        dates = accepted_dates(fields)
        issuer, kind = issuing_context(fields.get("issuing_country") or UNKNOWN_ISSUING_COUNTRY,
            fields.get("document_type") or "P")
        if ("date_of_birth" not in dates or "expiry_date" not in dates or kind not in {"P", "PASSPORT"}
                or (issuer != UNKNOWN_ISSUING_COUNTRY and pycountry.countries.get(alpha_3=issuer) is None)):
            raise ValueError("invalid_staff_fields")
    except (ValueError, ValidationError) as exc:
        raise EnrollmentError("reviewed_staff_identity_required") from exc
    return {**fields, "issuing_country": issuer, "document_type": "P"}


def staff_acceptance_proof(source: PassportSubmissionModel, crypto: TravellerReuseCrypto) -> dict[str, object]:
    """Only after accepted_staff_fields; bind photos/fields and current decision."""
    assert source.verification_reviewed_at is not None
    return {"source_extraction_revision": source.extraction_revision,
        "source_verification_revision": source.post_submission_verification_revision,
        "source_reviewed_by_user_id": str(source.verification_reviewed_by_user_id),
        "source_reviewed_at": utc(source.verification_reviewed_at).isoformat(),
        "source_input_digest": source_evidence_digest(crypto, source)}


def staff_source_is_current(revision: TravellerDocumentRevisionModel, source: PassportSubmissionModel,
    crypto: TravellerReuseCrypto | None,
) -> bool:
    fields = dict(source.confirmed_fields or {})
    if not needs_staff_compatibility(source, fields):
        return False
    try:
        accepted_staff_fields(source, fields)
    except EnrollmentError:
        return False
    crypto = crypto or TravellerReuseCrypto(get_traveller_reuse_settings())
    expected = staff_acceptance_proof(source, crypto)
    return all(revision.source_provenance.get(key) == value for key, value in expected.items()
        if key != "source_input_digest") and hmac.compare_digest(
            str(revision.source_provenance.get("source_input_digest", "")), str(expected["source_input_digest"]))
