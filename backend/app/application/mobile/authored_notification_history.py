"""Batched, PII-free delivery projections for explicit notification history."""

import base64
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.application.mobile.authored_notification_preview import provider_readiness
from app.infrastructure.database.gc_mobile_models import (
    MobileNotificationModel,
    MobilePushDeliveryModel,
)
from app.infrastructure.database.gc_notification_models import (
    GCNotificationBatchModel,
    GCNotificationDraftModel,
    GCNotificationRecipientModel,
)
from app.presentation.api.v1.schemas.gc_notification_schemas import (
    NotificationBatchResponse,
    NotificationDeviceCounts,
    NotificationRecipientCounts,
    NotificationRoleCounts,
)


def page_cursor(row: GCNotificationDraftModel | GCNotificationBatchModel) -> str:
    return (
        base64.urlsafe_b64encode(f"{row.created_at.isoformat()}|{row.id}".encode())
        .decode()
        .rstrip("=")
    )


def cursor_filter(
    model: type[GCNotificationDraftModel] | type[GCNotificationBatchModel], cursor: str
) -> ColumnElement[bool]:
    try:
        created, identifier = (
            base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
            .decode()
            .split("|")
        )
        created_at = datetime.fromisoformat(created)
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("Notification cursor timestamp must include a timezone")
        return tuple_(model.created_at, model.id) < (
            created_at,
            uuid.UUID(identifier),
        )
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(422, "Invalid notification cursor") from exc


async def batch_responses(
    session: AsyncSession, batches: list[GCNotificationBatchModel]
) -> list[NotificationBatchResponse]:
    if not batches:
        return []
    ids = [batch.id for batch in batches]
    recipient_counts = {batch.id: NotificationRecipientCounts() for batch in batches}
    device_counts = {batch.id: NotificationDeviceCounts() for batch in batches}
    rows = (
        await session.execute(
            select(
                GCNotificationRecipientModel.batch_id,
                MobileNotificationModel.status,
                MobileNotificationModel.failure_code,
                func.count(MobileNotificationModel.id),
                func.count(MobileNotificationModel.read_at),
            )
            .join(
                MobileNotificationModel,
                (MobileNotificationModel.authored_recipient_id == GCNotificationRecipientModel.id)
                & (MobileNotificationModel.agency_id == GCNotificationRecipientModel.agency_id),
            )
            .where(GCNotificationRecipientModel.batch_id.in_(ids))
            .group_by(
                GCNotificationRecipientModel.batch_id,
                MobileNotificationModel.status,
                MobileNotificationModel.failure_code,
            )
        )
    ).all()
    for batch_id, state, error, count, read in rows:
        counts = recipient_counts[batch_id]
        counts.total += count
        counts.read += read
        if error == "provider_outcome_unknown":
            counts.unknown += count
        elif state in {"queued", "sent", "failed", "cancelled"}:
            setattr(counts, state, getattr(counts, state) + count)
        if error == "no_active_registration":
            counts.no_active_registration += count
    deliveries = (
        await session.execute(
            select(
                GCNotificationRecipientModel.batch_id,
                MobilePushDeliveryModel.status,
                func.count(MobilePushDeliveryModel.id),
            )
            .join(
                MobileNotificationModel,
                (MobileNotificationModel.authored_recipient_id == GCNotificationRecipientModel.id)
                & (MobileNotificationModel.agency_id == GCNotificationRecipientModel.agency_id),
            )
            .join(
                MobilePushDeliveryModel,
                (MobilePushDeliveryModel.notification_id == MobileNotificationModel.id)
                & (MobilePushDeliveryModel.agency_id == MobileNotificationModel.agency_id),
            )
            .where(GCNotificationRecipientModel.batch_id.in_(ids))
            .group_by(GCNotificationRecipientModel.batch_id, MobilePushDeliveryModel.status)
        )
    ).all()
    for batch_id, state, count in deliveries:
        counts_device = device_counts[batch_id]
        counts_device.total += count
        if state in NotificationDeviceCounts.model_fields and state != "total":
            setattr(counts_device, state, getattr(counts_device, state) + count)
    return [
        NotificationBatchResponse.model_validate(
            {
                "id": batch.id,
                "notification_id": batch.draft_id,
                "request_id": batch.request_id,
                "draft_revision": batch.draft_revision,
                "title": batch.title,
                "body": batch.body,
                "audience": batch.audience,
                "group_ids": batch.group_ids,
                "group_names": batch.group_names,
                "role_counts": NotificationRoleCounts(**batch.role_counts),
                "created_at": batch.created_at,
                "expires_at": batch.expires_at,
                "recipient_counts": recipient_counts[batch.id],
                "device_delivery_counts": device_counts[batch.id],
                "provider_enabled": provider_readiness()["provider_enabled"],
            }
        )
        for batch in batches
    ]
