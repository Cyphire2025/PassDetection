"""
Passport Excel Importer
=======================
Reads loosely formatted passenger spreadsheets into passport submission rows.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from openpyxl import load_workbook


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass(frozen=True)
class ImportedPassportRow:
    row_number: int
    client_name: str
    client_email: str | None
    client_phone: str | None
    departure_city: str | None
    confirmed_fields: dict[str, str]


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
        },
        "client_email": {"email", "client email", "passenger email", "email address"},
        "client_phone": {"phone", "mobile", "contact", "contact no", "contact number", "client phone", "phone number"},
        "departure_city": {"departure city", "hub", "departure hub", "city"},
        "surname": {"surname", "last name"},
        "given_names": {"given names", "given name", "first name", "forename"},
        "passport_number": {"passport number", "passport no", "passport", "passport #"},
        "nationality": {"nationality"},
        "issuing_country": {"issuing country", "issue country", "country of issue"},
        "date_of_birth": {"date of birth", "dob", "birth date"},
        "date_of_expiry": {"date of expiry", "expiry date", "passport expiry", "valid until"},
        "sex": {"sex", "gender"},
    }

    FIELD_KEYS = {
        "surname",
        "given_names",
        "passport_number",
        "nationality",
        "issuing_country",
        "date_of_birth",
        "date_of_expiry",
        "sex",
    }

    def import_rows(self, content: bytes) -> list[ImportedPassportRow]:
        workbook = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        worksheet = workbook.active
        rows = list(worksheet.iter_rows(values_only=True))
        if not rows:
            return []

        header_index = self._find_header_row(rows)
        if header_index is None:
            raise ValueError("Could not find a header row in the Excel file")

        headers = self._map_headers(rows[header_index])
        imported: list[ImportedPassportRow] = []
        for row_offset, values in enumerate(rows[header_index + 1 :], start=header_index + 2):
            if not values or not any(self._stringify(value) for value in values):
                continue
            mapped = self._map_row(headers, values)
            client_name = mapped.get("client_name") or self._name_from_parts(mapped)
            if not client_name:
                continue
            confirmed_fields = {
                key: value
                for key in self.FIELD_KEYS
                if (value := mapped.get(key))
            }
            imported.append(
                ImportedPassportRow(
                    row_number=row_offset,
                    client_name=client_name[:255],
                    client_email=self._normalize_email(mapped.get("client_email")),
                    client_phone=self._limit(mapped.get("client_phone"), 32),
                    departure_city=self._limit(mapped.get("departure_city"), 120),
                    confirmed_fields=confirmed_fields,
                )
            )
        return imported

    def _find_header_row(self, rows: list[tuple[Any, ...]]) -> int | None:
        best_index: int | None = None
        best_score = 0
        for index, row in enumerate(rows[:10]):
            normalized = {self._normalize_header(value) for value in row if value is not None}
            score = sum(
                1
                for aliases in self.HEADER_ALIASES.values()
                if normalized.intersection(aliases)
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

    def _map_row(self, headers: dict[int, str], row: tuple[Any, ...]) -> dict[str, str]:
        mapped: dict[str, str] = {}
        for index, field in headers.items():
            if index >= len(row):
                continue
            value = self._stringify(row[index])
            if value:
                mapped[field] = value
        return mapped

    def _normalize_header(self, value: Any) -> str:
        return re.sub(r"[^a-z0-9#]+", " ", self._stringify(value).lower()).strip()

    def _stringify(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.date().isoformat()
        return " ".join(str(value).strip().split())

    def _name_from_parts(self, mapped: dict[str, str]) -> str:
        return " ".join(part for part in [mapped.get("given_names"), mapped.get("surname")] if part).strip()

    def _normalize_email(self, value: str | None) -> str | None:
        if not value:
            return None
        return value.lower()[:255]

    def _limit(self, value: str | None, limit: int) -> str | None:
        return value[:limit] if value else None
