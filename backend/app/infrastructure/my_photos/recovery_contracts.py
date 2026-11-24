"""Durable recovery dispatch, deletion claims and call-time database context."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

DispatchKind = Literal["search", "index", "media"]


DeletionKind = Literal["current", "superseded"]


@dataclass(frozen=True, slots=True)
class DurableDispatch:
    job_id: uuid.UUID
    kind: DispatchKind
    search_run_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class ProviderDeletionBatchResult:
    claimed: int
    completed: int
    retrying: int
    terminal_failed: int


@dataclass(frozen=True, slots=True)
class _DeletionClaim:
    enrollment_id: uuid.UUID
    kind: DeletionKind
    agency_id: uuid.UUID
    group_id: uuid.UUID
    passenger_identity_id: uuid.UUID
    provider_reference: str
    deletion_identity: str
    attempt_count: int


@dataclass(frozen=True, slots=True)
class _DeletionOutcome:
    claim: _DeletionClaim
    complete: bool
    error_code: str | None


@dataclass(frozen=True, slots=True)
class RecoveryContext:
    sessions: async_sessionmaker[AsyncSession]


DurableDispatch.__module__ = "app.infrastructure.my_photos.recovery_runtime"
ProviderDeletionBatchResult.__module__ = "app.infrastructure.my_photos.recovery_runtime"
_DeletionClaim.__module__ = "app.infrastructure.my_photos.recovery_runtime"
_DeletionOutcome.__module__ = "app.infrastructure.my_photos.recovery_runtime"
