"""Deterministic identity and merge support for passport Excel imports."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar

from app.domain.value_objects.passport_fields import (
    normalize_passport_number_identity,
    reconcile_confirmed_with_extraction,
)
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.imports.passport_excel_importer import ImportedPassportRow


def _excel_identity_key(name: str | None, email: str | None, phone: str | None) -> str:
    parts = [name or "", email or "", phone or ""]
    return "|".join(part.strip().casefold() for part in parts)


_FieldValue = TypeVar("_FieldValue")


def _merge_excel_fields(
    existing: Mapping[str, _FieldValue] | None,
    imported: Mapping[str, _FieldValue],
) -> dict[str, _FieldValue] | None:
    if not existing:
        return dict(imported) or None
    merged = dict(existing)
    for key, value in imported.items():
        if value not in (None, "") or key == "surname":
            merged[key] = value
    return merged


def _staff_code_for_submission(submission: PassportSubmissionModel) -> str | None:
    metadata = getattr(submission, "staff_metadata", None) or {}
    fields = submission.confirmed_fields or submission.extracted_fields or {}
    value = metadata.get("staff_code") or fields.get("staff_code")
    return str(value).strip().upper() if value else None


class _PassportExcelImportConflict(ValueError):
    """Unsafe or ambiguous identity evidence encountered during Excel import."""


@dataclass(frozen=True)
class _PassportExcelExistingIndexes:
    by_passport_number: dict[str, PassportSubmissionModel]
    by_staff_code: dict[str, PassportSubmissionModel]
    by_identity: dict[str, tuple[PassportSubmissionModel, ...]]


def _excel_scalar_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return " ".join(unicodedata.normalize("NFKC", str(value)).strip().split())


def _canonical_excel_staff_code(value: Any) -> str | None:
    normalized = _excel_scalar_text(value).upper()
    return normalized or None


def _canonical_excel_passport_number(value: Any) -> str | None:
    normalized = normalize_passport_number_identity(_excel_scalar_text(value))
    return normalized or None


def _preferred_submission_value(
    submission: PassportSubmissionModel,
    *,
    field: str,
    include_metadata: bool,
    normalizer: Callable[[object], str | None],
) -> str | None:
    """Resolve identity using the domain's reviewed-over-extracted precedence."""

    for attribute in ("confirmed_fields", "extracted_fields"):
        fields = getattr(submission, attribute, None) or {}
        if normalized := normalizer(fields.get(field)):
            return normalized
    if include_metadata:
        metadata = getattr(submission, "staff_metadata", None) or {}
        if normalized := normalizer(metadata.get(field)):
            return normalized
    return None


def _strict_passport_number_for_submission(
    submission: PassportSubmissionModel,
) -> str | None:
    return _preferred_submission_value(
        submission,
        field="passport_number",
        include_metadata=False,
        normalizer=_canonical_excel_passport_number,
    )


def _strict_staff_code_for_submission(
    submission: PassportSubmissionModel,
) -> str | None:
    return _preferred_submission_value(
        submission,
        field="staff_code",
        include_metadata=True,
        normalizer=_canonical_excel_staff_code,
    )


def _same_passport_submission(
    first: PassportSubmissionModel,
    second: PassportSubmissionModel,
) -> bool:
    if first is second:
        return True
    first_id = getattr(first, "id", None)
    second_id = getattr(second, "id", None)
    return first_id is not None and first_id == second_id


def _build_passport_excel_existing_indexes(
    submissions: list[PassportSubmissionModel],
) -> _PassportExcelExistingIndexes:
    by_passport_number: dict[str, PassportSubmissionModel] = {}
    by_staff_code: dict[str, PassportSubmissionModel] = {}
    by_identity_lists: dict[str, list[PassportSubmissionModel]] = {}
    for submission in submissions:
        passport_number = _strict_passport_number_for_submission(submission)
        if passport_number:
            prior = by_passport_number.get(passport_number)
            if prior is not None and not _same_passport_submission(prior, submission):
                raise _PassportExcelImportConflict(
                    "Multiple existing passengers share a passport number; "
                    "resolve the group data before importing."
                )
            by_passport_number[passport_number] = submission

        staff_code = _strict_staff_code_for_submission(submission)
        if staff_code:
            prior = by_staff_code.get(staff_code)
            if prior is not None and not _same_passport_submission(prior, submission):
                raise _PassportExcelImportConflict(
                    "Multiple existing passengers share a staff code; "
                    "resolve the group data before importing."
                )
            by_staff_code[staff_code] = submission

        identity = _excel_identity_key(
            submission.client_name,
            submission.client_email,
            submission.client_phone,
        )
        by_identity_lists.setdefault(identity, []).append(submission)

    return _PassportExcelExistingIndexes(
        by_passport_number=by_passport_number,
        by_staff_code=by_staff_code,
        by_identity={
            identity: tuple(candidates) for identity, candidates in by_identity_lists.items()
        },
    )


