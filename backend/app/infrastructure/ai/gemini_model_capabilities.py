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
    """Use the supported low-latency level for interactive image reading.

    Reasoning shares the provider output budget with the strict nine-field
    JSON result. Use minimal where supported; 3.6 still requires medium.
    """
    return thinking_level_for_model(model)
