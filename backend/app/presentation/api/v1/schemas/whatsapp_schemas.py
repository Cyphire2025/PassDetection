"""Pydantic request and response contracts for WhatsApp broadcast routes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.application.use_cases.whatsapp.recipient_capacity import (
    MAX_WHATSAPP_RECIPIENTS,
)


class WhatsAppRecipientInput(BaseModel):
    name: str | None = None
    phone_number: str = Field(min_length=6, max_length=64)
    imported_fields: dict[str, str] = Field(default_factory=dict)


class WhatsAppContactPreviewRecipient(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    phone_number: str = Field(min_length=9, max_length=16)
    imported_fields: dict[str, str] = Field(default_factory=dict)


WhatsAppContactRejectionCode = Literal[
    "missing_phone",
    "invalid_phone",
    "missing_name",
    "duplicate_phone",
]


class WhatsAppContactPreviewRejectedRow(BaseModel):
    sheet_name: str = Field(min_length=1, max_length=31)
    row_number: int = Field(ge=1)
    raw_name: str | None = Field(default=None, max_length=256)
    raw_phone_number: str | None = Field(default=None, max_length=64)
    imported_fields: dict[str, str] = Field(default_factory=dict)
    reason_code: WhatsAppContactRejectionCode
    reason: str = Field(min_length=1, max_length=256)


class WhatsAppContactPreviewResponse(BaseModel):
    recipient_count: int
    accepted_count: int
    recipients: list[WhatsAppContactPreviewRecipient]
    rejected_count: int
    rejected_rows: list[WhatsAppContactPreviewRejectedRow]
    rejected_rows_truncated: bool
    omitted_rejected_count: int


class WhatsAppRejectedContactInput(BaseModel):
    source_file_name: str = Field(min_length=1, max_length=255)
    sheet_name: str = Field(min_length=1, max_length=31)
    row_number: int = Field(ge=1, le=1_048_576)
    raw_name: str | None = Field(default=None, max_length=256)
    raw_phone_number: str | None = Field(default=None, max_length=64)
    imported_fields: dict[str, str] = Field(default_factory=dict)
    reason_code: WhatsAppContactRejectionCode


class WhatsAppRejectedContactResponse(BaseModel):
    id: uuid.UUID
    source_file_name: str
    sheet_name: str
    row_number: int
    raw_name: str | None
    raw_phone_number: str | None
    imported_fields: dict[str, str] = Field(default_factory=dict)
    reason_code: WhatsAppContactRejectionCode
    reason: str
    created_at: datetime


class WhatsAppRejectedContactListResponse(BaseModel):
    items: list[WhatsAppRejectedContactResponse]
    total: int
    limit: int
    offset: int


class WhatsAppRejectedContactResolveRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    phone_number: str = Field(min_length=1, max_length=64)
    recipient_opt_in_confirmed: bool


class WhatsAppSupportContactInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    phone_number: str = Field(min_length=6, max_length=64)


class WhatsAppRecipientResponse(BaseModel):
    id: uuid.UUID
    name: str | None
    phone_number: str
    normalized_phone_number: str
    imported_fields: dict[str, str] = Field(default_factory=dict)
    sent_message_types: list[str] = Field(default_factory=list)
    message_statuses: list["WhatsAppRecipientMessageStatusResponse"] = Field(default_factory=list)


class WhatsAppRecipientMessageStatusResponse(BaseModel):
    message_type: str
    status: str
    already_sent: bool
    send_suppressed: bool
    latest_resend_status: str | None = None
    resend_blocked: bool = False
    submitted_at: datetime | None
    status_updated_at: datetime


class WhatsAppReplacedRecipientResponse(BaseModel):
    recipient_id: uuid.UUID
    resolution_id: uuid.UUID
    client_group_id: uuid.UUID
    client_group_name: str
    name: str | None
    phone_number: str
    normalized_phone_number: str
    imported_fields: dict[str, str] = Field(default_factory=dict)
    replacement_submission_id: uuid.UUID
    replacement_name: str
    replacement_phone: str | None = None
    replaced_at: datetime


class WhatsAppUnidentifiedUploadResponse(BaseModel):
    submission_id: uuid.UUID
    client_group_id: uuid.UUID
    client_group_name: str
    name: str
    phone_number: str | None = None
    email: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime


class WhatsAppRecipientRosterItemResponse(BaseModel):
    kind: Literal["recipient", "rejected", "replaced", "unidentified"]
    display_order: int
    recipient: WhatsAppRecipientResponse | None = None
    rejected_contact: WhatsAppRejectedContactResponse | None = None
    replaced_recipient: WhatsAppReplacedRecipientResponse | None = None
    unidentified_upload: WhatsAppUnidentifiedUploadResponse | None = None


class WhatsAppRecipientRosterCountsResponse(BaseModel):
    all: int
    sent: int
    failed: int
    rejected: int
    replaced: int
    unidentified: int


class WhatsAppRecipientRosterResponse(BaseModel):
    items: list[WhatsAppRecipientRosterItemResponse]
    counts: WhatsAppRecipientRosterCountsResponse


class WhatsAppSupportContactResponse(BaseModel):
    id: uuid.UUID
    name: str
    phone_number: str
    normalized_phone_number: str


class WhatsAppBroadcastGroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    organizing_company_name: str
    # Delivery actions use active valid recipients. The total is the visible
    # roster size and also includes unresolved rejected spreadsheet rows.
    recipient_count: int
    total_contact_count: int
    recipient_opt_in_confirmed: bool
    created_at: datetime
    updated_at: datetime


class WhatsAppBroadcastGroupDetailResponse(WhatsAppBroadcastGroupResponse):
    recipients: list[WhatsAppRecipientResponse]
    support_contacts: list[WhatsAppSupportContactResponse]
    rejected_contact_count: int


class WhatsAppSendRequest(BaseModel):
    message_type: str = Field(pattern="^(welcome|passport_link|reminder)$")
    passport_intro: str | None = Field(default=None, max_length=600)
    passport_link: str | None = None
    message_content: str | None = Field(default=None, max_length=600)
    header_image_id: str | None = Field(default=None, max_length=255)
    recipient_ids: list[uuid.UUID] | None = Field(
        default=None,
        max_length=MAX_WHATSAPP_RECIPIENTS,
    )
    support_contact_ids: list[uuid.UUID] | None = Field(default=None, max_length=1)


class WhatsAppResendRequest(WhatsAppSendRequest):
    pass


class WhatsAppRecipientPhoneUpdateRequest(BaseModel):
    phone_number: str = Field(min_length=1, max_length=64)


class WhatsAppPreviewRequest(WhatsAppSendRequest):
    recipient_id: uuid.UUID | None = None
    resend_recipient_id: uuid.UUID | None = None


class WhatsAppPreviewResponse(BaseModel):
    message_type: str
    template_name: str
    recipient_id: uuid.UUID
    recipient_name: str
    recipient_count: int
    eligible_recipient_count: int
    already_sent_count: int
    in_progress_count: int
    uncertain_recipient_count: int
    passport_intro: str | None
    passport_link: str | None
    message_content: str
    header_image_id: str | None
    content_source: Literal["default", "latest_group", "latest_recipient"]
    rendered_message: str
    header_parameter_values: list[str]
    parameter_values: list[str]


class WhatsAppWelcomeMediaResponse(BaseModel):
    media_id: str
    file_name: str
    content_type: str


class WhatsAppSendResult(BaseModel):
    recipient_id: uuid.UUID
    phone_number: str
    status: str
    provider_message_id: str | None = None
    error_message: str | None = None


class WhatsAppSendResponse(BaseModel):
    batch_id: uuid.UUID | None = None
    queued: int = 0
    sent: int
    failed: int
    delivery_unknown: int = 0
    skipped_already_sent: int = 0
    skipped_in_progress: int = 0
    skipped_delivery_unknown: int = 0
    results: list[WhatsAppSendResult]


class WhatsAppBatchSummaryResponse(BaseModel):
    """Compact batch progress payload used by the polling UI."""

    batch_id: uuid.UUID
    queued: int
    sent: int
    failed: int
    delivery_unknown: int


class WhatsAppWebhookAck(BaseModel):
    ok: bool = True
    processed_statuses: int = 0
    received_messages: int = 0
