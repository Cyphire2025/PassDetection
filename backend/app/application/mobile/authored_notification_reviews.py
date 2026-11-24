"""Read-only current-audience review and signed preview creation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.gc_notifications import (
    NotificationPreviewResponse,
    NotificationRoleCounts,
)
from app.application.mobile.authored_notification_audience import (
    NotificationAudienceSnapshot,
    collect_notification_audience,
)
from app.application.mobile.authored_notification_drafts import require_draft
from app.application.mobile.authored_notification_preview import (
    create_preview_token,
    provider_readiness,
)
from app.application.mobile.authored_notification_registrations import registrations_for_grants
from app.application.mobile.notification_errors import NotificationWorkflowError
from app.infrastructure.database.gc_notification_models import GCNotificationDraftModel


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
        raise NotificationWorkflowError("conflict", "audience_changed")
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
        raise NotificationWorkflowError("conflict", "draft_conflict")
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
