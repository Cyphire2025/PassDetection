"""Draft/review/explicit-send transactions. This module never invokes a provider."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.authored_notification_access import registrations_for_grants
from app.application.mobile.authored_notification_audience import (
    NotificationAudienceSnapshot,
    collect_notification_audience,
)
from app.application.mobile.authored_notification_preview import (
    create_preview_token,
    provider_readiness,
    read_preview_token,
    request_fingerprint,
)
from app.infrastructure.database.gc_mobile_models import GCGroupAccessModel, MobileNotificationModel
from app.infrastructure.database.gc_notification_models import (
    GCNotificationBatchModel,
    GCNotificationDraftModel,
    GCNotificationRecipientGrantModel,
    GCNotificationRecipientModel,
)
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.schemas.gc_notification_schemas import (
    NotificationDraftInput,
    NotificationDraftResponse,
    NotificationDraftUpdate,
    NotificationPreviewResponse,
    NotificationRoleCounts,
    NotificationSendRequest,
)


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
        raise HTTPException(404, "Notification draft not found")
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
        raise HTTPException(422, "Selected groups are unavailable")
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
            raise HTTPException(409, "draft_conflict")
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
            raise HTTPException(409, "draft_conflict")
        return
    if expected_revision != draft.revision:
        raise HTTPException(409, "draft_conflict")
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


async def _audience(
    session: AsyncSession, draft: GCNotificationDraftModel, now: datetime
) -> NotificationAudienceSnapshot:
    selected = (
        [uuid.UUID(item) for item in draft.group_ids]
        if draft.audience == "selected_groups"
        else None
    )
    audience = await collect_notification_audience(
        session, agency_id=draft.agency_id, group_ids=selected, now=now
    )
    if selected is not None and {item[0] for item in audience.groups} != set(selected):
        raise HTTPException(409, "audience_changed")
    return audience


async def preview_notification(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    actor_id: uuid.UUID,
    draft_id: uuid.UUID,
    revision: int,
    now: datetime | None = None,
) -> NotificationPreviewResponse:
    current = now or datetime.now(UTC)
    draft = await require_draft(session, agency_id=agency_id, draft_id=draft_id)
    if draft.revision != revision:
        raise HTTPException(409, "draft_conflict")
    audience = await _audience(session, draft, current)
    devices: dict[str, set[uuid.UUID]] = {}
    for provider in ("fcm", "apns"):
        registrations = await registrations_for_grants(
            session,
            agency_id=agency_id,
            grants=audience.grants,
            provider_name=provider,
            now=current,
        )
        for key, rows in registrations.items():
            devices.setdefault(key, set()).update(row.id for row in rows)
    expiry = current + timedelta(minutes=10)
    return NotificationPreviewResponse(
        draft_revision=revision,
        preview_token=create_preview_token(
            agency_id=agency_id,
            actor_id=actor_id,
            draft_id=draft_id,
            revision=revision,
            fingerprint=audience.fingerprint,
            expires_at=expiry,
        ),
        expires_at=expiry,
        group_count=len(audience.groups),
        group_ids=[row[0] for row in audience.groups],
        group_names=[row[1] for row in audience.groups],
        recipient_count=len(audience.people),
        role_counts=NotificationRoleCounts(**audience.role_counts),
        eligible_device_count=sum(map(len, devices.values())),
        no_active_registration_count=len(audience.people) - len(devices),
        **provider_readiness(),
    )


async def batch_by_request(
    session: AsyncSession, agency_id: uuid.UUID, request_id: uuid.UUID
) -> GCNotificationBatchModel | None:
    return (
        await session.execute(
            select(GCNotificationBatchModel).where(
                GCNotificationBatchModel.agency_id == agency_id,
                GCNotificationBatchModel.request_id == request_id,
            )
        )
    ).scalar_one_or_none()


async def send_notification(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    actor_id: uuid.UUID,
    draft_id: uuid.UUID,
    body: NotificationSendRequest,
    now: datetime | None = None,
) -> GCNotificationBatchModel:
    """Commit ownership remains with the request; snapshots and outbox are atomic."""
    current = now or datetime.now(UTC)
    if session.get_bind().dialect.name == "postgresql":
        # One request UUID across different drafts also serializes. No provider/network
        # call runs under this transaction or lock.
        key = int.from_bytes(
            hashlib.sha256(f"{agency_id}:{body.request_id}".encode()).digest()[:8],
            "big",
            signed=True,
        )
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    existing = await batch_by_request(session, agency_id, body.request_id)
    try:
        audience_hash, expiry = read_preview_token(
            body.preview_token,
            agency_id=agency_id,
            actor_id=actor_id,
            draft_id=draft_id,
            revision=body.expected_revision,
        )
    except HTTPException as exc:
        if existing is not None:
            # A definitive pre-send rejection must never hide a prior committed
            # batch from recovery, even if the retry token was corrupted.
            raise HTTPException(409, "idempotency_conflict") from exc
        raise
    fingerprint = request_fingerprint(
        draft_id=draft_id,
        revision=body.expected_revision,
        audience=audience_hash,
        actor_id=actor_id,
    )
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise HTTPException(409, "idempotency_conflict")
        return existing
    if expiry <= current.timestamp():
        raise HTTPException(409, "stale_preview")
    draft = await require_draft(session, agency_id=agency_id, draft_id=draft_id, lock=True)
    if draft.revision != body.expected_revision:
        raise HTTPException(409, "draft_conflict")
    access_query = select(GCGroupAccessModel.id).where(GCGroupAccessModel.agency_id == agency_id)
    if draft.audience == "selected_groups":
        access_query = access_query.where(
            GCGroupAccessModel.group_id.in_([uuid.UUID(item) for item in draft.group_ids])
        )
    await session.execute(access_query.order_by(GCGroupAccessModel.id).with_for_update())
    current = max(current, datetime.now(UTC))
    if expiry <= current.timestamp():
        raise HTTPException(409, "stale_preview")
    audience = await _audience(session, draft, current)
    if audience.fingerprint != audience_hash:
        raise HTTPException(409, "audience_changed")
    if not audience.grants:
        raise HTTPException(409, "no_eligible_recipients")
    batch = GCNotificationBatchModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        draft_id=draft.id,
        draft_revision=draft.revision,
        request_id=body.request_id,
        request_fingerprint=fingerprint,
        title=draft.title,
        body=draft.body,
        audience=draft.audience,
        group_ids=[str(row[0]) for row in audience.groups],
        group_names=[row[1] for row in audience.groups],
        role_counts=audience.role_counts,
        created_by_user_id=actor_id,
        created_at=current,
        expires_at=current + timedelta(hours=24),
    )
    session.add(batch)
    await session.flush()
    await _enqueue_batch(session, batch, audience)
    draft.status, draft.last_sent_at, draft.updated_at = "sent", current, current
    await session.flush()
    await AuditLogRepository(session).record(
        action="gc_notification.batch_sent",
        entity_type="gc_notification_batch",
        agency_id=agency_id,
        user_id=actor_id,
        entity_id=str(batch.id),
        metadata={
            "draft_id": str(draft.id),
            "request_id": str(body.request_id),
            "recipient_count": len(audience.people),
            "group_count": len(audience.groups),
        },
    )
    return batch


async def _enqueue_batch(
    session: AsyncSession, batch: GCNotificationBatchModel, audience: NotificationAudienceSnapshot
) -> None:
    people = list(audience.people.items())
    for start in range(0, len(people), 250):
        page = people[start : start + 250]
        recipients = [
            GCNotificationRecipientModel(
                id=uuid.uuid4(),
                agency_id=batch.agency_id,
                batch_id=batch.id,
                recipient_type=grants[0].role,
                person_key=person_key,
                created_at=batch.created_at,
            )
            for person_key, grants in page
        ]
        session.add_all(recipients)
        await session.flush()
        for recipient, (_, grants) in zip(recipients, page, strict=True):
            session.add_all(
                [
                    GCNotificationRecipientGrantModel(
                        id=uuid.uuid4(),
                        agency_id=batch.agency_id,
                        recipient_id=recipient.id,
                        group_id=grant.group_id,
                        gc_group_access_id=grant.access_id,
                        principal_id=grant.principal_id,
                        access_generation=grant.access_generation,
                        identity_claim_generation=grant.claim_generation,
                    )
                    for grant in grants
                ]
            )
            notification_id = uuid.uuid4()
            session.add(
                MobileNotificationModel(
                    id=notification_id,
                    agency_id=batch.agency_id,
                    authored_recipient_id=recipient.id,
                    recipient_type="authored",
                    notification_type="gc_alert",
                    category="announcement",
                    priority="high",
                    title=batch.title,
                    body=batch.body,
                    lock_screen_title=batch.title,
                    lock_screen_body=batch.body,
                    contains_sensitive_content=False,
                    deep_link_path="/phone-alerts",
                    dedupe_key=f"gc-alert:{batch.id}",
                    public_payload={"route": "updates", "event_id": str(notification_id)},
                    status="queued",
                    available_at=batch.created_at,
                    expires_at=batch.expires_at,
                    created_at=batch.created_at,
                    updated_at=batch.created_at,
                )
            )
        await session.flush()
