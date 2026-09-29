"""Shared, flush-only client-detail correction with delivery and revision fences."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import propagate_mobile_passenger_change
from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.passports.correct_client_details import correct_client_details
from app.domain.entities.entities import (
    OFFICE_VISIBLE_PASSPORT_STATUS_VALUES,
    ClientGroup,
    GroupStatus,
    PassportSubmission,
    User,
)
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_roster_resolution_repository import (
    lock_linked_whatsapp_broadcast_groups,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.whatsapp.private_delivery_policy import (
    prepare_private_delivery_identity_mutation,
)


class ClientDetailsUnavailable(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


@dataclass(frozen=True, slots=True)
class ClientDetailDependencies:
    submissions: PassportSubmissionRepository
    groups: ClientGroupRepository
    audit: AuditLogRepository
    authorization: AuthorizationPolicy
    lock_broadcasts: Callable[..., Awaitable[Any]]
    prepare_delivery: Callable[..., Awaitable[int]]
    propagate: Callable[..., Awaitable[Any]]

    @classmethod
    def for_session(cls, session: AsyncSession) -> ClientDetailDependencies:
        return cls(
            PassportSubmissionRepository(session),
            ClientGroupRepository(session),
            AuditLogRepository(session),
            AuthorizationPolicy(session),
            lock_linked_whatsapp_broadcast_groups,
            prepare_private_delivery_identity_mutation,
            propagate_mobile_passenger_change,
        )


async def editable_client_submission(
    submission_id: uuid.UUID,
    user: User,
    session: AsyncSession,
    *,
    lock: bool,
    dependencies: ClientDetailDependencies | None = None,
) -> tuple[PassportSubmission, ClientGroup]:
    deps = dependencies or ClientDetailDependencies.for_session(session)
    submission = await (
        deps.submissions.get_by_id_for_update(submission_id)
        if lock
        else deps.submissions.get_by_id(submission_id)
    )
    if submission is None:
        raise ClientDetailsUnavailable(404, "Passport submission was not found")
    try:
        await deps.authorization.require_confirm_passport(user, submission)
    except AuthorizationError as exc:
        raise ClientDetailsUnavailable(403, exc.message) from exc
    group = await deps.groups.get_by_id(submission.group_id)
    if group is None or group.agency_id != submission.agency_id:
        raise ClientDetailsUnavailable(404, "Passport group was not found")
    if group.status in {GroupStatus.ARCHIVED, GroupStatus.DELETED}:
        raise ClientDetailsUnavailable(409, "Restore this group before editing client details.")
    if submission.status.value not in OFFICE_VISIBLE_PASSPORT_STATUS_VALUES:
        raise ClientDetailsUnavailable(
            409, "Wait until the client has submitted these details before editing."
        )
    return submission, group


@dataclass(frozen=True, slots=True)
class ClientDetailsCorrection:
    submission: PassportSubmission
    changed_fields: tuple[str, ...]
    cancelled_deliveries: int


async def apply_client_detail_correction(
    session: AsyncSession,
    *,
    submission_id: uuid.UUID,
    user: User,
    expected_updated_at: datetime,
    changes: dict[str, Any],
    cancel_queued: bool,
    dependencies: ClientDetailDependencies | None = None,
    preserve_revision: Callable[
        [PassportSubmission, PassportSubmission, ClientGroup, tuple[str, ...]], Awaitable[None]
    ]
    | None = None,
) -> ClientDetailsCorrection:
    """Caller commits correction, revision, audit, and mobile propagation together.

    Web corrections preserve their established queue-cancellation behavior.
    MCP callers must pass cancel_queued=False to block pending private delivery.
    """
    deps = dependencies or ClientDetailDependencies.for_session(session)
    before, _ = await editable_client_submission(
        submission_id, user, session, lock=False, dependencies=deps
    )
    locked_group = (
        await session.execute(
            select(ClientGroupModel)
            .where(
                ClientGroupModel.id == before.group_id,
                ClientGroupModel.agency_id == before.agency_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if locked_group is None:
        raise ClientDetailsUnavailable(404, "Passport group was not found")
    current_group = await deps.groups.get_by_id(before.group_id)
    if current_group is None:
        raise ClientDetailsUnavailable(404, "Passport group was not found")
    _, proposed_changes = correct_client_details(before, current_group, changes)
    cancelled = 0
    if proposed_changes:
        await deps.lock_broadcasts(session, agency_id=before.agency_id, group_id=before.group_id)
        cancelled = await deps.prepare_delivery(
            session,
            agency_id=before.agency_id,
            group_id=before.group_id,
            cancel_queued=cancel_queued,
            cancellation_reason="Client-provided details changed before private delivery. Refresh the preview before sending.",
        )
    submission, group = await editable_client_submission(
        submission_id, user, session, lock=True, dependencies=deps
    )
    if submission.group_id != before.group_id or submission.agency_id != before.agency_id:
        raise ClientDetailsUnavailable(
            409, "The submission moved while you were editing. Reload and try again."
        )
    current = submission.updated_at
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    if current != expected_updated_at:
        raise ClientDetailsUnavailable(
            409, "This submission changed while you were editing. Reload its details and try again."
        )
    updated, changed = correct_client_details(submission, group, changes)
    if changed:
        if preserve_revision is not None:
            await preserve_revision(submission, updated, group, changed)
        await deps.submissions.update(updated)
        await deps.audit.record(
            action="passport_client_details_corrected",
            entity_type="passport_submission",
            entity_id=str(updated.id),
            agency_id=updated.agency_id,
            user_id=user.id,
            metadata={
                "group_id": str(updated.group_id),
                "changed_fields": list(changed),
                "cancelled_private_deliveries": cancelled,
            },
        )
        await deps.propagate(
            session,
            agency_id=updated.agency_id,
            group_id=updated.group_id,
            passenger_submission_ids=[updated.id],
            actor_user_id=user.id,
            change_kind="profile",
            reconcile_identities=True,
        )
    return ClientDetailsCorrection(updated, changed, cancelled)
