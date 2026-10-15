"""Safe transport-independent failures; never include identifiers or answers."""

from enum import StrEnum


class ReuseReason(StrEnum):
    UNAVAILABLE = "history_unavailable"
    EXPIRED = "claim_expired"
    VERIFICATION_FAILED = "verification_failed"
    RATE_LIMITED = "verification_cooldown"
    REVISION_CONFLICT = "information_changed"
    INSUFFICIENT_EVIDENCE = "fresh_collection_required"
    INFRASTRUCTURE = "verification_unavailable"


class ReuseError(RuntimeError):
    def __init__(self, reason: ReuseReason, *, retry_after: int | None = None) -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.retry_after = retry_after
