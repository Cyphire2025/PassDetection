"""Bounded acceptance of historical source fields with truthful provenance.

Staff-reviewed fields keep their existing authority. Client-reviewed records
require exact agreement with a stored, checksum-valid TD3 MRZ; OCR recovery and
nationality-to-issuer inference are deliberately unavailable in this path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pycountry

from app.application.travellers.versioning import EnrollmentError, accepted_dates
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES
from app.domain.exceptions.exceptions import ValidationError
from app.domain.services.traveller_verification import exact_passport_number, issuing_context
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.traveller_reuse_models import TravellerDocumentRevisionModel
from app.infrastructure.ocr.td3_mrz_parser import TD3MRZParser

STAFF_ACCEPTED_STATUSES = frozenset({"staff_approved", "confirmed"})
MRZ_ACCEPTANCE_RULE = "client_reviewed_exact_td3_v1"


@dataclass(frozen=True, slots=True)
class AcceptedSource:
    fields: dict[str, str]
    reliable_source: str
    mrz_context: bool


def validated_mrz_fields(raw: str | None, fields: dict[str, str]) -> dict[str, str]:
    """O(1) bounded input: exactly two 44-character lines, no OCR repairs."""
    if not raw or len(raw) > 512:
        raise EnrollmentError("reliable_issuing_context_required")
    lines = [line.strip().upper() for line in raw.splitlines() if line.strip()]
    if len(lines) != 2 or any(not re.fullmatch(r"[A-Z0-9<]{44}", line) for line in lines):
        raise EnrollmentError("reliable_issuing_context_required")
    parsed = TD3MRZParser().parse("\n".join(lines))
    if parsed is None:
        raise EnrollmentError("reliable_issuing_context_required")
    try:
        if exact_passport_number(fields.get("passport_number", "")) != exact_passport_number(parsed.fields["passport_number"]):
            raise ValueError("passport_conflict")
        saved_dates, mrz_dates = accepted_dates(fields), accepted_dates(parsed.fields)
        if any(saved_dates.get(key) is None or saved_dates[key] != mrz_dates.get(key)
               for key in ("date_of_birth", "expiry_date")):
            raise ValueError("date_conflict")
        issuer, kind = issuing_context(parsed.fields["issuing_country"], fields.get("document_type") or "P")
        if pycountry.countries.get(alpha_3=issuer) is None:
            raise ValueError("unknown_issuer")
        if fields.get("issuing_country") and fields["issuing_country"].strip().upper() != issuer:
            raise ValueError("issuer_conflict")
        if kind not in {"P", "PASSPORT"}:
            raise ValueError("document_type_conflict")
    except (ValueError, KeyError, ValidationError) as exc:
        raise EnrollmentError("saved_mrz_identity_conflict") from exc
    return {**fields, "issuing_country": issuer, "document_type": kind}


def accept_source(source: PassportSubmissionModel, fields: dict[str, str], *, operator: bool) -> AcceptedSource:
    if source.status in STAFF_ACCEPTED_STATUSES:
        missing_context = not fields.get("issuing_country") or not fields.get("document_type")
        if missing_context and operator:
            return AcceptedSource(validated_mrz_fields(source.mrz_raw, fields), "staff_review", True)
        return AcceptedSource(fields, "staff_review", False)
    if not operator or source.status not in OFFICE_VISIBLE_PASSPORT_STATUS_VALUES or source.client_reviewed_at is None:
        raise EnrollmentError("accepted_source_revision_required")
    return AcceptedSource(validated_mrz_fields(source.mrz_raw, fields), "verified_import", True)


def retained_source_is_current(revision: TravellerDocumentRevisionModel, source: PassportSubmissionModel) -> bool:
    """Source authorization for pending independent copies; caller checks scope."""
    if source.status in STAFF_ACCEPTED_STATUSES:
        return True
    if revision.source_provenance.get("acceptance_rule") != MRZ_ACCEPTANCE_RULE:
        return False
    try:
        accepted = accept_source(source, dict(source.confirmed_fields or {}), operator=True)
    except EnrollmentError:
        return False
    return accepted.reliable_source == "verified_import"
