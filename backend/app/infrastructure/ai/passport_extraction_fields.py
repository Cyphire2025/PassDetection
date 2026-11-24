"""Passport extraction fields; established service methods delegate here."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Any, Protocol

from app.domain.value_objects.passport_fields import normalize_extracted_passport_dates
from app.infrastructure.ai.passport_extraction_contract import (
    _ACTIONS,
    _FIELD_CODES,
    _MAX_FIELD_VALUE_CHARS,
    PASSPORT_FIELDS,
)
from app.infrastructure.validation.passport_field_validator import PassportFieldValidator


class PassportExtractionFieldsContext(Protocol):
    _validator: PassportFieldValidator

    def _normalize(self, field: str, raw_value: Any) -> str: ...

    @staticmethod
    def _string_value(value: Any) -> str: ...


def _merge(
    self: PassportExtractionFieldsContext, original: dict[str, Any], provider_result: dict[str, Any]
) -> tuple[dict[str, Any], list[str], list[str], list[str], dict[str, float]]:
    merged = dict(original)
    corrected: list[str] = []
    filled: list[str] = []
    absent: list[str] = []
    field_confidences: dict[str, float] = {}
    seen: set[str] = set()
    current_given_names = self._normalize(
        "given_names",
        merged.get("given_names"),
    )
    proposed_name_values: dict[str, str] = {}
    proposed_name_actions: dict[str, str] = {}
    for candidate in provider_result["f"]:
        if (
            isinstance(candidate, dict)
            and candidate.get("k") in {"sn", "gn"}
            and isinstance(candidate.get("v"), str)
            and isinstance(candidate.get("a"), str)
        ):
            candidate_field = _FIELD_CODES[str(candidate["k"])]
            proposed_name_values[candidate_field] = self._normalize(
                candidate_field,
                candidate["v"],
            )
            proposed_name_actions[candidate_field] = str(candidate["a"])

    for item in provider_result["f"]:
        if not isinstance(item, dict) or set(item) != {"k", "v", "a", "c"}:
            raise ValueError("Unexpected field result shape")
        code = item["k"]
        action = item["a"]
        raw_value = item["v"]
        raw_confidence = item["c"]
        if (
            not isinstance(code, str)
            or not isinstance(action, str)
            or not isinstance(raw_value, str)
            or len(raw_value) > _MAX_FIELD_VALUE_CHARS
            or isinstance(raw_confidence, bool)
            or not isinstance(raw_confidence, (int, float))
            or code not in _FIELD_CODES
            or action not in _ACTIONS
            or code in seen
        ):
            raise ValueError("Unexpected or duplicate field result")
        seen.add(code)
        field = _FIELD_CODES[code]
        confidence = float(raw_confidence)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("Confidence must be between zero and one")
        value = self._normalize(field, raw_value)
        current = self._string_value(merged.get(field))

        if action == "absent":
            if field != "surname" or self._string_value(raw_value):
                raise ValueError("Only an empty surname can be explicitly absent")
            if confidence >= 0.90:
                merged["surname"] = ""
                absent.append("surname")
                field_confidences["surname"] = round(confidence, 4)
                if current:
                    corrected.append("surname")
        elif (
            action == "fill"
            and field == "surname"
            and not current
            and value
            and (
                current_given_names == value
                or (
                    proposed_name_actions.get("given_names") in {"fill", "keep", "replace"}
                    and proposed_name_values.get("given_names") == value
                )
            )
        ):
            # Fail closed when the provider duplicates its given-name
            # extraction into a blank surname. A real absent surname must
            # use the explicit `absent` action; a readable surname must be
            # independently supported.
            continue
        elif action == "fill" and not current and value and confidence >= 0.75:
            merged[field] = value
            filled.append(field)
            field_confidences[field] = round(confidence, 4)
        elif action == "replace" and current and value and value != current and confidence >= 0.90:
            merged[field] = value
            corrected.append(field)
            field_confidences[field] = round(confidence, 4)
        elif action == "keep" and current and value == current:
            field_confidences[field] = round(confidence, 4)

    accepted = list(dict.fromkeys(corrected + filled + absent))
    if accepted:
        sources = dict(merged.get("extraction_sources") or {})
        for field in accepted:
            sources[field] = "gemini_image_verification"
        merged["extraction_sources"] = sources
        merged.pop("processing_note", None)

    merged = normalize_extracted_passport_dates(merged)
    validated_fields = {
        field: value
        for field in PASSPORT_FIELDS
        if (value := self._string_value(merged.get(field)))
    }
    validation = self._validator.validate(validated_fields)
    validation_issues = [
        issue
        for issue in validation.issues
        if not (
            issue.field == "surname"
            and "surname" in absent
            and issue.message == "Required field was not extracted."
        )
    ]
    merged["field_validation"] = {
        "status": "valid" if not validation_issues else "review_required",
        "issues": [
            {"field": issue.field, "message": issue.message, "severity": issue.severity}
            for issue in validation_issues
        ],
    }
    return merged, corrected, filled, absent, field_confidences


def _normalize(self: PassportExtractionFieldsContext, field: str, raw_value: Any) -> str:
    value = self._string_value(raw_value)
    if not value:
        return ""
    value = re.sub(r"\s+", " ", value).strip()

    if field in {"surname", "given_names"}:
        normalized = value.upper()
        allowed = all(character.isalpha() or character in " '-." for character in normalized)
        is_plausible = (
            allowed
            and any(character.isalpha() for character in normalized)
            and len(normalized) <= 100
        )
        return normalized if is_plausible else ""
    if field == "passport_number":
        normalized = re.sub(r"\s+", "", value).upper()
        return normalized if re.fullmatch(r"[A-Z0-9]{5,12}", normalized) else ""
    if field == "nationality":
        normalized = value.upper()
        return normalized if re.fullmatch(r"[A-Z]{3}", normalized) else ""
    if field == "place_of_issue":
        normalized = value.upper()
        if (
            len(normalized) > _MAX_FIELD_VALUE_CHARS
            or not any(character.isalnum() for character in normalized)
            or any(unicodedata.category(character).startswith("C") for character in normalized)
        ):
            return ""
        return normalized
    if field in {"date_of_birth", "date_of_issue", "date_of_expiry"}:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return ""
        if parsed.year < 1900 or parsed.year > 2100:
            return ""
        if field == "date_of_birth" and parsed >= date.today():
            return ""
        if field == "date_of_issue" and parsed > date.today():
            return ""
        return parsed.isoformat()
    if field == "sex":
        normalized = value.upper()
        normalized = {"MALE": "M", "FEMALE": "F", "UNSPECIFIED": "X"}.get(normalized, normalized)
        return normalized if normalized in {"M", "F", "X", "<"} else ""
    return ""


def _string_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
