"""Factual-anchor extraction and content-free diagnostic projection."""

from __future__ import annotations

import re
import unicodedata

from app.core.logging.logger import get_logger
from app.infrastructure.ai.gemini_email_patterns import (
    _FACTUAL_ANCHOR_RULES,
)

logger = get_logger("app.infrastructure.ai.gemini_email_analysis_service")


def _factual_anchors(value: str) -> set[tuple[str, str]]:
    """Extract a deliberately narrow set of high-impact factual anchors."""

    anchors: set[tuple[str, str]] = set()
    occupied_spans: list[tuple[int, int]] = []
    for kind, pattern, capture_group in _FACTUAL_ANCHOR_RULES:
        for match in pattern.finditer(value):
            span = match.span()
            if any(
                span[0] < occupied_end and occupied_start < span[1]
                for occupied_start, occupied_end in occupied_spans
            ):
                continue
            raw_anchor = match.group(capture_group) if capture_group is not None else match.group(0)
            canonical = _canonical_factual_anchor(kind, raw_anchor)
            if not canonical:
                continue
            anchors.add((kind, canonical))
            occupied_spans.append(span)
    return anchors


def _canonical_factual_anchor(kind: str, value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    if kind == "url":
        return normalized.rstrip(".,;:!?)]}")
    if kind == "email":
        return normalized
    if kind == "phone":
        return "".join(character for character in normalized if character.isdigit())
    if kind in {"passport", "reference"}:
        return "".join(character for character in normalized if character.isalnum())
    if kind == "money":
        currency_match = re.search(
            r"(?i)[$\u20ac\u00a3\u20b9]|INR|USD|EUR|GBP|AED|SGD|JPY|RS\.?|RUPEES?",
            normalized,
        )
        amount_match = re.search(r"\d[\d,]*(?:\.\d{1,2})?", normalized)
        if currency_match is None or amount_match is None:
            return ""
        currency = currency_match.group(0).casefold().rstrip(".")
        amount = amount_match.group(0).replace(",", "")
        return f"{currency}:{amount}"
    if kind == "number":
        return normalized.replace(",", "").removesuffix("%")
    if kind in {"date", "time"}:
        return re.sub(r"\s+", " ", normalized).replace(".", "")
    return normalized


def _log_unsupported_factual_anchors(
    *,
    field: str,
    anchors: set[tuple[str, str]],
    model: str,
) -> None:
    logger.warning(
        "email_ai_unsupported_factual_anchors",
        field=field,
        anchor_count=len(anchors),
        anchor_kinds=sorted({kind for kind, _ in anchors}),
        model=model,
    )