def _passport_number_for_import_row(row: ImportedPassportRow) -> str | None:
    return _canonical_excel_passport_number(row.confirmed_fields.get("passport_number"))


def _staff_code_for_import_row(row: ImportedPassportRow) -> str | None:
    return _canonical_excel_staff_code(
        (row.staff_metadata or {}).get("staff_code") or row.confirmed_fields.get("staff_code")
    )


def _normalized_excel_mapping_items(
    values: dict[str, str],
    *,
    excluded_keys: frozenset[str] = frozenset(),
) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (
                _excel_scalar_text(key).casefold(),
                _excel_scalar_text(value).casefold(),
            )
            for key, value in values.items()
            if key not in excluded_keys
        )
    )


def _passport_excel_row_fingerprint(row: ImportedPassportRow) -> tuple[Any, ...]:
    return (
        _excel_identity_key(row.client_name, row.client_email, row.client_phone),
        _excel_scalar_text(row.departure_city).casefold(),
        _excel_scalar_text(row.nearest_domestic_airport).casefold(),
        _normalized_excel_mapping_items(row.confirmed_fields),
        _normalized_excel_mapping_items(
            row.staff_metadata,
            excluded_keys=frozenset({"source_sheet", "source_zone"}),
        ),
    )


def _deduplicate_passport_excel_rows(
    rows: list[ImportedPassportRow],
) -> list[ImportedPassportRow]:
    unique_rows: list[ImportedPassportRow] = []
    by_passport: dict[str, tuple[tuple[Any, ...], int]] = {}
    by_staff: dict[str, tuple[tuple[Any, ...], int]] = {}
    weak_by_identity: dict[str, tuple[tuple[Any, ...], int]] = {}
    first_strong_by_identity: dict[str, tuple[tuple[Any, ...], int]] = {}
    differing_strong_by_identity: dict[str, tuple[tuple[Any, ...], int]] = {}

    for row in rows:
        passport_number = _passport_number_for_import_row(row)
        staff_code = _staff_code_for_import_row(row)
        identity = _excel_identity_key(
            row.client_name,
            row.client_email,
            row.client_phone,
        )
        fingerprint = _passport_excel_row_fingerprint(row)
        duplicate = False

        if passport_number and (prior := by_passport.get(passport_number)):
            if prior[0] != fingerprint:
                raise _PassportExcelImportConflict(
                    f"Rows {prior[1]} and {row.row_number} assign the same passport "
                    "number to conflicting passenger details."
                )
            duplicate = True
        if staff_code and (prior := by_staff.get(staff_code)):
            if prior[0] != fingerprint:
                raise _PassportExcelImportConflict(
                    f"Rows {prior[1]} and {row.row_number} assign the same staff "
                    "code to conflicting passenger details."
                )
            duplicate = True

        has_strong_key = bool(passport_number or staff_code)
        if has_strong_key:
            prior_weak = weak_by_identity.get(identity)
            if prior_weak is not None and prior_weak[0] != fingerprint:
                raise _PassportExcelImportConflict(
                    f"Rows {prior_weak[1]} and {row.row_number} have an ambiguous "
                    "passenger identity."
                )
            if prior_weak is not None:
                duplicate = True
        else:
            prior_weak = weak_by_identity.get(identity)
            if prior_weak is not None:
                if prior_weak[0] != fingerprint:
                    raise _PassportExcelImportConflict(
                        f"Rows {prior_weak[1]} and {row.row_number} have an ambiguous "
                        "passenger identity."
                    )
                duplicate = True

            prior_strong = first_strong_by_identity.get(identity)
            if prior_strong is not None:
                conflicting_strong = (
                    prior_strong
                    if prior_strong[0] != fingerprint
                    else differing_strong_by_identity.get(identity)
                )
                if conflicting_strong is not None:
                    raise _PassportExcelImportConflict(
                        f"Rows {conflicting_strong[1]} and {row.row_number} have an "
                        "ambiguous passenger identity."
                    )
                duplicate = True

        if duplicate:
            continue
        unique_rows.append(row)
        if passport_number:
            by_passport[passport_number] = (fingerprint, row.row_number)
        if staff_code:
            by_staff[staff_code] = (fingerprint, row.row_number)
        if has_strong_key:
            first_strong = first_strong_by_identity.setdefault(
                identity,
                (fingerprint, row.row_number),
            )
            if first_strong[0] != fingerprint:
                differing_strong_by_identity.setdefault(
                    identity,
                    (fingerprint, row.row_number),
                )
        else:
            weak_by_identity[identity] = (fingerprint, row.row_number)
    return unique_rows


