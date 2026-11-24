"""
TD3 MRZ Parser
==============
Validates saved ICAO 9303 TD3 evidence for historical traveller acceptance.
This module performs no image reading, local OCR or identifier recovery.
"""

from __future__ import annotations

import re

from app.application.interfaces.mrz_parser import IMRZParser, MRZParseResult


class TD3MRZParser(IMRZParser):
    """MRZ parser for two-line passport MRZ blocks."""

    def parse(self, raw_text: str | None) -> MRZParseResult | None:
        if not raw_text:
            return None

        lines = [line.strip().replace(" ", "") for line in raw_text.splitlines() if line.strip()]
        if len(lines) < 2:
            return None

        return self._parse_lines(
            self._normalize_td3_line1_candidate(lines[-2]),
            self._normalize_mrz_line(lines[-1]),
        )

    def _parse_lines(self, line1: str, line2: str) -> MRZParseResult | None:
        if len(line1) != 44 or len(line2) != 44 or not line1.startswith("P<"):
            return None

        if not self._is_valid_td3_line2(line2):
            return None

        surname, given_names = self._parse_td3_names(line1[5:44])
        warnings = self._build_name_warnings(given_names)
        fields = self._clean_field_map(
            {
                "surname": surname,
                "given_names": given_names,
                "passport_number": line2[0:9].replace("<", ""),
                "nationality": line2[10:13].replace("<", ""),
                "issuing_country": line1[2:5].replace("<", ""),
                "date_of_birth": self._format_td3_date(line2[13:19], is_expiry=False),
                "date_of_expiry": self._format_td3_date(line2[21:27], is_expiry=True),
                "sex": line2[20].replace("<", ""),
                "personal_number": line2[28:42].rstrip("<"),
                "mrz_line_1": line1,
                "mrz_line_2": line2,
            }
        )
        return MRZParseResult(fields=fields, raw_text=f"{line1}\n{line2}", warnings=warnings)

    def _normalize_mrz_line(self, value: str) -> str:
        return value.upper().replace(" ", "").replace("\n", "")

    def _normalize_td3_line1_candidate(self, value: str) -> str:
        normalized = self._normalize_mrz_line(value)
        if normalized.startswith("P<") and 30 <= len(normalized) < 44:
            return normalized.ljust(44, "<")
        return normalized

    def _is_valid_td3_line2(self, line2: str) -> bool:
        checks = [
            (line2[0:9], line2[9]),
            (line2[13:19], line2[19]),
            (line2[21:27], line2[27]),
            (line2[28:42], line2[42]),
            (line2[0:10] + line2[13:20] + line2[21:43], line2[43]),
        ]
        return all(self._mrz_check_digit(value) == check_digit for value, check_digit in checks)

    def _mrz_check_digit(self, value: str) -> str:
        weights = [7, 3, 1]
        total = 0
        for index, char in enumerate(value):
            if char == "<":
                digit = 0
            elif char.isdigit():
                digit = int(char)
            elif "A" <= char <= "Z":
                digit = ord(char) - 55
            else:
                return "-"
            total += digit * weights[index % 3]
        return str(total % 10)

    def _parse_td3_names(self, raw_names: str) -> tuple[str | None, str | None]:
        surname_raw, _, given_raw = raw_names.partition("<<")
        return self._coalesce(surname_raw.replace("<", " ")), self._coalesce(given_raw.replace("<", " "))

    def _format_td3_date(self, value: str, *, is_expiry: bool) -> str | None:
        if not re.fullmatch(r"\d{6}", value):
            return None
        yy = int(value[0:2])
        mm = int(value[2:4])
        dd = int(value[4:6])
        if not 1 <= mm <= 12 or not 1 <= dd <= 31:
            return None
        year = 2000 + yy if is_expiry else (1900 + yy if yy > 30 else 2000 + yy)
        return f"{year:04d}-{mm:02d}-{dd:02d}"

    def _build_name_warnings(self, given_names: str | None) -> list[str]:
        if given_names and re.search(r"(HAS|H[A-Z]S)$", given_names):
            return ["Name was recovered from noisy MRZ OCR and should be reviewed against the image."]
        return []

    def _clean_field_map(self, values: dict[str, str | None]) -> dict[str, str]:
        return {key: value.strip() for key, value in values.items() if isinstance(value, str) and value.strip()}

    def _coalesce(self, value: str | None) -> str | None:
        return value.replace("<", " ").replace("  ", " ").strip() if value and value.strip() else None
