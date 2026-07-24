"""
Passport Excel Importer
=======================
Reads loosely formatted passenger spreadsheets into passport submission rows.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from openpyxl import load_workbook

from app.domain.value_objects.passport_fields import normalize_extracted_passport_dates


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True)
class ImportedPassportRow:
    row_number: int
    worksheet_name: str
    client_name: str
    client_email: str | None
    client_phone: str | None
    departure_city: str | None
    nearest_domestic_airport: str | None
    confirmed_fields: dict[str, str]
    staff_metadata: dict[str, str]


class PassportExcelImporter:
    HEADER_ALIASES = {
        "client_name": {
            "client name",
            "passenger name",
            "passenger",
            "name",
            "full name",
            "guest name",
            "traveller name",
            "traveler name",
            "staffname",
            "staff name",
        },
        "client_email": {"email", "client email", "passenger email", "email address"},
        "client_phone": {
            "phone",
            "mobile",
            "contact",
            "contact no",
            "contact number",
            "client phone",
            "phone number",
        },
        "departure_city": {"departure city", "hub", "departure hub", "city"},
        "nearest_domestic_airport": {
            "nearest domestic airport",
            "domestic airport",
            "nearest airport domestic",
        },
        "surname": {"surname", "last name"},
        "given_names": {"given names", "given name", "first name", "forename"},
        "passport_number": {"passport number", "passport no", "passport", "passport #"},
        "nationality": {"nationality"},
        "place_of_issue": {
            "place of issue",
            "place of issuance",
        },
        "issuing_country": {
            # Preserve legacy imports under their original meaning. These
            # values are not Place of Issue and are never AI-verified as such.
            "issuing country",
            "issue country",
            "country of issue",
        },
        "date_of_birth": {
            "date of birth",
            "dob",
            "birth date",
            "birthdate",
        },
        "date_of_issue": {
            "date of issue",
            "doi",
            "issue date",
            "passport issue",
            "passport issue date",
        },
        "date_of_expiry": {
            "date of expiry",
            "date of expiration",
            "doe",
            "expiry",
            "expiry date",
            "expiration date",
            "passport expiry",
            "passport expiry date",
            "valid until",
        },
        "sex": {"sex", "gender"},
        "staff_code": {"staffcode", "staff code", "employee code", "employee id"},
    }

    FIELD_KEYS = {
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

    def import_rows(self, content: bytes) -> list[ImportedPassportRow]:
        workbook = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        imported: list[ImportedPassportRow] = []
        readable_sheet_count = 0
        for worksheet in workbook.worksheets:
            rows = list(worksheet.iter_rows(values_only=True))
            if not rows:
                continue
            header_index = self._find_header_row(rows)
            if header_index is None:
                continue
            readable_sheet_count += 1
            headers = self._map_headers(rows[header_index])
            metadata_headers = self._metadata_headers(rows[header_index])
            for row_offset, values in enumerate(rows[header_index + 1 :], start=header_index + 2):
                if not values or not any(self._stringify(value) for value in values):
                    continue
                mapped = self._map_row(headers, values)
                client_name = mapped.get("client_name") or self._name_from_parts(mapped)
                if not client_name:
                    continue
                confirmed_fields = {
                    key: value for key in self.FIELD_KEYS if (value := mapped.get(key))
                }
                confirmed_fields = {
                    key: str(value)
                    for key, value in normalize_extracted_passport_dates(confirmed_fields).items()
                }
                staff_metadata = self._map_metadata_row(metadata_headers, values)
                if mapped.get("staff_code"):
                    staff_metadata.setdefault("staff_code", mapped["staff_code"])
                staff_metadata["source_sheet"] = worksheet.title
                # A zone heading is not guaranteed in third-party templates;
                # the worksheet name remains a reliable grouping fallback.
                staff_metadata["source_zone"] = staff_metadata.get("zone_name") or worksheet.title
                imported.append(
                    ImportedPassportRow(
                        row_number=row_offset,
                        worksheet_name=worksheet.title,
                        client_name=client_name[:255],
                        client_email=self._normalize_email(mapped.get("client_email")),
                        client_phone=self._limit(mapped.get("client_phone"), 32),
                        departure_city=self._limit(mapped.get("departure_city"), 120),
                        nearest_domestic_airport=self._limit(
                            mapped.get("nearest_domestic_airport"),
                            120,
                        ),
                        confirmed_fields=confirmed_fields,
                        staff_metadata=staff_metadata,
                    )
                )
        if not readable_sheet_count:
            raise ValueError("Could not find a header row in any worksheet of the Excel file")
        return imported

    def _find_header_row(self, rows: list[tuple[Any, ...]]) -> int | None:
        best_index: int | None = None
        best_score = 0
        for index, row in enumerate(rows[:10]):
            normalized = {self._normalize_header(value) for value in row if value is not None}
            score = sum(
                1 for aliases in self.HEADER_ALIASES.values() if normalized.intersection(aliases)
            )
            if score > best_score:
                best_score = score
                best_index = index
        return best_index if best_score > 0 else None

    def _map_headers(self, row: tuple[Any, ...]) -> dict[int, str]:
        mapped: dict[int, str] = {}
        for index, value in enumerate(row):
            header = self._normalize_header(value)
            if not header:
                continue
            for field, aliases in self.HEADER_ALIASES.items():
                if header in aliases:
                    mapped[index] = field
                    break
        return mapped

    def _metadata_headers(self, row: tuple[Any, ...]) -> dict[int, str]:
        """Return stable JSON keys for every populated source column.

        The original workbook headings are intentionally not discarded: a company
        can add a new grouping column without requiring a deployment first.
        """
        keys: dict[int, str] = {}
        used: set[str] = set()
        for index, value in enumerate(row):
            base = re.sub(r"[^a-z0-9]+", "_", self._stringify(value).lower()).strip("_")
            if not base:
                continue
            key = base[:64]
            suffix = 2
            while key in used:
                key = f"{base[:58]}_{suffix}"
                suffix += 1
            used.add(key)
            keys[index] = key
        return keys

    def _map_row(self, headers: dict[int, str], row: tuple[Any, ...]) -> dict[str, str]:
        mapped: dict[str, str] = {}
        for index, field in headers.items():
            if index >= len(row):
                continue
            value = self._stringify(row[index])
            if value:
                mapped[field] = value
        return mapped

    def _map_metadata_row(self, headers: dict[int, str], row: tuple[Any, ...]) -> dict[str, str]:
        return {
            key: value
            for index, key in headers.items()
            if index < len(row) and (value := self._stringify(row[index]))
        }

    def _normalize_header(self, value: Any) -> str:
        return re.sub(r"[^a-z0-9#]+", " ", self._stringify(value).lower()).strip()

    def _stringify(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        text = " ".join(str(value).strip().split())
        return "" if text.lower() in {"null", "n/a", "na", "none", "-"} else text

    def _name_from_parts(self, mapped: dict[str, str]) -> str:
        return " ".join(
            part for part in [mapped.get("given_names"), mapped.get("surname")] if part
        ).strip()

    def _normalize_email(self, value: str | None) -> str | None:
        if not value:
            return None
        return value.lower()[:255]

    def _limit(self, value: str | None, limit: int) -> str | None:
        return value[:limit] if value else None
