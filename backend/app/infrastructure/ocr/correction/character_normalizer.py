"""Field-context character normalization for ICAO MRZ text."""

from __future__ import annotations


DIGIT_CONFUSIONS = {
    "O": "0",
    "Q": "0",
    "D": "0",
    "I": "1",
    "L": "1",
    "Z": "2",
    "S": "5",
    "G": "6",
    "T": "7",
    "B": "8",
}

ALPHA_CONFUSIONS = {
    "0": "O",
    "1": "I",
    "2": "Z",
    "5": "S",
    "6": "G",
    "8": "B",
}

NAME_FILLER_CONFUSIONS = {"K": "<", "S": "<", "5": "<", "E": "<", "6": "<"}


class CharacterNormalizer:
    """Normalizes OCR-confused characters only where the field permits it."""

    def sanitize_mrz_text(self, value: str | None) -> str:
        return "".join(char for char in (value or "").upper() if char.isalnum() or char == "<")

    def digit(self, char: str) -> str:
        return DIGIT_CONFUSIONS.get(char, char)

    def alpha(self, char: str) -> str:
        return ALPHA_CONFUSIONS.get(char, char)

    def sex(self, char: str) -> str:
        normalized = self.alpha(char)
        return normalized if normalized in {"M", "F", "<"} else char

    def country_code(self, value: str) -> str:
        return "".join(self.alpha(char) for char in value[:3]).ljust(3, "<")

    def date(self, value: str) -> str:
        return "".join(self.digit(char) for char in value[:6]).ljust(6, "<")

    def name_payload(self, value: str) -> str:
        chars: list[str] = []
        for char in value:
            if char == "<":
                chars.append("<")
            elif char.isalpha():
                chars.append(char)
        return "".join(chars)
