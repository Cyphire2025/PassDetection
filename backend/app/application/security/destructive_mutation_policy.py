"""Locked authorization policy for irreversible passport-data mutations.

Destructive routes must acquire the same client-group row lock used by legal
hold changes before inspecting tenant ownership, authorization, or hold state.
That shared serialization point prevents a stale domain object from bypassing
an already committed legal hold.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.security.authorization_policy import AuthorizationPolicy
from app.core.logging.logger import get_logger
from app.domain.entities.entities import ClientGroup, User, UserRole
from app.domain.exceptions.exceptions import (
    AuthorizationError,
    ConflictError,
    EntityNotFoundError,
    PassDetectionError,
    PassportLegalHoldError,
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DestructiveGroupMutation:
    """Authorized group state held under a database row lock."""

    group: ClientGroup
    action: str
    request_fingerprint: str
    target_count: int


@dataclass(frozen=True, slots=True)
class DestructiveOwnedGroupsMutation:
    """Authorized manager-owned groups held under deterministic row locks."""

    manager_id: uuid.UUID
    groups: tuple[ClientGroup, ...]
    action: str
    request_fingerprint: str


@dataclass(frozen=True, slots=True)
class DestructiveScopedGroupsMutation:
    """Authorized platform or tenant group scope held under ordered locks."""

    agency_id: uuid.UUID | None
    groups: tuple[ClientGroup, ...]
    action: str
    request_fingerprint: str


class DestructiveMutationPolicy:
    """Central tenant, role, legal-hold, lock, and attempt-audit boundary."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._groups = ClientGroupRepository(session)
        self._authorization = AuthorizationPolicy(session)
        self._audit = AuditLogRepository(session)

    async def require_group(
        self,
        *,
        user: User,
        group_id: uuid.UUID,
        action: str,
        target_ids: Sequence[uuid.UUID] = (),
    ) -> DestructiveGroupMutation:
        """Lock and authorize one group without disclosing cross-tenant state."""

        tenant_agency_id = None if user.role == UserRole.SUPER_ADMIN else user.agency_id
        if user.role != UserRole.SUPER_ADMIN and tenant_agency_id is None:
            raise AuthorizationError()
        group = await self._groups.get_by_id_for_update(
            group_id,
            agency_id=tenant_agency_id,
            allow_global_scope=user.role == UserRole.SUPER_ADMIN,
        )
        if group is None:
            raise EntityNotFoundError("ClientGroup", group_id)

        fingerprint = destructive_request_fingerprint(
            action=action,
            entity_id=group_id,
            target_ids=target_ids,
        )
        context = DestructiveGroupMutation(
            group=group,
            action=action,
            request_fingerprint=fingerprint,
            target_count=len(set(target_ids)),
        )
        await self._record_group_event(context, user=user, result="attempted")
        try:
            await self._authorization.require_delete_data(user, group, permanent=True)
        except AuthorizationError as error:
            await self._record_group_event(
                context,
                user=user,
                result="denied",
                reason_code=error.code,
            )
            await self._session.commit()
            raise
        if group.passport_legal_hold:
            await self.block_group(
                context,
                user=user,
                error=PassportLegalHoldError(),
            )
        return context

    async def require_manager_owned_groups(
        self,
        *,
        user: User,
        manager_id: uuid.UUID,
        manager_agency_id: uuid.UUID | None,
        action: str,
    ) -> DestructiveOwnedGroupsMutation:
        """Lock every manager-owned group before an account/data purge."""

        if user.role != UserRole.SUPER_ADMIN or manager_agency_id is None:
            raise AuthorizationError()
        groups = tuple(
            await self._groups.list_owned_for_update(
                owner_user_id=manager_id,
                agency_id=manager_agency_id,
            )
        )
        fingerprint = destructive_request_fingerprint(
            action=action,
            entity_id=manager_id,
            target_ids=[group.id for group in groups],
        )
        context = DestructiveOwnedGroupsMutation(
            manager_id=manager_id,
            groups=groups,
            action=action,
            request_fingerprint=fingerprint,
        )
        await self._audit.record(
            action="destructive_operation_attempted",
            entity_type="user",
            entity_id=str(manager_id),
            agency_id=manager_agency_id,
            user_id=user.id,
            actor_email=user.email,
            metadata={
                "operation": action,
                "result": "attempted",
                "request_fingerprint": fingerprint,
                "group_count": len(groups),
            },
            result="success",
        )
        try:
            for group in groups:
                await self._authorization.require_delete_data(
                    user,
                    group,
                    permanent=True,
                )
        except AuthorizationError as error:
            await self._audit.record(
                action="destructive_operation_denied",
                entity_type="user",
                entity_id=str(manager_id),
                agency_id=manager_agency_id,
                user_id=user.id,
                actor_email=user.email,
                metadata={
                    "operation": action,
                    "result": "denied",
                    "reason_code": error.code,
                    "request_fingerprint": fingerprint,
                    "group_count": len(groups),
                },
                result="denied",
            )
            await self._session.commit()
            raise
        held_count = sum(group.passport_legal_hold for group in groups)
        if held_count:
            await self._audit.record(
                action="destructive_operation_blocked",
                entity_type="user",
                entity_id=str(manager_id),
                agency_id=manager_agency_id,
                user_id=user.id,
                actor_email=user.email,
                metadata={
                    "operation": action,
                    "result": "blocked",
                    "reason_code": "PASSPORT_LEGAL_HOLD_ACTIVE",
                    "request_fingerprint": fingerprint,
                    "held_group_count": held_count,
                },
                result="blocked",
            )
            # Only privacy-safe audit inserts precede this commit. Persisting
            # them before raising ensures the dependency rollback cannot erase
            # evidence of a blocked destructive request.
            await self._session.commit()
            raise PassportLegalHoldError()
        return context

    async def require_scoped_groups(
        self,
        *,
        user: User,
        action: str,
    ) -> DestructiveScopedGroupsMutation:
        """Lock and authorize every group in a platform or tenant purge scope."""

        if user.role not in {UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN}:
            raise AuthorizationError()
        agency_id = None if user.role == UserRole.SUPER_ADMIN else user.agency_id
        if user.role != UserRole.SUPER_ADMIN and agency_id is None:
            raise AuthorizationError()
        groups = tuple(
            await self._groups.list_scope_for_update(
                agency_id=agency_id,
                allow_global_scope=user.role == UserRole.SUPER_ADMIN,
            )
        )
        scope_id = agency_id or uuid.UUID(int=0)
        fingerprint = destructive_request_fingerprint(
            action=action,
            entity_id=scope_id,
            target_ids=[group.id for group in groups],
        )
        context = DestructiveScopedGroupsMutation(
            agency_id=agency_id,
            groups=groups,
            action=action,
            request_fingerprint=fingerprint,
        )
        entity_type = "platform" if agency_id is None else "agency"
        entity_id = None if agency_id is None else str(agency_id)
        await self._audit.record(
            action="destructive_operation_attempted",
            entity_type=entity_type,
            entity_id=entity_id,
            agency_id=agency_id,
            user_id=user.id,
            actor_email=user.email,
            metadata={
                "operation": action,
                "result": "attempted",
                "request_fingerprint": fingerprint,
                "group_count": len(groups),
            },
            result="success",
        )
        try:
            for group in groups:
                await self._authorization.require_delete_data(
                    user,
                    group,
                    permanent=True,
                )
        except AuthorizationError as error:
            await self._record_scoped_group_event(
                context,
                user=user,
                result="denied",
                reason_code=error.code,
            )
            await self._session.commit()
            raise
        held_count = sum(group.passport_legal_hold for group in groups)
        if held_count:
            await self._record_scoped_group_event(
                context,
                user=user,
                result="blocked",
                reason_code="PASSPORT_LEGAL_HOLD_ACTIVE",
                held_group_count=held_count,
            )
            await self._session.commit()
            raise PassportLegalHoldError()
        return context

    async def block_group(
        self,
        context: DestructiveGroupMutation,
        *,
        user: User,
        error: ConflictError,
    ) -> None:
        """Persist a blocked decision, release the lock, then raise it."""

        await self._record_group_event(
            context,
            user=user,
            result="blocked",
            reason_code=error.code,
        )
        await self._session.commit()
        raise error

    async def _record_group_event(
        self,
        context: DestructiveGroupMutation,
        *,
        user: User,
        result: Literal["attempted", "blocked", "denied"],
        reason_code: str | None = None,
    ) -> None:
        metadata: dict[str, str | int] = {
            "operation": context.action,
            "result": result,
            "request_fingerprint": context.request_fingerprint,
            "target_count": context.target_count,
        }
        if reason_code is not None:
            metadata["reason_code"] = reason_code
        await self._audit.record(
            action=f"destructive_operation_{result}",
            entity_type="client_group",
            entity_id=str(context.group.id),
            agency_id=context.group.agency_id,
            user_id=user.id,
            actor_email=user.email,
            metadata=metadata,
            result=(
                "blocked" if result == "blocked" else "denied" if result == "denied" else "success"
            ),
        )

    async def _record_scoped_group_event(
        self,
        context: DestructiveScopedGroupsMutation,
        *,
        user: User,
        result: Literal["blocked", "denied"],
        reason_code: str,
        held_group_count: int | None = None,
    ) -> None:
        metadata: dict[str, str | int] = {
            "operation": context.action,
            "result": result,
            "reason_code": reason_code,
            "request_fingerprint": context.request_fingerprint,
            "group_count": len(context.groups),
        }
        if held_group_count is not None:
            metadata["held_group_count"] = held_group_count
        await self._audit.record(
            action=f"destructive_operation_{result}",
            entity_type="platform" if context.agency_id is None else "agency",
            entity_id=(None if context.agency_id is None else str(context.agency_id)),
            agency_id=context.agency_id,
            user_id=user.id,
            actor_email=user.email,
            metadata=metadata,
            result="blocked" if result == "blocked" else "denied",
        )


