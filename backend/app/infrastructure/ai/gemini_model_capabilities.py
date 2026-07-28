"""Explicit compatibility rules for configured Gemini model families."""

from __future__ import annotations

from typing import Literal

GeminiThinkingLevel = Literal["minimal", "medium"]


def thinking_level_for_model(model: str) -> GeminiThinkingLevel:
    """Choose a supported low-cost thinking level for one concrete model.

    Gemini 3.6 supports ``medium`` and ``high``. Older verification models in
    this application use ``minimal``. This is evaluated for every retry model,
    allowing a 3.6 primary to fall back to an older model safely.
    """

    normalized = model.strip().lower()
    return "medium" if normalized.startswith("gemini-3.6-") else "minimal"


def thinking_level_for_passport_extraction(model: str) -> GeminiThinkingLevel:
    """Use balanced thinking for Gemini models that read passport images.

    Interactive extraction has to classify a document and transcribe several
    visually small fields. Gemini 3.5 Flash and Gemini 3.1 Flash-Lite both
    support ``medium`` thinking, which is more appropriate here than the
    latency-first ``minimal`` setting used by simpler verification requests.
    """

    normalized = model.strip().lower()
    if normalized.startswith(
        (
            "gemini-3.6-",
            "gemini-3.5-",
            "gemini-3.1-flash-lite",
        )
    ):
        return "medium"
    return thinking_level_for_model(model)
