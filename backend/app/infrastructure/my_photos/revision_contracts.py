"""Refresh result and immutable call-time session factory."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

RefreshFanoutState = Literal["succeeded", "continuing", "failed", "lease_lost"]


@dataclass(frozen=True, slots=True)
class RefreshFanoutResult:
    state: RefreshFanoutState
    search_run_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class RevisionContext:
    sessions: async_sessionmaker[AsyncSession]


RefreshFanoutResult.__module__ = "app.infrastructure.my_photos.revision_runtime"
