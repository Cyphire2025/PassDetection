"""Monotonic wall-clock budgets shared by bounded processing stages."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class TimeBudget:
    """Tracks one non-extendable deadline without exposing wall-clock time."""

    deadline: float

    @classmethod
    def start(cls, seconds: float) -> TimeBudget:
        return cls(deadline=time.monotonic() + max(0.0, float(seconds)))

    def remaining(self, *, cap: float | None = None) -> float:
        remaining = max(0.0, self.deadline - time.monotonic())
        if cap is not None:
            return min(remaining, max(0.0, float(cap)))
        return remaining

    def has_time(self, minimum_seconds: float = 0.0) -> bool:
        return self.remaining() > max(0.0, minimum_seconds)
