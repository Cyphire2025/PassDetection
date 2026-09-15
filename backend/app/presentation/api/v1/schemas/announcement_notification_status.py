"""Aggregate push diagnostics, deliberately excluding recipient/device identities."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AnnouncementRecipientCounts(BaseModel):
    total: int = 0
    queued: int = 0
    sent: int = 0
    failed: int = 0
    cancelled: int = 0
    read: int = 0
    no_active_registration: int = 0


class AnnouncementDeviceDeliveryCounts(BaseModel):
    total: int = 0
    submitting: int = 0
    retry: int = 0
    receipt_pending: int = 0
    delivered: int = 0
    failed: int = 0
    cancelled: int = 0


class AnnouncementNotificationFailure(BaseModel):
    scope: Literal["recipient", "device"]
    code: str
    count: int


class AnnouncementNotificationStatusResponse(BaseModel):
    announcement_id: UUID
    provider_enabled: bool
    recipient_counts: AnnouncementRecipientCounts
    device_delivery_counts: AnnouncementDeviceDeliveryCounts
    failures: list[AnnouncementNotificationFailure] = Field(default_factory=list)
    checked_at: datetime
