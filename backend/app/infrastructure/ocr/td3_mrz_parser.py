"""
TD3 MRZ Parser
==============
Parses ICAO 9303 TD3 passport MRZ lines with checksum validation and bounded
OCR recovery for common character confusions.
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

    def parse_from_ocr_text(self, text: str) -> MRZParseResult | None:
        for line1, line2 in self._find_td3_mrz_candidates(text):
            result = self._parse_lines(line1, line2)
            if result:
                return result
        return None

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

    def _find_td3_mrz_candidates(self, text: str) -> list[tuple[str, str]]:
        normalized = (
            text.upper()
            .replace(" ", "")
            .replace("\n", "")
            .replace("{", "P<")
            .replace("[", "P<")
        )
        tokens = re.findall(r"[A-Z0-9<]{12,}", normalized)
        candidates: list[tuple[str, str]] = []

        for index, token in enumerate(tokens):
            if token.startswith("P<") and len(token) >= 30:
                line1 = self._normalize_td3_line1_candidate(token[:44])
                for next_token in tokens[index + 1:index + 4]:
                    if len(next_token) >= 44:
                        candidates.append((line1, self._normalize_mrz_line(next_token[:44])))
                        break

        for index, token in enumerate(tokens):
            for prefix, line2 in self._recover_td3_line2_windows(token):
                recovered_line1 = self._recover_td3_line1([*tokens[:index], prefix], line2)
                if recovered_line1:
                    candidates.append((recovered_line1, line2))

        return candidates

    def _normalize_mrz_line(self, value: str) -> str:
        return value.upper().replace(" ", "").replace("\n", "")

    def _normalize_td3_line1_candidate(self, value: str) -> str:
        normalized = self._normalize_mrz_line(value)
        if normalized.startswith("P<") and 30 <= len(normalized) < 44:
            return normalized.ljust(44, "<")
        return normalized

    def _recover_td3_line2_windows(self, token: str) -> list[tuple[str, str]]:
        candidates: list[tuple[str, str]] = []
        if len(token) < 44:
            return candidates

        for start in range(0, len(token) - 43):
            window = token[start:start + 44]
            corrected = self._correct_td3_line2(window)
            for variant in self._td3_line2_variants(corrected):
                if self._is_valid_td3_line2(variant):
                    candidates.append((token[:start], variant))
                    break

        return candidates

    def _td3_line2_variants(self, line2: str) -> list[str]:
        variants = [line2[:10] + nationality + line2[13:] for nationality in self._country_code_variants(line2[10:13])]
        expanded: list[str] = []
        for variant in variants:
            for birth_date in self._date_field_variants(variant[13:19], variant[19], is_expiry=False):
                with_birth_date = variant[:13] + birth_date + variant[19:]
                for expiry_date in self._date_field_variants(with_birth_date[21:27], with_birth_date[27], is_expiry=True):
                    expanded.append(with_birth_date[:21] + expiry_date + with_birth_date[27:])
        return expanded

    def _country_code_variants(self, value: str) -> list[str]:
        known_codes = ("IND",)
        variants: list[str] = []
        for code in known_codes:
            distance = sum(1 for current, expected in zip(value, code) if current != expected)
            if value == code or distance <= 1:
                variants.append(code)
        variants.append(value)
        return list(dict.fromkeys(variants))

    def _date_field_variants(self, value: str, check_digit: str, *, is_expiry: bool) -> list[str]:
        variants = [value]
        if self._mrz_check_digit(value) == check_digit and self._format_td3_date(value, is_expiry=is_expiry):
            return variants

        for index, char in enumerate(value):
            for replacement in "0123456789":
                if replacement == char:
                    continue
                candidate = value[:index] + replacement + value[index + 1:]
                if self._mrz_check_digit(candidate) == check_digit and self._format_td3_date(candidate, is_expiry=is_expiry):
                    variants.append(candidate)
        return variants

    def _correct_td3_line2(self, value: str) -> str:
        chars = list(self._normalize_mrz_line(value))
        digit_positions = set(range(13, 20)) | set(range(21, 28)) | {9, 19, 27, 42, 43}
        alpha_positions = set(range(10, 13))

        for index, char in enumerate(chars):
            if index in digit_positions:
                chars[index] = self._normalize_mrz_digit(char)
            elif index in alpha_positions:
                chars[index] = self._normalize_mrz_alpha(char)
            elif index == 20 and char not in {"M", "F", "<"}:
                chars[index] = "F" if char in {"7", "E", "P"} else "<"
        return "".join(chars)

    def _recover_td3_line1(self, previous_tokens: list[str], line2: str) -> str | None:
        nationality = line2[10:13]
        for token in reversed(previous_tokens[-6:]):
            candidate = self._correct_td3_line1(token, nationality)
            if candidate:
                return candidate
        return None

    def _correct_td3_line1(self, token: str, nationality: str) -> str | None:
        normalized = self._normalize_mrz_line(token).replace("{", "P<").replace("[", "P<")
        if "<<" not in normalized:
            return None

        payload = normalized.rsplit("P<", 1)[1] if "P<" in normalized else normalized
        if len(payload) >= 3:
            payload_country = "".join(self._normalize_mrz_alpha(char) for char in payload[:3])
            country_distance = sum(1 for current, expected in zip(payload_country, nationality) if current != expected)
            names = payload[3:] if payload_country == nationality or country_distance <= 1 else payload
        else:
            names = payload

        names = self._normalize_td3_name_payload(names)
        line1 = f"P<{nationality}{names}"
        return line1[:44].ljust(44, "<") if len(line1) >= 8 else None

    def _normalize_td3_name_payload(self, value: str) -> str:
        chars: list[str] = []
        seen_separator = False
        for char in value:
            if char == "<":
                chars.append("<")
                if len(chars) >= 2 and chars[-2:] == ["<", "<"]:
                    seen_separator = True
                continue
            if char.isdigit() and seen_separator:
                chars.append("<")
                continue
            if char.isalpha():
                chars.append(char)
        return "".join(chars)

    def _normalize_mrz_digit(self, char: str) -> str:
        return {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "G": "6", "T": "7", "B": "8"}.get(char, char)

    def _normalize_mrz_alpha(self, char: str) -> str:
        return {"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B"}.get(char, char)

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
