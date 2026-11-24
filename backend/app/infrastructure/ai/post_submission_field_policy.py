"""Post submission field policy."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.application.interfaces.post_submission_verification import (
    POST_SUBMISSION_PASSPORT_FIELDS,
    PostSubmissionFieldResult,
    PostSubmissionFieldVerdict,
)
from app.domain.exceptions.exceptions import ValidationError
from app.domain.value_objects.passport_fields import (
    canonical_country_identity,
    normalize_passport_date,
)
from app.infrastructure.ai.passport_date_evidence import (
    PassportNumericDateOrder,
    normalize_passport_date_evidence,
    passport_date_evidence_candidates,
    passport_numeric_date_order_hint,
)
from app.infrastructure.ai.post_submission_contract import (
    _MAX_OBSERVED_VALUE_CHARACTERS,
    _REASON_CODES,
    _VERDICTS,
)


def _string_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _normalize_passport_value(
    field: str,
    value: Any,
) -> str:
    normalized = unicodedata.normalize("NFKC", _string_value(value))
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return ""
    if field in {"surname", "given_names"}:
        candidate = normalized.upper()
        if len(candidate) > 100:
            return ""
        if not all(character.isalpha() or character in " '-." for character in candidate):
            return ""
        # Whitespace adjacent to passport-name punctuation is presentational,
        # but punctuation itself remains significant.
        return re.sub(r"\s*([.'-])\s*", r"\1", candidate)
    if field == "passport_number":
        candidate = re.sub(r"\s+", "", normalized).upper()
        return candidate if re.fullmatch(r"[A-Z0-9]{5,12}", candidate) else ""
    if field == "nationality":
        identity = canonical_country_identity(normalized)
        return identity if re.fullmatch(r"[A-Z]{3}", identity) else ""
    if field == "place_of_issue":
        candidate = normalized.upper()
        if (
            len(candidate) > _MAX_OBSERVED_VALUE_CHARACTERS
            or not any(character.isalnum() for character in candidate)
            or any(unicodedata.category(character).startswith("C") for character in candidate)
        ):
            return ""
        return candidate
    if field in {"date_of_birth", "date_of_issue", "date_of_expiry"}:
        try:
            return normalize_passport_date(normalized, field=field)
        except ValidationError:
            return ""
    if field == "sex":
        candidate = {
            "MALE": "M",
            "FEMALE": "F",
            "UNSPECIFIED": "X",
        }.get(normalized.upper(), normalized.upper())
        return candidate if candidate in {"M", "F", "X", "<"} else ""
    return ""


class PostSubmissionFieldAgent:
    """Validate and normalize the provider's strict field-by-field evidence."""

    def evaluate(
        self,
        raw_fields: Any,
        submitted_fields: dict[str, Any],
    ) -> tuple[PostSubmissionFieldResult, ...]:
        if not isinstance(raw_fields, list) or len(raw_fields) != len(
            POST_SUBMISSION_PASSPORT_FIELDS
        ):
            raise ValueError("Gemini must return every passport field exactly once")

        date_order_hints = {
            hint
            for raw in raw_fields
            if isinstance(raw, dict)
            and raw.get("field") in {"date_of_birth", "date_of_issue", "date_of_expiry"}
            and isinstance(raw.get("observed_value"), str)
            and (
                hint := passport_numeric_date_order_hint(
                    raw["observed_value"],
                )
            )
            is not None
        }
        date_order: PassportNumericDateOrder | None = (
            next(iter(date_order_hints)) if len(date_order_hints) == 1 else None
        )
        results: dict[str, PostSubmissionFieldResult] = {}
        expected_keys = {
            "field",
            "verdict",
            "observed_value",
            "confidence",
            "reason_code",
        }
        for raw in raw_fields:
            if not isinstance(raw, dict) or set(raw) != expected_keys:
                raise ValueError("Unexpected post-submission field result shape")
            field = raw["field"]
            if field not in POST_SUBMISSION_PASSPORT_FIELDS or field in results:
                raise ValueError("Unexpected or duplicate passport field")
            if raw["verdict"] not in _VERDICTS or raw["reason_code"] not in _REASON_CODES:
                raise ValueError("Unexpected passport field verdict")

            raw_confidence = raw["confidence"]
            if isinstance(raw_confidence, bool) or not isinstance(
                raw_confidence,
                (int, float),
            ):
                raise ValueError("Confidence must be a JSON number")
            confidence = float(raw_confidence)
            if not 0.0 <= confidence <= 1.0:
                raise ValueError("Confidence must be between zero and one")

            submitted = _normalize_passport_value(field, submitted_fields.get(field))
            raw_observed = raw["observed_value"]
            if (
                not isinstance(raw_observed, str)
                or len(raw_observed) > _MAX_OBSERVED_VALUE_CHARACTERS
            ):
                raise ValueError("Observed value must be a bounded JSON string")
            date_evidence_ambiguous = False
            if field in {"date_of_birth", "date_of_issue", "date_of_expiry"}:
                date_candidates = passport_date_evidence_candidates(
                    raw_observed,
                    field=field,
                )
                observed = normalize_passport_date_evidence(
                    raw_observed,
                    field=field,
                    numeric_order=date_order,
                )
                date_evidence_ambiguous = len(date_candidates) > 1 and not observed
            else:
                observed = _normalize_passport_value(field, raw_observed)
            verdict = PostSubmissionFieldVerdict(raw["verdict"])
            reason_code = str(raw["reason_code"])
            if reason_code == "not_present" and (field != "surname" or _string_value(raw_observed)):
                raise ValueError("Only an empty surname can use not_present evidence")

            surname_confirmed_absent = (
                field == "surname"
                and not submitted
                and not observed
                and not _string_value(raw_observed)
                and verdict == PostSubmissionFieldVerdict.CORRECT
                and reason_code == "not_present"
            )
            if surname_confirmed_absent:
                # Absence is provider-supplied visual evidence, not a missing
                # extraction. Confidence calibration below still fails closed
                # when that evidence is weak.
                verdict = PostSubmissionFieldVerdict.CORRECT
            elif not submitted and field == "surname" and observed:
                verdict = PostSubmissionFieldVerdict.INCORRECT
                reason_code = "different_value"
            elif not submitted and field == "surname":
                verdict = PostSubmissionFieldVerdict.SUSPICIOUS
                reason_code = "unreadable" if reason_code == "unreadable" else "ambiguous"
            elif not submitted:
                verdict = PostSubmissionFieldVerdict.SUSPICIOUS
                reason_code = "missing_submitted_value"
            elif date_evidence_ambiguous:
                verdict = PostSubmissionFieldVerdict.SUSPICIOUS
                reason_code = "ambiguous"
            elif not observed:
                verdict = PostSubmissionFieldVerdict.SUSPICIOUS
                reason_code = "unreadable"
            elif observed == submitted:
                # Gemini supplies visible evidence; the application owns the
                # deterministic comparison result. Confidence calibration below
                # still downgrades a visually weak match.
                verdict = PostSubmissionFieldVerdict.CORRECT
                reason_code = "match"
            elif verdict == PostSubmissionFieldVerdict.CORRECT:
                verdict = PostSubmissionFieldVerdict.INCORRECT
                reason_code = "different_value"

            results[field] = PostSubmissionFieldResult(
                field=field,
                verdict=verdict,
                observed_value=observed or None,
                confidence=confidence,
                reason_code=reason_code,
            )

        if set(results) != set(POST_SUBMISSION_PASSPORT_FIELDS):
            raise ValueError("Gemini omitted a passport field")
        return tuple(results[field] for field in POST_SUBMISSION_PASSPORT_FIELDS)
