"""Canonical passport analytics value without transport or persistence dependencies."""

from dataclasses import asdict, dataclass
from typing import Any


class PassportAnalyticsLimitError(ValueError):
    def __init__(self) -> None:
        super().__init__("analytics_read_limit")


@dataclass(frozen=True, slots=True)
class PassportAnalyticsSummary:
    status_counts: dict[str, int]
    confidence_buckets: dict[str, int]
    submissions_by_day: dict[str, int]
    average_confidence: float | None

    def project(self) -> dict[str, Any]:
        return asdict(self)
