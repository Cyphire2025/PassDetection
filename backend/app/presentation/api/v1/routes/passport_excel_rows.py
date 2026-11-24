"""Deterministic workbook fingerprints and indexed duplicate/conflict selection."""

from __future__ import annotations

from typing import Any

from app.infrastructure.imports.passport_excel_importer import ImportedPassportRow
from app.presentation.api.v1.routes.passport_excel_identity import (
    _excel_identity_key,
    _excel_scalar_text,
    _passport_number_for_import_row,
    _PassportExcelImportConflict,
    _staff_code_for_import_row,
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
