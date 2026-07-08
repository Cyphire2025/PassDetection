"""ICAO TD3 name-field normalization."""

from __future__ import annotations

from dataclasses import dataclass

from app.infrastructure.ocr.correction.character_normalizer import CharacterNormalizer


@dataclass(frozen=True)
class NameNormalization:
    line1: str
    surname: str
    given_names: str
    reason: str
    confidence: float


class NameNormalizer:
    """Normalizes TD3 line-1 names without inventing missing names."""

    def __init__(self, normalizer: CharacterNormalizer | None = None) -> None:
        self._normalizer = normalizer or CharacterNormalizer()

    def normalize_line1(self, raw_line1: str, issuing_country: str) -> NameNormalization:
        sanitized = self._normalizer.sanitize_mrz_text(raw_line1)
        payload = self._extract_payload(sanitized, issuing_country)
        payload = self._recover_name_separator(payload)
        payload = self._normalizer.name_payload(payload)
        payload = self._normalize_filler_runs(payload)
        surname, given_names = self._split_names(payload)
        line1_payload = self._line1_payload(surname, given_names)
        line1 = f"P<{issuing_country}{line1_payload}"[:44].ljust(44, "<")
        changed = line1 not in {sanitized[:44].ljust(44, "<"), sanitized.ljust(44, "<")[:44]}
        return NameNormalization(
            line1=line1,
            surname=surname,
            given_names=given_names,
            reason="name_payload_normalized" if changed else "unchanged",
            confidence=0.90 if surname and given_names else 0.55,
        )

    def _extract_payload(self, value: str, issuing_country: str) -> str:
        start = value.find("P<")
        if start >= 0:
            payload = value[start + 2 :]
        elif value.startswith("P") and len(value) > 1 and value[1] in {"<", "C", "E", "K", "S", "5"}:
            payload = value[2:]
        else:
            payload = value
        country = self._normalizer.country_code(payload[:3])
        if country == issuing_country or self._distance(country, issuing_country) <= 1:
            payload = payload[3:]
        # A shifted line start can duplicate the issuing country at the name
        # boundary (for example NDIINDVASHISTHA). Remove only the rotated
        # country fragment when it is immediately followed by the exact code.
        elif (
            len(payload) >= 6
            and payload[3:6] == issuing_country
            and sorted(payload[:3]) == sorted(issuing_country)
        ):
            payload = payload[6:]
        return payload

    @staticmethod
    def _normalize_filler_runs(value: str) -> str:
        while "<<<" in value:
            value = value.replace("<<<", "<<")
        if "<<" in value:
            surname, given = value.split("<<", 1)
            given = NameNormalizer._strip_trailing_filler_noise(given.rstrip("<"))
            return f"{surname}<<{given}" if given else f"{surname}<<"
        return value.rstrip("<")

    @staticmethod
    def _recover_name_separator(value: str) -> str:
        existing_separator = value.find("<<")
        if 1 < existing_separator <= 25 and NameNormalizer._has_alpha_after(value, existing_separator + 2):
            return value
        separator_chars = {"<", "C", "E", "K", "S", "5"}
        for index in range(2, len(value) - 3):
            pair = value[index:index + 2]
            if pair[0] == "<":
                continue
            if set(pair).issubset(separator_chars) and value[index - 1].isalpha() and value[index + 2].isalpha():
                left = value[:index]
                right = value[index + 2:]
                if len(NameNormalizer._letters(left)) >= 2 and len(NameNormalizer._letters(right)) >= 2:
                    return f"{left}<<{right}"
        single_separator = NameNormalizer._recover_single_separator(value)
        if single_separator:
            return single_separator
        return value

    @staticmethod
    def _recover_single_separator(value: str) -> str | None:
        padding_start = NameNormalizer._first_padding_run(value)
        if padding_start is not None:
            value = value[:padding_start]
        last_alpha = max((index for index, char in enumerate(value) if char.isalpha()), default=-1)
        if last_alpha < 0:
            return None
        payload = value[:last_alpha + 1]
        if len(payload) < 5 or "<<" in payload:
            return None

        for index in range(2, len(payload) - 2):
            if payload[index] == "<" and payload[index - 1].isalpha() and payload[index + 1].isalpha():
                left = payload[:index]
                right = payload[index + 1:]
                if len(NameNormalizer._letters(left)) >= 2 and len(NameNormalizer._letters(right)) >= 2:
                    return f"{left}<<{right}"

        if payload.count("X") == 1:
            index = payload.index("X")
            left = payload[:index]
            right = payload[index + 1:]
            if len(NameNormalizer._letters(left)) >= 2 and len(NameNormalizer._letters(right)) >= 2:
                return f"{left}<<{right}"
        return None

    @staticmethod
    def _has_alpha_after(value: str, start: int) -> bool:
        return any(char.isalpha() for char in value[start:])

    @staticmethod
    def _first_padding_run(value: str) -> int | None:
        filler_chars = {"<", "K", "S", "5", "E", "6"}
        for index in range(2, len(value) - 2):
            if all(char in filler_chars for char in value[index:index + 3]):
                return index
        return None

    @staticmethod
    def _strip_trailing_filler_noise(value: str) -> str:
        filler_chars = {"<", "K", "S", "5", "E", "6"}
        for index in range(2, len(value) - 2):
            run = value[index:index + 3]
            if all(char in filler_chars for char in run):
                return value[:index].rstrip("<")
        return value

    @staticmethod
    def _split_names(payload: str) -> tuple[str, str]:
        surname_raw, separator, given_raw = payload.partition("<<")
        if not separator:
            return NameNormalizer._letters(surname_raw), ""
        given_parts = [part for part in (NameNormalizer._letters(part) for part in given_raw.split("<")) if part]
        given_parts = NameNormalizer._remove_leading_noise_initial(given_parts)
        return NameNormalizer._letters(surname_raw), " ".join(given_parts)

    @staticmethod
    def _remove_leading_noise_initial(parts: list[str]) -> list[str]:
        noise_initials = {"C", "E", "K", "S", "X"}
        if len(parts) >= 2 and parts[0] in noise_initials and len(parts[1]) >= 2:
            return parts[1:]
        if len(parts) == 1 and len(parts[0]) >= 4 and parts[0].startswith("X"):
            return [parts[0][1:]]
        return parts

    @staticmethod
    def _line1_payload(surname: str, given_names: str) -> str:
        surname_payload = surname.replace(" ", "<")
        given_payload = given_names.replace(" ", "<")
        return f"{surname_payload}<<{given_payload}" if given_payload else f"{surname_payload}<<"

    @staticmethod
    def _letters(value: str) -> str:
        return "".join(char for char in value if "A" <= char <= "Z")

    @staticmethod
    def _distance(left: str, right: str) -> int:
        return sum(1 for current, expected in zip(left, right) if current != expected)
