"""Explicit authored notification review/send contracts; previews never send."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NotificationAudience = Literal["all_active_trips", "selected_groups"]


class NotificationDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=240)
    audience: NotificationAudience
    group_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)

    @field_validator("group_ids")
    @classmethod
    def unique_groups(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Choose each group once")
        return sorted(value, key=str)

    @model_validator(mode="after")
    def audience_shape(self) -> NotificationDraftInput:
        if (self.audience == "selected_groups") != bool(self.group_ids):
            raise ValueError("Specific groups require group_ids; all active trips must omit them")
        return self


class NotificationDraftUpdate(NotificationDraftInput):
    expected_revision: int = Field(ge=1)


class NotificationDraftResponse(NotificationDraftInput):
    group_names: list[str]
    id: uuid.UUID
    revision: int
    status: Literal["draft", "sent"]
    last_sent_at: datetime | None
    created_at: datetime
    updated_at: datetime


class NotificationDraftPage(BaseModel):
    items: list[NotificationDraftResponse]
    next_cursor: str | None = None


class NotificationPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)


class NotificationRoleCounts(BaseModel):
    passengers: int = 0
    client_managers: int = 0
    coordinators: int = 0


class NotificationPreviewResponse(BaseModel):
    draft_revision: int
    preview_token: str
    expires_at: datetime
    group_count: int
    group_ids: list[uuid.UUID]
    group_names: list[str]
    recipient_count: int
    role_counts: NotificationRoleCounts
    eligible_device_count: int
    no_active_registration_count: int
    provider_enabled: bool
    android_provider_enabled: bool
    ios_provider_enabled: bool
    delivery_window_hours: int = 24


class NotificationSendRequest(NotificationPreviewRequest):
    preview_token: str = Field(min_length=1, max_length=4096)
    request_id: uuid.UUID


class NotificationRecipientCounts(BaseModel):
    total: int = 0
    queued: int = 0
    sent: int = 0
    failed: int = 0
    cancelled: int = 0
    unknown: int = 0
    read: int = 0
    no_active_registration: int = 0


class NotificationDeviceCounts(BaseModel):
    total: int = 0
    submitting: int = 0
    retry: int = 0
    receipt_pending: int = 0
    provider_accepted: int = 0
    delivered: int = 0
    failed: int = 0
    cancelled: int = 0
    unknown: int = 0


class NotificationBatchResponse(BaseModel):
    id: uuid.UUID
    notification_id: uuid.UUID
    request_id: uuid.UUID
    draft_revision: int
    title: str
    body: str
    audience: NotificationAudience
    group_ids: list[uuid.UUID]
    group_names: list[str]
    role_counts: NotificationRoleCounts
    created_at: datetime
    expires_at: datetime
    recipient_counts: NotificationRecipientCounts
    device_delivery_counts: NotificationDeviceCounts
    provider_enabled: bool


class NotificationBatchPage(BaseModel):
    items: list[NotificationBatchResponse]
    next_cursor: str | None = None
