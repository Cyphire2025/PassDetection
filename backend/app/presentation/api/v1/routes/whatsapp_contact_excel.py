"""Workbook header detection and accepted/rejected source-row extraction."""

from __future__ import annotations

from typing import Any

from app.presentation.api.v1.routes.whatsapp_contact_values import (
    _EMPTY_EXCEL_VALUES,
    MAX_WHATSAPP_EXCEL_HEADER_SCAN_ROWS,
    PHONE_RE,
    _clean_name,
    _excel_cell_text,
    _excel_field_key,
    _excel_header_label,
)
from app.presentation.api.v1.routes.whatsapp_imported_fields import _safe_imported_fields


def _is_excel_phone_header(label: str) -> bool:
    tokens = set(label.split())
    # "WhatsApp Email" describes its source, not a second delivery number.
    if tokens.intersection({"email", "mail"}):
        return False
    if tokens.intersection({"phone", "mobile", "whatsapp", "telephone"}):
        return True
    return "contact" in tokens and (
        len(tokens) == 1 or bool(tokens.intersection({"number", "no", "phone", "mobile"}))
    )


def _is_excel_name_header(label: str) -> bool:
    return _excel_field_key(label) == "name"


def _excel_header_columns(
    row: tuple[Any, ...],
) -> tuple[list[int], list[int], list[int], list[int]]:
    labels = [_excel_header_label(cell) for cell in row]
    field_keys = [_excel_field_key(cell) for cell in row]
    phone_columns = [
        index for index, label in enumerate(labels) if label and _is_excel_phone_header(label)
    ]
    name_columns = [
        index
        for index, label in enumerate(labels)
        if label and _is_excel_name_header(label) and index not in phone_columns
    ]
    given_name_columns = [index for index, key in enumerate(field_keys) if key == "given_names"]
    surname_columns = [index for index, key in enumerate(field_keys) if key == "surname"]
    return (
        phone_columns,
        name_columns,
        given_name_columns,
        surname_columns,
    )


def _find_excel_contact_header(
    rows: list[tuple[Any, ...]],
) -> tuple[int, list[int], list[int], list[int], list[int]] | None:
    best_match: (
        tuple[
            tuple[int, int, int],
            int,
            list[int],
            list[int],
            list[int],
            list[int],
        ]
        | None
    ) = None
    for row_index, row in enumerate(rows[:MAX_WHATSAPP_EXCEL_HEADER_SCAN_ROWS]):
        (
            phone_columns,
            name_columns,
            given_name_columns,
            surname_columns,
        ) = _excel_header_columns(row)
        if not phone_columns:
            continue
        score = (
            1 if name_columns or given_name_columns else 0,
            (
                len(phone_columns)
                + len(name_columns)
                + len(given_name_columns)
                + len(surname_columns)
            ),
            -row_index,
        )
        if best_match is None or score > best_match[0]:
            best_match = (
                score,
                row_index,
                phone_columns,
                name_columns,
                given_name_columns,
                surname_columns,
            )
    if best_match is None:
        return None
    (
        _,
        row_index,
        phone_columns,
        name_columns,
        given_name_columns,
        surname_columns,
    ) = best_match
    return (
        row_index,
        phone_columns,
        name_columns,
        given_name_columns,
        surname_columns,
    )


def _excel_name_from_row(
    row_values: list[Any],
    *,
    name_columns: list[int],
    given_name_columns: list[int],
    surname_columns: list[int],
    phone_columns: list[int],
) -> str | None:
    for index in name_columns:
        if index >= len(row_values):
            continue
        name = _clean_name(row_values[index])
        if name:
            return name
    given_name = next(
        (
            _clean_name(row_values[index])
            for index in given_name_columns
            if index < len(row_values) and _clean_name(row_values[index])
        ),
        None,
    )
    surname = next(
        (
            _clean_name(row_values[index])
            for index in surname_columns
            if index < len(row_values) and _clean_name(row_values[index])
        ),
        None,
    )
    composed = " ".join(part for part in (given_name, surname) if part)
    if composed:
        return composed
    if name_columns or given_name_columns or surname_columns:
        return None
    for index, value in enumerate(row_values):
        if index in phone_columns:
            continue
        name = _clean_name(value)
        if name and any(character.isalpha() for character in name) and not PHONE_RE.search(name):
            return name
    return None


def _excel_raw_name_from_row(
    row_values: list[Any],
    *,
    name_columns: list[int],
    given_name_columns: list[int],
    surname_columns: list[int],
    phone_columns: list[int],
) -> str | None:
    for index in name_columns:
        if index >= len(row_values):
            continue
        if value := _excel_cell_text(row_values[index]):
            return value[:256]
    given_name = next(
        (
            _excel_cell_text(row_values[index])
            for index in given_name_columns
            if index < len(row_values) and _excel_cell_text(row_values[index])
        ),
        None,
    )
    surname = next(
        (
            _excel_cell_text(row_values[index])
            for index in surname_columns
            if index < len(row_values) and _excel_cell_text(row_values[index])
        ),
        None,
    )
    composed = " ".join(part for part in (given_name, surname) if part)
    if composed:
        return composed[:256]
    if name_columns or given_name_columns or surname_columns:
        return None
    for index, value in enumerate(row_values):
        if index in phone_columns:
            continue
        text = _excel_cell_text(value)
        if text and any(character.isalpha() for character in text) and not PHONE_RE.search(text):
            return text[:256]
    return None


def _bounded_excel_raw_value(value: Any, *, max_length: int) -> str | None:
    text = _excel_cell_text(value)
    if not text or _excel_header_label(text) in _EMPTY_EXCEL_VALUES:
        return None
    return text[:max_length]


def _is_repeated_excel_header(
    row_values: list[Any],
    header_row: tuple[Any, ...],
) -> bool:
    identity_keys = {"given_names", "name", "phone_number", "surname"}

    def identity_signature(values: list[Any] | tuple[Any, ...]) -> tuple[tuple[int, str], ...]:
        return tuple(
            (index, key)
            for index, value in enumerate(values)
            if (key := _excel_field_key(value)) in identity_keys
        )

    header_signature = identity_signature(header_row)
    row_signature = identity_signature(row_values)
    header_keys = {key for _, key in header_signature}
    return (
        "phone_number" in header_keys
        and bool(header_keys & {"given_names", "name"})
        and row_signature == header_signature
    )


def _row_has_contact_identity(
    *,
    name: str | None,
    imported_fields: dict[str, str],
) -> bool:
    if name:
        return True
    return bool(
        imported_fields.keys()
        & {
            "agent_code",
            "email",
            "passport_number",
            "staff_code",
        }
    )


def _excel_fields_from_row(
    *,
    header_row: tuple[Any, ...],
    row_values: list[Any],
    sheet_name: str,
    source_file_name: str,
    row_number: int,
    source_order: int,
) -> dict[str, str]:
    fields: dict[str, str] = {}
    for index, raw_header in enumerate(header_row):
        if index >= len(row_values):
            continue
        key = _excel_field_key(raw_header)
        text_value = _excel_cell_text(row_values[index])
        if not key or not text_value or _excel_header_label(text_value) in _EMPTY_EXCEL_VALUES:
            continue
        fields.setdefault(key, text_value)
    fields.setdefault("source_file", source_file_name)
    fields.setdefault("source_order", str(source_order))
    fields.setdefault("source_sheet", sheet_name)
    fields.setdefault("source_row", str(row_number))
    return _safe_imported_fields(fields)
