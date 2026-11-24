"""Explicit reviewed-send transaction and durable outbox creation."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.gc_notifications import NotificationSendRequest
from app.application.mobile.authored_notification_audience import NotificationAudienceSnapshot
from app.application.mobile.authored_notification_drafts import require_draft
from app.application.mobile.authored_notification_preview import (
    read_preview_token,
    request_fingerprint,
)
from app.application.mobile.authored_notification_reviews import _audience
from app.application.mobile.notification_errors import NotificationWorkflowError
from app.infrastructure.database.gc_mobile_models import GCGroupAccessModel, MobileNotificationModel
from app.infrastructure.database.gc_notification_models import (
    GCNotificationBatchModel,
    GCNotificationRecipientGrantModel,
    GCNotificationRecipientModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository


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
    except NotificationWorkflowError as exc:
        if existing is not None:
            # A definitive pre-send rejection must never hide a prior committed
            # batch from recovery, even if the retry token was corrupted.
            raise NotificationWorkflowError("conflict", "idempotency_conflict") from exc
        raise
    fingerprint = request_fingerprint(
        draft_id=draft_id,
        revision=body.expected_revision,
        audience=audience_hash,
        actor_id=actor_id,
    )
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise NotificationWorkflowError("conflict", "idempotency_conflict")
        return existing
    if expiry <= current.timestamp():
        raise NotificationWorkflowError("conflict", "stale_preview")
    draft = await require_draft(session, agency_id=agency_id, draft_id=draft_id, lock=True)
    if draft.revision != body.expected_revision:
        raise NotificationWorkflowError("conflict", "draft_conflict")
    access_query = select(GCGroupAccessModel.id).where(GCGroupAccessModel.agency_id == agency_id)
    if draft.audience == "selected_groups":
        access_query = access_query.where(
            GCGroupAccessModel.group_id.in_([uuid.UUID(item) for item in draft.group_ids])
        )
    await session.execute(access_query.order_by(GCGroupAccessModel.id).with_for_update())
    current = max(current, datetime.now(UTC))
    if expiry <= current.timestamp():
        raise NotificationWorkflowError("conflict", "stale_preview")
    audience = await _audience(session, draft, current)
    if audience.fingerprint != audience_hash:
        raise NotificationWorkflowError("conflict", "audience_changed")
    if not audience.grants:
        raise NotificationWorkflowError("conflict", "no_eligible_recipients")
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
