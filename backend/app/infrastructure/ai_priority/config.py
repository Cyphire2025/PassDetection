"""Constructor-driven configuration for global Gemini admission control.

The environment names live here so operational wiring can be added in one
place after the application-settings work is stable.  Coordination code does
not read environment variables directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

GEMINI_EXTRACTION_MAX_CONCURRENCY: Final[str] = (
    "GEMINI_EXTRACTION_MAX_CONCURRENCY"
)
GEMINI_VERIFICATION_MAX_CONCURRENCY: Final[str] = (
    "GEMINI_VERIFICATION_MAX_CONCURRENCY"
)
GEMINI_EXTRACTION_TIMEOUT_MS: Final[str] = "GEMINI_EXTRACTION_TIMEOUT_MS"
GEMINI_EXTRACTION_QUIET_PERIOD_MS: Final[str] = (
    "GEMINI_EXTRACTION_QUIET_PERIOD_MS"
)
GEMINI_RETRY_MAX_ATTEMPTS: Final[str] = "GEMINI_RETRY_MAX_ATTEMPTS"
GEMINI_PRIORITY_CAPACITY_CALIBRATED: Final[str] = (
    "GEMINI_PRIORITY_CAPACITY_CALIBRATED"
)

PREPARED_SETTING_NAMES: Final[tuple[str, ...]] = (
    GEMINI_EXTRACTION_MAX_CONCURRENCY,
    GEMINI_VERIFICATION_MAX_CONCURRENCY,
    GEMINI_EXTRACTION_TIMEOUT_MS,
    GEMINI_EXTRACTION_QUIET_PERIOD_MS,
    GEMINI_RETRY_MAX_ATTEMPTS,
    GEMINI_PRIORITY_CAPACITY_CALIBRATED,
)


@dataclass(frozen=True)
class AiPriorityConfig:
    """Limits and lease durations used by the Redis state machine.

    Defaults are deliberately conservative.  They are explicit constructor
    defaults, not hidden process-local configuration or admission state.
    """

    extraction_max_concurrency: int = 32
    verification_max_concurrency: int = 1
    extraction_timeout_ms: int = 30_000
    verification_timeout_ms: int = 30_000
    extraction_quiet_period_ms: int = 2_000
    retry_max_attempts: int = 3
    waiting_lease_ms: int = 300_000
    dispatching_lease_ms: int = 120_000
    lease_grace_ms: int = 15_000
    admission_retry_ms: int = 2_000

    def __post_init__(self) -> None:
        positive_fields = {
            "extraction_max_concurrency": self.extraction_max_concurrency,
            "verification_max_concurrency": self.verification_max_concurrency,
            "extraction_timeout_ms": self.extraction_timeout_ms,
            "verification_timeout_ms": self.verification_timeout_ms,
            "retry_max_attempts": self.retry_max_attempts,
            "waiting_lease_ms": self.waiting_lease_ms,
            "dispatching_lease_ms": self.dispatching_lease_ms,
            "lease_grace_ms": self.lease_grace_ms,
            "admission_retry_ms": self.admission_retry_ms,
        }
        for name, value in positive_fields.items():
            if value < 1:
                raise ValueError(f"{name} must be positive")
        if self.extraction_quiet_period_ms < 0:
            raise ValueError("extraction_quiet_period_ms cannot be negative")

    @property
    def extraction_active_lease_ms(self) -> int:
        return self.extraction_timeout_ms + self.lease_grace_ms

    @property
    def verification_active_lease_ms(self) -> int:
        return self.verification_timeout_ms + self.lease_grace_ms
