"""Tenant-scoped authored notification draft lifecycle."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.gc_notifications import (
    NotificationDraftInput,
    NotificationDraftResponse,
    NotificationDraftUpdate,
)
from app.application.mobile.notification_errors import NotificationWorkflowError
from app.infrastructure.database.gc_notification_models import GCNotificationDraftModel
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository


async def require_draft(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    draft_id: uuid.UUID,
    lock: bool = False,
    include_deleted: bool = False,
) -> GCNotificationDraftModel:
    statement = (
        select(GCNotificationDraftModel)
        .where(
            GCNotificationDraftModel.id == draft_id, GCNotificationDraftModel.agency_id == agency_id
        )
        .execution_options(populate_existing=True)
    )
    if lock:
        statement = statement.with_for_update()
    result = (await session.execute(statement)).scalar_one_or_none()
    if result is None or (result.deleted_at is not None and not include_deleted):
        raise NotificationWorkflowError("missing", "Notification draft not found")
    return result


async def _selected_labels(
    session: AsyncSession, agency_id: uuid.UUID, group_ids: list[uuid.UUID]
) -> list[str]:
    if not group_ids:
        return []
    rows = {
        group_id: name
        for group_id, name in (
            await session.execute(
                select(ClientGroupModel.id, ClientGroupModel.name).where(
                    ClientGroupModel.agency_id == agency_id,
                    ClientGroupModel.id.in_(group_ids),
                    ClientGroupModel.deleted_at.is_(None),
                )
            )
        ).all()
    }
    if len(rows) != len(group_ids):
        raise NotificationWorkflowError("invalid", "Selected groups are unavailable")
    return [rows[group_id] for group_id in group_ids]


def draft_response(draft: GCNotificationDraftModel) -> NotificationDraftResponse:
    return NotificationDraftResponse.model_validate(
        {
            "id": draft.id,
            "title": draft.title,
            "body": draft.body,
            "audience": draft.audience,
            "group_ids": draft.group_ids,
            "group_names": draft.group_names,
            "revision": draft.revision,
            "status": draft.status,
            "last_sent_at": draft.last_sent_at,
            "created_at": draft.created_at,
            "updated_at": draft.updated_at,
        }
    )


async def save_notification_draft(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    actor_id: uuid.UUID,
    body: NotificationDraftInput,
    draft_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> GCNotificationDraftModel:
    current = now or datetime.now(UTC)
    labels = await _selected_labels(session, agency_id, body.group_ids)
    if draft_id is None:
        draft = GCNotificationDraftModel(
            id=uuid.uuid4(),
            agency_id=agency_id,
            revision=1,
            created_by_user_id=actor_id,
            created_at=current,
            status="draft",
        )
        session.add(draft)
    else:
        draft = await require_draft(session, agency_id=agency_id, draft_id=draft_id, lock=True)
        if (
            not isinstance(body, NotificationDraftUpdate)
            or body.expected_revision != draft.revision
        ):
            raise NotificationWorkflowError("conflict", "draft_conflict")
        draft.revision += 1
        draft.status = "draft"
    draft.title, draft.body, draft.audience = body.title, body.body, body.audience
    draft.group_ids, draft.group_names = [str(item) for item in body.group_ids], labels
    draft.updated_at, draft.updated_by_user_id = current, actor_id
    await session.flush()
    await AuditLogRepository(session).record(
        action="gc_notification.draft_saved",
        entity_type="gc_notification",
        agency_id=agency_id,
        user_id=actor_id,
        entity_id=str(draft.id),
        metadata={"revision": draft.revision},
    )
    return draft


async def delete_notification_draft(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    actor_id: uuid.UUID,
    draft_id: uuid.UUID,
    expected_revision: int,
    now: datetime | None = None,
) -> None:
    """Hide saved content only; existing send transactions and delivery remain durable."""
    draft = await require_draft(
        session, agency_id=agency_id, draft_id=draft_id, lock=True, include_deleted=True
    )
    if draft.deleted_at is not None:
        # A lost successful response can be safely retried with its original revision.
        if expected_revision != draft.revision - 1:
            raise NotificationWorkflowError("conflict", "draft_conflict")
        return
    if expected_revision != draft.revision:
        raise NotificationWorkflowError("conflict", "draft_conflict")
    current = now or datetime.now(UTC)
    draft.deleted_at, draft.deleted_by_user_id = current, actor_id
    draft.updated_at, draft.updated_by_user_id = current, actor_id
    draft.revision += 1
    await session.flush()
    await AuditLogRepository(session).record(
        action="gc_notification.saved_deleted",
        entity_type="gc_notification",
        agency_id=agency_id,
        user_id=actor_id,
        entity_id=str(draft.id),
        metadata={"revision": draft.revision, "history_retained": True},
    )