def _resolve_existing_passport_excel_submission(
    row: ImportedPassportRow,
    indexes: _PassportExcelExistingIndexes,
) -> PassportSubmissionModel | None:
    passport_number = _passport_number_for_import_row(row)
    staff_code = _staff_code_for_import_row(row)
    passport_match = indexes.by_passport_number.get(passport_number) if passport_number else None
    staff_match = indexes.by_staff_code.get(staff_code) if staff_code else None
    if (
        passport_match is not None
        and staff_match is not None
        and not _same_passport_submission(passport_match, staff_match)
    ):
        raise _PassportExcelImportConflict(
            "A workbook row's passport number and staff code identify different "
            "existing passengers."
        )
    if passport_match is not None or staff_match is not None:
        strong_match = passport_match or staff_match
        if strong_match is None:  # Defensive narrowing for static analyzers.
            return None
        existing_passport = _strict_passport_number_for_submission(strong_match)
        existing_staff_code = _strict_staff_code_for_submission(strong_match)
        if passport_number and existing_passport and passport_number != existing_passport:
            raise _PassportExcelImportConflict(
                "A workbook row's staff code matches an existing passenger, but "
                "its passport number conflicts with that passenger."
            )
        if staff_code and existing_staff_code and staff_code != existing_staff_code:
            raise _PassportExcelImportConflict(
                "A workbook row's passport number matches an existing passenger, "
                "but its staff code conflicts with that passenger."
            )
        return strong_match

    identity = _excel_identity_key(
        row.client_name,
        row.client_email,
        row.client_phone,
    )
    identity_matches = indexes.by_identity.get(identity, ())
    if len(identity_matches) > 1:
        raise _PassportExcelImportConflict(
            "A workbook row matches multiple existing passengers by legacy name/contact identity."
        )
    if not identity_matches:
        return None

    identity_match = identity_matches[0]
    existing_passport = _strict_passport_number_for_submission(identity_match)
    existing_staff_code = _strict_staff_code_for_submission(identity_match)
    if passport_number and existing_passport and passport_number != existing_passport:
        raise _PassportExcelImportConflict(
            "A workbook row conflicts with the passport number stored for its "
            "legacy name/contact match."
        )
    if staff_code and existing_staff_code and staff_code != existing_staff_code:
        raise _PassportExcelImportConflict(
            "A workbook row conflicts with the staff code stored for its legacy name/contact match."
        )
    return identity_match


def _apply_passport_excel_row_to_submission(
    submission: PassportSubmissionModel,
    row: ImportedPassportRow,
    *,
    now: datetime,
) -> None:
    submission.client_name = row.client_name
    if row.client_email is not None:
        submission.client_email = row.client_email
    if row.client_phone is not None:
        submission.client_phone = row.client_phone
    if row.departure_city is not None:
        submission.departure_city = row.departure_city
    if row.nearest_domestic_airport is not None:
        submission.nearest_domestic_airport = row.nearest_domestic_airport
    submission.staff_metadata = {
        **(submission.staff_metadata or {}),
        **(row.staff_metadata or {}),
    } or None
    merged_confirmed_fields = _merge_excel_fields(
        submission.confirmed_fields,
        row.confirmed_fields,
    )
    merged_extracted_fields = _merge_excel_fields(
        submission.extracted_fields,
        row.confirmed_fields,
    )
    submission.extracted_fields = merged_extracted_fields
    submission.confirmed_fields, submission.extraction_conflicts = (
        reconcile_confirmed_with_extraction(
            merged_confirmed_fields,
            merged_extracted_fields or {},
        )
    )
    submission.confidence_score = {
        **(submission.confidence_score or {}),
        "source": "excel_import",
        "row_number": row.row_number,
        "source_sheet": row.worksheet_name,
        "updated_from_excel": True,
    }
    submission.overall_confidence = (
        submission.overall_confidence
        if submission.overall_confidence is not None
        else (1.0 if row.confirmed_fields else None)
    )
    submission.updated_at = now
