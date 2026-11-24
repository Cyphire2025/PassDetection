"""Durable passenger-search contracts and the single session-factory resource."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

WorkerState = Literal[
    "succeeded", "retrying", "failed", "cancelled", "lease_busy", "lease_lost", "noop"
]


@dataclass(frozen=True, slots=True)
class SearchJobExecutionResult:
    state: WorkerState
    retry_after_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class _SearchClaim:
    search_run_id: uuid.UUID
    job_id: uuid.UUID
    lease_owner: str
    agency_id: uuid.UUID
    group_id: uuid.UUID
    passenger_identity_id: uuid.UUID
    enrollment_id: uuid.UUID
    gallery_id: uuid.UUID
    gallery_revision: int
    face_index_version: int
    enrollment_version: int
    collection_reference: str
    reference_face_handle: str
    total_face_count: int
    attempt_count: int
    max_attempts: int


SessionFactory = Callable[[], AsyncSession]


@dataclass(frozen=True, slots=True)
class SearchWorkerContext:
    session_factory: SessionFactory


SearchJobExecutionResult.__module__ = "app.infrastructure.my_photos.worker_runtime"
_SearchClaim.__module__ = "app.infrastructure.my_photos.worker_runtime"
