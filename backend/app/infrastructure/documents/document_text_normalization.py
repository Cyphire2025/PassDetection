"""Focused text normalization policy; no parser or I/O side effects."""

from __future__ import annotations

import re
import unicodedata

from app.domain.value_objects.travel_document_taxonomy import document_type_label


class DocumentTextNormalization:
    def _text_lines(self, text: str) -> list[str]:
        lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
        if not lines and text.strip():
            lines = [" ".join(text.split())]
        return lines[:4_000]

    def _name_words(self, value: str) -> list[str]:
        compatible = unicodedata.normalize("NFKC", value).casefold()
        return re.findall(r"[^\W_]+", compatible, flags=re.UNICODE)[:40_000]

    def _normalize_identifier(self, value: object) -> str | None:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        raw = " ".join(str(value).strip().split())
        if not raw or len(raw) > 80:
            return None
        normalized = re.sub(r"[^A-Z0-9]+", "", raw.upper())
        return normalized if 1 <= len(normalized) <= 64 else None

    def _normalize_key(self, value: object) -> str:
        raw = str(value or "")
        camel_case_split = re.sub(
            r"(?<=[A-Z])(?=[A-Z][a-z])|(?<=[a-z0-9])(?=[A-Z])",
            " ",
            raw,
        )
        return "_".join(re.findall(r"[a-z0-9]+", camel_case_split.casefold()))

    def _normalize(self, value: str) -> str:
        compatible = unicodedata.normalize("NFKC", value).casefold()
        return " ".join(re.findall(r"[^\W_]+", compatible, flags=re.UNICODE))

    def _label(self, value: str) -> str:
        if value == "passport":
            return "passport"
        return document_type_label(value).casefold()
