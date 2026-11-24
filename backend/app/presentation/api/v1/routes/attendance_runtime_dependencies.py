"""Typed call-time services captured by the public browser attendance routes."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import Settings
from app.core.security.mobile_offline_lease import SignedOfflineManifest
from app.infrastructure.database.models import (
    AttendanceRuntimeRegistrationModel,
    AttendanceSessionModel,
)
from app.infrastructure.repositories.attendance_discard_repository import (
    AttendanceDiscardRepository,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository


class BrowserRuntimeResolver(Protocol):
    async def __call__(
        self,
        request: Request,
        *,
        session: AsyncSession,
        agency_id: uuid.UUID,
        coordinator_user_id: uuid.UUID,
        required: bool,
    ) -> AttendanceRuntimeRegistrationModel | None: ...


class CoordinatorSessionLookup(Protocol):
    async def __call__(
        self,
        session: AsyncSession,
        agency_id: uuid.UUID,
        session_id: uuid.UUID,
        coordinator_id: uuid.UUID,
        *,
        lock_for_scan: bool = False,
    ) -> AttendanceSessionModel: ...


class CoordinatorRosterRevision(Protocol):
    async def __call__(
        self,
        session: AsyncSession,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
    ) -> int: ...


GroupAssignmentCheck = Callable[[AsyncSession, uuid.UUID, uuid.UUID, uuid.UUID], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class OfflineAuthorizationDependencies:
    settings: Settings
    agency_id: uuid.UUID
    resolve_runtime: BrowserRuntimeResolver
    ensure_group: GroupAssignmentCheck
    roster_revision: CoordinatorRosterRevision
    sign_manifest: Callable[[Mapping[str, object]], SignedOfflineManifest]
    audit_repository: type[AuditLogRepository]


@dataclass(frozen=True, slots=True)
class DiscardSynchronizationDependencies:
    settings: Settings
    agency_id: uuid.UUID
    resolve_runtime: BrowserRuntimeResolver
    ensure_group: GroupAssignmentCheck
    get_session: CoordinatorSessionLookup
    discard_repository: type[AttendanceDiscardRepository]
    audit_repository: type[AuditLogRepository]
