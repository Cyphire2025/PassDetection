"""Optional external anchoring boundary for audit-chain checkpoints.

The database hash chain detects mutation but cannot make a database
administrator unable to rewrite both rows and chain heads.  Production
deployments that require stronger non-repudiation can publish these bounded
checkpoints to an independently controlled immutable/WORM destination.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AuditIntegrityCheckpoint:
    scope_key: str
    integrity_version: int
    last_sequence: int
    last_hash: str
    observed_at: datetime


class AuditIntegritySink(Protocol):
    """Publish an idempotent chain checkpoint outside the application database."""

    async def publish(self, checkpoint: AuditIntegrityCheckpoint) -> None: ...


__all__ = ["AuditIntegrityCheckpoint", "AuditIntegritySink"]
