"""Contracts for creating a broadcast from an existing passport group."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBroadcastGroupDetailResponse,
    WhatsAppContactPreviewRecipient,
    WhatsAppSupportContactInput,
)


class WhatsAppSourceGroupOption(BaseModel):
    id: uuid.UUID
    name: str
    submission_count: int
    import_only: bool = False


class WhatsAppSourceContact(BaseModel):
    source_submission_id: uuid.UUID
    name: str
    phone_number: str
    normalized_phone_number: str | None = None
    issue: str | None = None
    imported_fields: dict[str, str] = Field(default_factory=dict)


class WhatsAppSourceExcludedCounts(BaseModel):
    missing_phone: int = 0
    invalid_phone: int = 0
    unverified_phone: int = 0
    missing_name: int = 0
    name_too_long: int = 0
    duplicate_phone: int = 0


class WhatsAppSourceGroupPreview(BaseModel):
    source_group_id: uuid.UUID
    source_group_name: str
    source_import_only: bool = False
    total_submissions: int
    recipient_count: int
    recipients: list[WhatsAppContactPreviewRecipient]
    contacts: list[WhatsAppSourceContact] = Field(default_factory=list)
    shared_phone_count: int = 0
    needs_attention_count: int = 0
    excluded_count: int
    excluded_counts: WhatsAppSourceExcludedCounts
    preview_revision: str


class WhatsAppSourceGroupCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_group_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    organizing_company_name: str | None = Field(default=None, max_length=100)
    support_contacts: list[WhatsAppSupportContactInput] = Field(min_length=1, max_length=3)
    recipient_opt_in_confirmed: bool
    preview_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class WhatsAppSourceGroupCreateResponse(BaseModel):
    group: WhatsAppBroadcastGroupDetailResponse
    source: WhatsAppSourceGroupPreview


class WhatsAppBroadcastSourceContact(WhatsAppSourceContact):
    source_group_id: uuid.UUID
    source_group_name: str
    source_import_only: bool
    recipient_id: uuid.UUID | None = None


class WhatsAppBroadcastSourceRoster(BaseModel):
    sources: list[WhatsAppSourceGroupOption]
    total_contacts: int
    unique_phone_count: int
    shared_phone_count: int
    needs_attention_count: int
    contacts: list[WhatsAppBroadcastSourceContact]
