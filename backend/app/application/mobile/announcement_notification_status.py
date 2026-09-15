"""Read-only, tenant-scoped announcement delivery counters.

The provider's delivered receipt confirms provider acceptance, not a visible
phone alert. One recipient may have several device deliveries.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.gc_mobile_models import (
    MobileNotificationModel,
    MobilePushDeliveryModel,
)


@dataclass
class AnnouncementRecipientCounts:
    total: int = 0
    queued: int = 0
    sent: int = 0
    failed: int = 0
    cancelled: int = 0
    read: int = 0
    no_active_registration: int = 0


@dataclass
class AnnouncementDeviceDeliveryCounts:
    total: int = 0
    submitting: int = 0
    retry: int = 0
    receipt_pending: int = 0
    delivered: int = 0
    failed: int = 0
    cancelled: int = 0


@dataclass(frozen=True)
class AnnouncementNotificationFailure:
    scope: Literal["recipient", "device"]
    code: str
    count: int


@dataclass(frozen=True)
class AnnouncementNotificationStatus:
    announcement_id: UUID
    provider_enabled: bool
    recipient_counts: AnnouncementRecipientCounts
    device_delivery_counts: AnnouncementDeviceDeliveryCounts
    failures: list[AnnouncementNotificationFailure]
    checked_at: datetime


# Provider errors can contain arbitrary input. Only known operational codes
# leave this boundary; neither provider messages nor tokens are returned.
_SAFE_FAILURE_CODES = frozenset(
    {
        "no_active_registration",
        "announcement_unpublished",
        "recipient_access_revoked",
        "invalid_public_payload",
        "token_decryption_failed",
        "receipt_expired",
        "receipt_not_ready",
        "provider_disabled",
        "provider_unavailable",
        "provider_http_error",
        "provider_rejected",
        "provider_malformed_response",
        "provider_ticket_error",
        "provider_receipt_error",
        "provider_timeout",
        "DeviceNotRegistered",
        "MessageTooBig",
        "MessageRateExceeded",
        "MismatchSenderId",
        "InvalidCredentials",
    }
)


async def announcement_notification_status(
    session: AsyncSession,
    *,
    agency_id: UUID,
    group_id: UUID,
    access_id: UUID,
    announcement_id: UUID,
    provider_enabled: bool,
) -> AnnouncementNotificationStatus:
    scope = (
        MobileNotificationModel.agency_id == agency_id,
        MobileNotificationModel.group_id == group_id,
        MobileNotificationModel.gc_group_access_id == access_id,
        MobileNotificationModel.notification_type == "group_announcement",
        MobileNotificationModel.dedupe_key == f"announcement:{announcement_id}",
    )
    recipient_rows = (
        await session.execute(
            select(
                MobileNotificationModel.status,
                MobileNotificationModel.failure_code,
                func.count(MobileNotificationModel.id),
                func.count(MobileNotificationModel.read_at),
            )
            .where(*scope)
            .group_by(
                MobileNotificationModel.status,
                MobileNotificationModel.failure_code,
            )
        )
    ).all()
    delivery_rows = (
        await session.execute(
            select(
                MobilePushDeliveryModel.status,
                MobilePushDeliveryModel.last_error_code,
                func.count(MobilePushDeliveryModel.id),
            )
            .join(
                MobileNotificationModel,
                MobileNotificationModel.id == MobilePushDeliveryModel.notification_id,
            )
            .where(*scope, MobilePushDeliveryModel.agency_id == agency_id)
            .group_by(
                MobilePushDeliveryModel.status,
                MobilePushDeliveryModel.last_error_code,
            )
        )
    ).all()
    recipients = AnnouncementRecipientCounts()
    devices = AnnouncementDeviceDeliveryCounts()
    failures: Counter[tuple[Literal["recipient", "device"], str]] = Counter()
    for state, code, count, read_count in recipient_rows:
        recipients.total += count
        recipients.read += read_count
        if state in {"queued", "sent", "failed", "cancelled"}:
            setattr(recipients, state, getattr(recipients, state) + count)
        if code == "no_active_registration":
            recipients.no_active_registration += count
        if code:
            failures[("recipient", code if code in _SAFE_FAILURE_CODES else "other")] += count
    for state, code, count in delivery_rows:
        devices.total += count
        if state in {"submitting", "retry", "receipt_pending", "delivered", "failed", "cancelled"}:
            setattr(devices, state, getattr(devices, state) + count)
        if code:
            failures[("device", code if code in _SAFE_FAILURE_CODES else "other")] += count
    return AnnouncementNotificationStatus(
        announcement_id=announcement_id,
        provider_enabled=provider_enabled,
        recipient_counts=recipients,
        device_delivery_counts=devices,
        failures=[
            AnnouncementNotificationFailure(scope=kind, code=code, count=count)
            for (kind, code), count in sorted(failures.items())
        ],
        checked_at=datetime.now(tz=UTC),
    )
