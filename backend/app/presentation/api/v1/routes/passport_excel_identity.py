"""Canonical Excel identity evidence, existing-passenger indexes and safe resolution."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.domain.value_objects.passport_fields import (
    normalize_passport_number_identity,
)
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.imports.passport_excel_importer import ImportedPassportRow


def _excel_identity_key(name: str | None, email: str | None, phone: str | None) -> str:
    parts = [name or "", email or "", phone or ""]
    return "|".join(part.strip().casefold() for part in parts)


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
