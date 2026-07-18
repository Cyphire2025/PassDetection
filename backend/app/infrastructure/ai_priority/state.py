"""State objects and the atomic-store contract for AI priority admission."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class AiWorkload(str, Enum):
    EXTRACTION = "extraction"
    VERIFICATION = "verification"


class AdmissionStatus(str, Enum):
    ADMITTED = "admitted"
    FAIL_OPEN = "fail_open"
    DEFERRED = "deferred"
    DUPLICATE = "duplicate"
    STALE = "stale"


@dataclass(frozen=True)
class QueueCounts:
    extraction_waiting: int = 0
    extraction_dispatching: int = 0
    extraction_active: int = 0
    verification_waiting: int = 0
    verification_active: int = 0

    @property
    def extraction_pending_or_active(self) -> int:
        return (
            self.extraction_waiting
            + self.extraction_dispatching
            + self.extraction_active
        )


@dataclass(frozen=True)
class StoreMutation:
    code: str
    generation: int
    counts: QueueCounts
    retry_after_ms: int = 0


class AtomicPriorityStore(Protocol):
    """One mutation is one atomic operation in the global state store."""

    def mutate(
        self,
        *,
        operation: str,
        job_key: str,
        generation: int,
        now_ms: int,
        lease_ms: int,
        waiting_lease_ms: int,
        max_concurrency: int,
        quiet_period_ms: int,
    ) -> StoreMutation: ...


@dataclass(frozen=True)
class PriorityLease:
    workload: AiWorkload
    job_key: str
    generation: int
    lease_ms: int
    redis_available: bool = True


@dataclass(frozen=True)
class AdmissionDecision:
    status: AdmissionStatus
    reason: str
    lease: PriorityLease
    counts: QueueCounts
    retry_after_ms: int = 0

    @property
    def admitted(self) -> bool:
        return self.status in {
            AdmissionStatus.ADMITTED,
            AdmissionStatus.FAIL_OPEN,
        }