def destructive_request_fingerprint(
    *,
    action: str,
    entity_id: uuid.UUID,
    target_ids: Sequence[uuid.UUID] = (),
) -> str:
    """Return a non-reversible stable reference for retries and audit joins."""

    ordered_targets = ",".join(str(item) for item in sorted(set(target_ids), key=str))
    material = f"v1:{action}:{entity_id}:{ordered_targets}".encode()
    return hashlib.sha256(material).hexdigest()


async def record_destructive_failure(
    context: (
        DestructiveGroupMutation | DestructiveOwnedGroupsMutation | DestructiveScopedGroupsMutation
    ),
    *,
    user: User,
    error: Exception,
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionFactory,
) -> bool:
    """Best-effort durable failure evidence outside a poisoned transaction.

    A database commit error leaves the request session unsuitable for further
    writes. A fresh bounded session preserves privacy-safe evidence when the
    database is still reachable, while never replacing the original mutation
    error if audit persistence is also unavailable.
    """

    entity_type: str
    entity_id: str | None
    agency_id: uuid.UUID | None
    target_count: int
    if isinstance(context, DestructiveGroupMutation):
        entity_type = "client_group"
        entity_id = str(context.group.id)
        agency_id = context.group.agency_id
        target_count = context.target_count
    elif isinstance(context, DestructiveOwnedGroupsMutation):
        entity_type = "user"
        entity_id = str(context.manager_id)
        agency_id = context.groups[0].agency_id if context.groups else user.agency_id
        target_count = len(context.groups)
    else:
        entity_type = "platform" if context.agency_id is None else "agency"
        entity_id = None if context.agency_id is None else str(context.agency_id)
        agency_id = context.agency_id
        target_count = len(context.groups)
    reason_code = error.code if isinstance(error, PassDetectionError) else type(error).__name__
    try:
        async with session_factory() as audit_session:
            await AuditLogRepository(audit_session).record(
                action="destructive_operation_failed",
                entity_type=entity_type,
                entity_id=entity_id,
                agency_id=agency_id,
                user_id=user.id,
                actor_email=user.email,
                metadata={
                    "operation": context.action,
                    "result": "failed",
                    "reason_code": reason_code,
                    "request_fingerprint": context.request_fingerprint,
                    "target_count": target_count,
                },
                result="failed",
            )
            await audit_session.commit()
    except Exception as audit_error:
        logger.error(
            "destructive_operation_failure_audit_unavailable",
            operation=context.action,
            request_fingerprint=context.request_fingerprint,
            error_type=type(audit_error).__name__,
        )
        return False
    return True


__all__ = [
    "DestructiveGroupMutation",
    "DestructiveMutationPolicy",
    "DestructiveOwnedGroupsMutation",
    "DestructiveScopedGroupsMutation",
    "destructive_request_fingerprint",
    "record_destructive_failure",
]
