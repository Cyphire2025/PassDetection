"""Public schemas for server-side email integrations.

Provider credentials, OAuth codes, encrypted locators, and raw provider
payloads intentionally have no representation in this module.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class EmailProviderAvailabilityResponse(BaseModel):
    provider: Literal["gmail", "outlook"]
    label: str
    configured: bool


class EmailIntegrationStatusResponse(BaseModel):
    enabled: bool
    sync_enabled: bool
    attachment_processing_enabled: bool
    auto_actions_enabled: bool
    ai_enabled: bool = False
    ai_notifications_enabled: bool = False
    providers: list[EmailProviderAvailabilityResponse] = Field(default_factory=list)


class EmailConnectionResponse(BaseModel):
    id: uuid.UUID
    agency_id: uuid.UUID
    agency_name: str
    provider: str
    email_address: str
    status: str
    last_successful_sync_at: datetime | None = None
    last_sync_attempt_at: datetime | None = None
    last_error_message: str | None = None
    ai_processing_enabled: bool = False
    ai_effective_enabled: bool = False
    allowed_actions: list[str] = Field(default_factory=list)


class EmailAuthorizeRequest(BaseModel):
    connection_id: uuid.UUID | None = None


# Backward-compatible import for callers that still use the Gmail-specific
# schema name. The payload is provider-neutral.
GmailAuthorizeRequest = EmailAuthorizeRequest


class EmailAuthorizationUrlResponse(BaseModel):
    authorization_url: str


class EmailConnectionActionResponse(BaseModel):
    connection_id: uuid.UUID
    status: str
    message: str


class RemoveEmailConnectionRequest(BaseModel):
    model_config = {"extra": "forbid"}

    confirmation_email: str = Field(min_length=3, max_length=320)


class RemoveEmailConnectionResponse(BaseModel):
    connection_id: uuid.UUID
    status: Literal["removed"] = "removed"
    messages_removed: int = 0
    artifacts_removed: int = 0
    reviews_removed: int = 0
    activity_events_removed: int = 0
    documents_removed: int = 0
    notifications_removed: int = 0
    storage_cleanup_pending: bool = False
    message: str


class EmailAiConnectionSettingsRequest(BaseModel):
    model_config = {"extra": "forbid"}

    enabled: bool


class EmailAiConnectionSettingsResponse(BaseModel):
    connection_id: uuid.UUID
    enabled: bool
    effective_enabled: bool
    message: str


class EmailIntegrationSummaryResponse(BaseModel):
    connected_accounts: int = 0
    relevant_emails_today: int = 0
    documents_retrieved_today: int = 0
    automatically_matched_today: int = 0
    revisions_detected_today: int = 0
    pending_review: int = 0
    retrieval_failures_today: int = 0


class EmailReviewItemResponse(BaseModel):
    id: uuid.UUID
    email_message_id: uuid.UUID
    artifact_id: uuid.UUID | None = None
    status: str
    review_type: str
    sender_email: str
    subject: str
    received_at: datetime
    artifact_name: str | None = None
    artifact_kind: str | None = None
    artifact_detected_type: str | None = None
    proposed_group_id: uuid.UUID | None = None
    proposed_group_name: str | None = None
    proposed_passenger_id: uuid.UUID | None = None
    proposed_passenger_name: str | None = None
    confidence: float
    evidence: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    proposed_action: str
    allowed_actions: list[str] = Field(default_factory=list)
    revision: int
    created_at: datetime


class EmailReviewGroupOption(BaseModel):
    id: uuid.UUID
    name: str
    destination: str | None = None
    travel_date: date | None = None


class EmailReviewPassengerOption(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    name: str
    passport_number_hint: str | None = None


class EmailReviewOptionsResponse(BaseModel):
    groups: list[EmailReviewGroupOption] = Field(default_factory=list)
    passengers: list[EmailReviewPassengerOption] = Field(default_factory=list)


class ResolveEmailReviewRequest(BaseModel):
    action: Literal[
        "approve",
        "assign",
        "mark_unrelated",
        "reject",
        "retry",
        "defer",
    ]
    group_id: uuid.UUID | None = None
    passenger_id: uuid.UUID | None = None
    document_type: Literal["visa", "flight_ticket"] | None = None
    expected_revision: int = Field(ge=0)


class EmailReviewActionResponse(BaseModel):
    review_id: uuid.UUID
    status: str
    message: str


class EmailActivityItemResponse(BaseModel):
    message_id: uuid.UUID
    connection_id: uuid.UUID
    account_email: str
    sender_email: str
    subject: str
    received_at: datetime
    relevance_status: str
    processing_status: str
    group_name: str | None = None
    retrieved_count: int = 0
    matched_count: int = 0
    review_count: int = 0
    failure_count: int = 0


class EmailArtifactDetailResponse(BaseModel):
    id: uuid.UUID
    kind: str
    filename: str | None = None
    source_host: str | None = None
    verified_content_type: str | None = None
    byte_size: int | None = None
    retrieval_status: str
    processing_status: str
    detected_type: str | None = None
    match_confidence: float | None = None
    group_id: uuid.UUID | None = None
    passenger_id: uuid.UUID | None = None
    error_message: str | None = None


class EmailActivityEventResponse(BaseModel):
    id: uuid.UUID
    event_type: str
    status: str
    title: str
    detail: str | None = None
    created_at: datetime


class EmailMessageDetailResponse(BaseModel):
    id: uuid.UUID
    connection_id: uuid.UUID
    account_email: str
    sender_email: str
    sender_name: str | None = None
    recipients: list[str] = Field(default_factory=list)
    subject: str
    body_excerpt: str
    original_email_url: str | None = None
    received_at: datetime
    relevance_status: str
    relevance_confidence: float
    relevance_evidence: list[str] = Field(default_factory=list)
    processing_status: str
    group_id: uuid.UUID | None = None
    group_name: str | None = None
    ai_used: bool = False
    artifacts: list[EmailArtifactDetailResponse] = Field(default_factory=list)
    events: list[EmailActivityEventResponse] = Field(default_factory=list)
