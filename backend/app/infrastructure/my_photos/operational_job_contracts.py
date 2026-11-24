"""Durable photo operation job contracts."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

OperationalState = Literal[
    "succeeded", "retrying", "failed", "cancelled", "lease_busy", "lease_lost", "noop"
]
OperationalJobType = Literal[
    "index_gallery", "generate_variants", "prepare_media", "refresh_searches"
]
MediaVariant = Literal["thumbnail", "preview", "analysis", "original", "optimized"]


@dataclass(frozen=True, slots=True)
class OperationalJobResult:
    state: OperationalState
    retry_after_seconds: int | None = None
    search_run_ids: tuple[uuid.UUID, ...] = ()
    followup_job_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class _OperationalClaim:
    job_id: uuid.UUID
    lease_owner: str
    job_type: OperationalJobType
    gallery_id: uuid.UUID
    media_asset_id: uuid.UUID | None
    agency_id: uuid.UUID
    group_id: uuid.UUID
    checkpoint_cursor: str | None
    target_revision: int | None
    idempotency_key: str
    request_fingerprint: str | None
    attempt_count: int
    max_attempts: int


SessionFactory = Callable[[], AsyncSession]


@dataclass(frozen=True, slots=True)
class OperationalWorkerContext:
    session_factory: SessionFactory


OperationalJobResult.__module__ = "app.infrastructure.my_photos.operational_runtime"
_OperationalClaim.__module__ = "app.infrastructure.my_photos.operational_runtime"
