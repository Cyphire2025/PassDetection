"""Roster view fields with explicit projection boundaries."""

from __future__ import annotations

import math
import re
import unicodedata
import uuid
from typing import Any

from app.domain.value_objects.passport_fields import canonical_country_identity


def _normalized_tokens(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(token for token in re.split(r"[^\w]+", text) if token)


def _normalized_identifier(value: Any) -> str:
    return "".join(character for character in _normalized_tokens(value) if character.isalnum())


def _field_value(submission: Any, field: str) -> str:
    confirmed = submission.confirmed_fields or {}
    extracted = submission.extracted_fields or {}
    # An explicit reviewed blank (notably surname) is authoritative.
    if field in confirmed:
        value = confirmed.get(field)
    else:
        value = extracted.get(field)
    return str(value).strip() if value is not None else ""


def _passport_name(submission: Any) -> str:
    components = [
        _field_value(submission, "given_names"),
        _field_value(submission, "surname"),
    ]
    passport_name = _normalized_tokens(" ".join(component for component in components if component))
    if passport_name:
        return passport_name
    return _normalized_tokens(submission.client_name)


def _place_of_issue_identity(submission: Any) -> str:
    confirmed = submission.confirmed_fields or {}
    extracted = submission.extracted_fields or {}
    if "place_of_issue" in confirmed or "place_of_issue" in extracted:
        return _normalized_identifier(_field_value(submission, "place_of_issue"))

    # Preserve country-code/name equivalence for old records whose JSON used
    # the previous field. New records use the visibly printed place text.
    legacy_value = _field_value(submission, "issuing_country")
    return canonical_country_identity(legacy_value) if legacy_value else ""


def duplicate_identity_key(submission: Any) -> str | None:
    """Prefer passport+place of issue, with a cautious demographic fallback."""

    passport_number = _normalized_identifier(_field_value(submission, "passport_number"))
    place_of_issue = _place_of_issue_identity(submission)
    if passport_number and place_of_issue:
        return f"passport:{passport_number}:{place_of_issue}"

    name = _passport_name(submission)
    date_of_birth = _normalized_identifier(_field_value(submission, "date_of_birth"))
    nationality_value = _field_value(submission, "nationality")
    nationality = canonical_country_identity(nationality_value) if nationality_value else ""
    if name and date_of_birth and nationality:
        return f"fallback:{name}:{date_of_birth}:{nationality}"
    return None


def _cluster_id(member_ids: tuple[uuid.UUID, ...]) -> str:
    # Submission UUIDs are already response identifiers and avoid deriving a
    # correlatable token from passport or demographic PII.
    return f"dup_{member_ids[0].hex}"


def _verification_confidence(submission: Any) -> float | None:
    verification = submission.post_submission_verification
    verification_usable = True
    if isinstance(verification, dict):
        fields = verification.get("fields")
        if isinstance(fields, list):
            for field in fields:
                if not isinstance(field, dict):
                    continue
                confidence = field.get("confidence")
                if (
                    not isinstance(confidence, (int, float))
                    or isinstance(confidence, bool)
                    or confidence <= 0
                ):
                    continue
                observed_value = str(field.get("observed_value") or "").strip()
                reason_code = str(field.get("reason_code") or "").strip().casefold()
                if not observed_value or reason_code in {"unreadable", "missing_submitted_value"}:
                    verification_usable = False
                    break
        value = verification.get("confidence")
        if (
            verification_usable
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        ):
            return float(value)
    value = submission.overall_confidence
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    ):
        return float(value)
    return None


def _display_name(submission: Any) -> str:
    return str(getattr(submission, "display_name", None) or submission.client_name)
