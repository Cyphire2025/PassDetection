"""Linked WhatsApp broadcast configuration and responses."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.presentation.api.v1.schemas.client_group_request_validation import (
    _normalize_broadcast_group_ids,
    _normalize_matching_fields_by_broadcast,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppMatchingFieldOption


class WhatsAppBroadcastSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    name: str
    archived_at: datetime | None = None
    recipient_count: int = Field(default=0, ge=0)
    available_matching_fields: list[WhatsAppMatchingFieldOption] = Field(default_factory=list)
    matching_field_keys: list[str] | None = None
    created_at: datetime
    updated_at: datetime


class ReplaceWhatsAppBroadcastLinksRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    whatsapp_broadcast_group_ids: list[uuid.UUID] = Field(
        ...,
        max_length=50,
    )
    matching_fields_by_broadcast: dict[uuid.UUID, list[str]] | None = None

    @field_validator("whatsapp_broadcast_group_ids", mode="before")
    @classmethod
    def normalize_whatsapp_broadcast_group_ids(
        cls,
        value: list[uuid.UUID] | None,
    ) -> list[uuid.UUID]:
        return _normalize_broadcast_group_ids(value)

    @field_validator("matching_fields_by_broadcast", mode="before")
    @classmethod
    def normalize_matching_fields(
        cls,
        value: object,
    ) -> dict[uuid.UUID, list[str]] | None:
        return _normalize_matching_fields_by_broadcast(value)

    @model_validator(mode="after")
    def validate_matching_fields(self) -> ReplaceWhatsAppBroadcastLinksRequest:
        if self.matching_fields_by_broadcast is not None and not set(
            self.matching_fields_by_broadcast
        ).issubset(self.whatsapp_broadcast_group_ids):
            raise ValueError("Matching fields must belong to a selected WhatsApp broadcast")
        return self


class ClientGroupWhatsAppLinksResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_group_id: uuid.UUID
    broadcasts: list[WhatsAppBroadcastSummaryResponse] = Field(default_factory=list)
    broadcast_count: int = Field(default=0, ge=0)
    recipient_count: int = Field(default=0, ge=0)
    can_manage: bool = False
