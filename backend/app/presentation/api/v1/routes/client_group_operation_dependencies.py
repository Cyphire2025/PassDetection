"""Typed call-time dependencies shared by the upload-link workflow owners."""

from __future__ import annotations

import uuid
from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.mobile.passenger_identity_reconciliation import (
    PassengerIdentityReconciliationResult,
)
from app.application.security.destructive_mutation_policy import (
    DestructiveGroupMutation,
    DestructiveOwnedGroupsMutation,
    DestructiveScopedGroupsMutation,
)
from app.application.use_cases.whatsapp.group_submission_matching import (
    SubmissionMatchRow,
)
from app.domain.entities.entities import (
    ClientGroup,
    User,
)
from app.infrastructure.database.models import (
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    StorageCleanupJobModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.documents.storage_cleanup import StorageCleanupCipher
from app.infrastructure.observability.operational_events import OperationalEvent
from app.presentation.api.v1.schemas.client_group_schemas import (
    WhatsAppBroadcastSummaryResponse,
)


class CurrentUnresolvedMatchContext(Protocol):
    async def __call__(
        self, /, session: AsyncSession, *, group_id: uuid.UUID, agency_id: uuid.UUID
    ) -> tuple[
        dict[uuid.UUID, str],
        list[WhatsAppBroadcastRecipientModel],
        list[PassportSubmissionModel],
        list[SubmissionMatchRow],
    ]: ...


class RecordOperationalEvent(Protocol):
    def __call__(self, event: OperationalEvent, reason: str, *, amount: int = 1) -> None: ...


class LinkedBroadcastMatchingFieldsForGroup(Protocol):
    async def __call__(
        self, /, session: AsyncSession, *, group_id: uuid.UUID, agency_id: uuid.UUID
    ) -> dict[uuid.UUID, tuple[str, ...] | None]: ...


class LinkedBroadcastNamesForGroup(Protocol):
    async def __call__(
        self, /, session: AsyncSession, *, group_id: uuid.UUID, agency_id: uuid.UUID
    ) -> dict[uuid.UUID, str]: ...


class OwnerScopeFor(Protocol):
    def __call__(self, /, user: User) -> uuid.UUID | None: ...


class ReplaceWhatsappLinks(Protocol):
    async def __call__(
        self,
        /,
        session: AsyncSession,
        *,
        group_id: uuid.UUID,
        agency_id: uuid.UUID,
        created_by_user_id: uuid.UUID,
        broadcast_ids: list[uuid.UUID],
        matching_fields_by_broadcast: dict[uuid.UUID, list[str]] | None = None,
    ) -> tuple[list[WhatsAppBroadcastSummaryResponse], list[uuid.UUID], bool]: ...


class RequireClientGroupCreationAccess(Protocol):
    async def __call__(self, /, user: User, session: AsyncSession) -> None: ...


class RequireManagedGroup(Protocol):
    async def __call__(
        self,
        /,
        session: AsyncSession,
        current_user: User,
        link_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> ClientGroup: ...


class RequireMatchingRosterResolutionReplay(Protocol):
    def __call__(
        self,
        /,
        resolution: PassportRosterResolutionModel,
        *,
        client_group_id: uuid.UUID,
        submission_id: uuid.UUID,
        resolution_type: Literal["replacement", "rejected"],
        broadcast_recipient_id: uuid.UUID | None,
        conflict_detail: str,
    ) -> PassportRosterResolutionModel: ...


class RequireViewableGroup(Protocol):
    async def __call__(
        self, /, session: AsyncSession, current_user: User, link_id: uuid.UUID
    ) -> ClientGroup: ...


class RequireWhatsappBroadcastAccess(Protocol):
    def __call__(self, /, user: User) -> None: ...


class UniqueLinkedRecipientCount(Protocol):
    async def __call__(
        self, /, session: AsyncSession, *, group_id: uuid.UUID, agency_id: uuid.UUID
    ) -> int: ...


class ValidateBroadcastIds(Protocol):
    async def __call__(
        self,
        /,
        session: AsyncSession,
        *,
        agency_id: uuid.UUID,
        broadcast_ids: list[uuid.UUID],
        allowed_archived_ids: list[uuid.UUID] | None = None,
    ) -> list[WhatsAppBroadcastSummaryResponse]: ...


class LockLinkedWhatsappBroadcastGroups(Protocol):
    async def __call__(
        self, /, session: AsyncSession, *, agency_id: uuid.UUID, group_id: uuid.UUID
    ) -> None: ...


class LockWhatsappBroadcastGroups(Protocol):
    async def __call__(
        self,
        /,
        session: AsyncSession,
        *,
        agency_id: uuid.UUID,
        broadcast_group_ids: list[uuid.UUID] | set[uuid.UUID] | tuple[uuid.UUID, ...],
    ) -> list[uuid.UUID]: ...


class PreparePrivateDeliveryIdentityMutation(Protocol):
    async def __call__(
        self,
        /,
        session: AsyncSession,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID | None = None,
        broadcast_group_ids: set[uuid.UUID] | None = None,
        recipient_ids: set[uuid.UUID] | None = None,
        cancel_queued: bool,
        cancellation_reason: str,
    ) -> int: ...


class ReconcileMobilePassengerAccessForGroup(Protocol):
    async def __call__(
        self,
        /,
        session: AsyncSession,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
    ) -> PassengerIdentityReconciliationResult | None: ...


class RecordDestructiveFailure(Protocol):
    async def __call__(
        self,
        /,
        context: DestructiveGroupMutation
        | DestructiveOwnedGroupsMutation
        | DestructiveScopedGroupsMutation,
        *,
        user: User,
        error: Exception,
        session_factory: async_sessionmaker[AsyncSession] = AsyncSessionFactory,
    ) -> bool: ...


class RequireLockedBroadcastRecipientCapacity(Protocol):
    async def __call__(
        self,
        /,
        session: AsyncSession,
        *,
        agency_id: uuid.UUID,
        locked_broadcast_ids: Collection[uuid.UUID],
        activating_by_broadcast: Mapping[uuid.UUID, int],
    ) -> dict[uuid.UUID, int]: ...


class StageStorageCleanupJobs(Protocol):
    def __call__(
        self,
        /,
        session: AsyncSession,
        *,
        agency_id: uuid.UUID | None,
        source: str,
        context_id: str,
        storage_keys: Sequence[str],
        cipher: StorageCleanupCipher | None = None,
        now: datetime | None = None,
        not_before: datetime | None = None,
    ) -> tuple[StorageCleanupJobModel, ...]: ...


class SuppressActiveReplacementRecipients(Protocol):
    async def __call__(
        self,
        /,
        session: AsyncSession,
        *,
        agency_id: uuid.UUID,
        broadcast_group_ids: list[uuid.UUID] | set[uuid.UUID] | tuple[uuid.UUID, ...],
        now: datetime,
    ) -> list[WhatsAppBroadcastRecipientModel]: ...


class SyncGroupBroadcastContacts(Protocol):
    async def __call__(
        self,
        /,
        session: AsyncSession,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        actor_user_id: uuid.UUID | None = None,
        affected_broadcast_ids: Sequence[uuid.UUID] = (),
    ) -> dict[str, int]: ...
