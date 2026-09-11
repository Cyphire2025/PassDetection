"""Welcome preparation for submitted traveller WhatsApp destinations."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class TravellerWelcomeSource(BaseModel):
    id: uuid.UUID
    name: str


class TravellerWelcomeRecipient(BaseModel):
    phone_number: str | None = None
    passenger_ids: list[uuid.UUID] = Field(default_factory=list)
    passenger_names: list[str] = Field(default_factory=list)
    status: str
    eligible: bool = False
    reason: str | None = None
    rendered_message: str | None = None


class TravellerWelcomeSummary(BaseModel):
    total_numbers: int = 0
    needs_welcome: int = 0
    already_welcomed: int = 0
    in_progress: int = 0
    blocked: int = 0


class TravellerWelcomePreview(BaseModel):
    group_id: uuid.UUID
    preview_token: str
    source_broadcast_id: uuid.UUID | None = None
    source_broadcast_name: str | None = None
    sources: list[TravellerWelcomeSource] = Field(default_factory=list)
    template_name: str | None = None
    template_configured: bool = False
    can_send: bool = False
    configuration_error: str | None = None
    header_image_url: str | None = None
    summary: TravellerWelcomeSummary
    recipients: list[TravellerWelcomeRecipient] = Field(default_factory=list)
    poll_after_seconds: int | None = None


class SendTravellerWelcomeRequest(BaseModel):
    phone_numbers: list[str] = Field(min_length=1, max_length=1_500)
    preview_token: str = Field(min_length=64, max_length=64)
    source_broadcast_id: uuid.UUID | None = None
    header_image_id: str | None = Field(default=None, min_length=1, max_length=255)


class SendTravellerWelcomeResponse(BaseModel):
    group_id: uuid.UUID
    batch_id: uuid.UUID | None = None
    queued_count: int = 0
    skipped_count: int = 0
    blocked_count: int = 0
    message: str
