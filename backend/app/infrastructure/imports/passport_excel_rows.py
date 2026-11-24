"""Canonical headers, source metadata and passenger field/value conversion."""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import date, datetime
from typing import Any

from app.domain.value_objects.passport_fields import (
    MAX_REVIEWED_FIELD_VALUE_LENGTH,
    normalize_extracted_passport_dates,
    normalize_passport_number_identity,
    normalize_passport_sex_identity,
)
from app.infrastructure.ai.passport_date_evidence import normalize_passport_date_evidence

from . import passport_excel_catalog as catalog
from .passport_excel_catalog import (
    _canonicalize_numeric_date_separators,
    _header_identity,
    _normalized_header_text,
)
from .passport_excel_records import PassportExcelImportError


class _PassportExcelRows:
    """Template methods retain dynamic self dispatch for importer overrides."""

    FIELD_KEYS = frozenset(
        {
            "surname",
            "given_names",
            "passport_number",
            "nationality",
            "place_of_issue",
            "issuing_country",
            "date_of_birth",
            "date_of_issue",
            "date_of_expiry",
            "sex",
            "staff_code",
        }
    )

    def _find_header_row(self, rows: list[tuple[Any, ...]]) -> int | None:
        best_index: int | None = None
        best_score: tuple[int, int, int] | None = None
        for index, row in enumerate(rows[:catalog.PASSPORT_EXCEL_HEADER_SCAN_ROWS]):
            matches = [
                match
                for value in row
                if (match := catalog._HEADER_ALIAS_INDEX.get(_header_identity(value))) is not None
            ]
            fields = {match.field for match in matches}
            if not fields.intersection(catalog._NAME_FIELDS):
                continue
            explicit_name_score = (
                2
                if {"given_names", "surname"}.issubset(fields)
                else 1
                if fields.intersection({"given_names", "surname"})
                else 0
            )
            score = (explicit_name_score, len(fields), len(matches))
            if best_score is None or score > best_score:
                best_score = score
                best_index = index
        return best_index

    def _map_headers(
        self,
        row: tuple[Any, ...],
        *,
        worksheet_name: str = "worksheet",
    ) -> dict[int, str]:
        selected: dict[str, tuple[int, int, str]] = {}
        for index, value in enumerate(row):
            match = catalog._HEADER_ALIAS_INDEX.get(_header_identity(value))
            if match is None:
                continue
            source_label = self._stringify(value)
            existing = selected.get(match.field)
            if existing is None or match.priority < existing[0]:
                selected[match.field] = (match.priority, index, source_label)
                continue
            if match.priority == existing[0]:
                raise PassportExcelImportError(
                    f"Ambiguous headers in worksheet {worksheet_name!r}: "
                    f"{existing[2]!r} and {source_label!r} both map to "
                    f"{match.field.replace('_', ' ')}."
                )
        return {index: field for field, (_, index, _) in selected.items()}

    def _metadata_headers(self, row: tuple[Any, ...]) -> dict[int, str]:
        """Return stable JSON keys for every populated source column."""

        keys: dict[int, str] = {}
        used: set[str] = set(catalog._RESERVED_METADATA_KEYS)
        for index, value in enumerate(row):
            source_header = self._stringify(value)
            if not source_header:
                continue
            base = re.sub(
                r"[^a-z0-9]+",
                "_",
                unicodedata.normalize("NFKC", source_header).casefold(),
            ).strip("_")
            if not base:
                base = f"column_{index + 1}"
            key = base[:64]
            suffix = 2
            while key in used:
                suffix_text = f"_{suffix}"
                key = f"{base[: 64 - len(suffix_text)]}{suffix_text}"
                suffix += 1
            used.add(key)
            keys[index] = key
        return keys

    def _map_row(
        self,
        headers: dict[int, str],
        row: tuple[str, ...],
        *,
        source_row: tuple[Any, ...],
        formula_columns: frozenset[int] = frozenset(),
    ) -> dict[str, str]:
        mapped: dict[str, str] = {}
        for index, field in headers.items():
            if index >= len(row):
                continue
            if index in formula_columns:
                continue
            value = row[index]
            if value and value.casefold() not in catalog._EXCEL_ERROR_CELL_VALUES:
                mapped[field] = value
            elif field == "surname" and (
                index >= len(source_row)
                or source_row[index] is None
                or not str(source_row[index]).strip()
            ):
                # A genuinely blank surname cell is meaningful passport data.
                # Null markers such as N/A remain absent rather than clearing it.
                mapped[field] = ""
        return mapped

    def _confirmed_fields(self, mapped: dict[str, str]) -> dict[str, str]:
        confirmed: dict[str, str] = {}
        for field, raw_value in mapped.items():
            if field not in self.FIELD_KEYS:
                continue
            if field == "surname" and raw_value == "":
                confirmed[field] = ""
                continue
            if not raw_value:
                continue
            value = raw_value
            if field in catalog._DATE_FIELDS:
                value = normalize_passport_date_evidence(
                    _canonicalize_numeric_date_separators(value),
                    field=field,
                    numeric_order="day_first",
                )
            elif field == "sex":
                value = normalize_passport_sex_identity(value)
            elif field == "passport_number":
                value = normalize_passport_number_identity(value)
                if len(value) > catalog.MAX_PASSPORT_NUMBER_LENGTH:
                    raise PassportExcelImportError(
                        "Passport number can contain at most "
                        f"{catalog.MAX_PASSPORT_NUMBER_LENGTH} letters and numbers."
                    )
            elif len(value) > MAX_REVIEWED_FIELD_VALUE_LENGTH:
                raise PassportExcelImportError(
                    f"{field.replace('_', ' ').title()} can contain at most "
                    f"{MAX_REVIEWED_FIELD_VALUE_LENGTH} characters."
                )
            if value:
                confirmed[field] = value

        return {
            key: str(value) for key, value in normalize_extracted_passport_dates(confirmed).items()
        }

    def _map_metadata_row(
        self,
        headers: dict[int, str],
        row: tuple[str, ...],
        *,
        formula_columns: frozenset[int] = frozenset(),
    ) -> dict[str, str]:
        return {
            key: value
            for index, key in headers.items()
            if index not in formula_columns
            and index < len(row)
            and (value := row[index])
        }

    def _is_repeated_header_row(
        self,
        row: tuple[Any, ...],
        headers: dict[int, str],
    ) -> bool:
        return bool(headers) and all(
            index < len(row)
            and (match := catalog._HEADER_ALIAS_INDEX.get(_header_identity(row[index]))) is not None
            and match.field == field
            for index, field in headers.items()
        )

    def _normalize_header(self, value: Any) -> str:
        return _normalized_header_text(value)

    def _stringify(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, float) and math.isfinite(value) and value.is_integer():
            # Excel commonly stores identifier-like numeric cells as floats.
            # Removing punctuation from "4779216.0" would otherwise corrupt a
            # passport number into "47792160" and leak .0 into codes/phones.
            value = int(value)
        raw_text = str(value)
        # Bound the actual source value before whitespace normalization. A cell
        # containing thousands of spaces must not evade per-cell and workbook
        # materialization limits merely because it collapses to an empty value.
        if len(raw_text) > catalog.MAX_PASSPORT_EXCEL_CELL_CHARACTERS:
            raise PassportExcelImportError(
                f"Excel cells can contain at most {catalog.MAX_PASSPORT_EXCEL_CELL_CHARACTERS} characters."
            )
        text = " ".join(raw_text.strip().split())
        return "" if text.casefold() in catalog._EMPTY_CELL_VALUES else text

    def _name_from_parts(self, mapped: dict[str, str]) -> str:
        return " ".join(
            part for part in (mapped.get("given_names"), mapped.get("surname")) if part
        ).strip()

    def _normalize_email(self, value: str | None) -> str | None:
        if not value:
            return None
        normalized = value.casefold()
        return self._bounded_value(
            normalized,
            limit=255,
            label="Email address",
        )

    def _bounded_value(
        self,
        value: str | None,
        *,
        limit: int,
        label: str,
    ) -> str | None:
        if value and len(value) > limit:
            raise PassportExcelImportError(f"{label} can contain at most {limit} characters.")
        return value or None
