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
