"""Passenger QR lifecycle, private delivery previews and send commands."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class GroupPassengerQrCodeResponse(BaseModel):
    passenger_id: uuid.UUID
    client_name: str
    client_email: str | None = None
    client_phone: str | None = None
    departure_city: str | None = None
    coordinator_id: uuid.UUID | None = None
    coordinator_name: str | None = None
    qr_status: str
    qr_token_version: int | None = None
    qr_created_at: datetime | None = None
    qr_expires_at: datetime | None = None
    qr_revoked_at: datetime | None = None
    qr_payload: str | None = None


class GroupPassengerQrCodesResponse(BaseModel):
    group_id: uuid.UUID
    group_name: str
    generated_at: datetime
    passengers: list[GroupPassengerQrCodeResponse] = Field(default_factory=list)


class QrDeliveryPreviewRecipient(BaseModel):
    passenger_id: uuid.UUID
    passenger_name: str
    passport_number: str | None = None
    qr_token_id: uuid.UUID | None = None
    qr_token_version: int | None = None
    qr_status: str
    recipient_id: uuid.UUID | None = None
    broadcast_group_id: uuid.UUID | None = None
    broadcast_name: str | None = None
    phone_number: str | None = None
    delivery_id: uuid.UUID | None = None
    delivery_status: str
    eligible: bool = False
    reason: str
    error_message: str | None = None
    message_preview: str | None = None


class QrDeliveryPreviewSummary(BaseModel):
    total_passengers: int = 0
    ready: int = 0
    retryable: int = 0
    already_sent: int = 0
    in_progress: int = 0
    blocked: int = 0
    ambiguous_recipients: int = 0


class QrDeliveryPreviewResponse(BaseModel):
    group_id: uuid.UUID
    template_name: str | None = None
    template_configured: bool = False
    linked_broadcast_count: int = 0
    can_send: bool = False
    configuration_error: str | None = None
    message_content: str
    summary: QrDeliveryPreviewSummary
    recipients: list[QrDeliveryPreviewRecipient] = Field(default_factory=list)


class SendQrBroadcastRequest(BaseModel):
    qr_token_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)
    message_content: str = Field(min_length=1, max_length=600)


class SendQrBroadcastResponse(BaseModel):
    send_batch_id: uuid.UUID | None = None
    queued_count: int = 0
    skipped_count: int = 0
    message: str


class PassengerQrTokenResponse(BaseModel):
    passenger_id: uuid.UUID
    status: str
    token_version: int
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    qr_payload: str | None = None


class SetPassengerQrActiveRequest(BaseModel):
    is_active: bool


class SetPassengerQrExpirationRequest(BaseModel):
    expires_at: datetime
