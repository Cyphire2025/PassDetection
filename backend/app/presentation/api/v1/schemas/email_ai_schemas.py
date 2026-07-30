"""Public, sanitized contracts for the AI Travel Operations Inbox."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EmailInboxDeadlineResponse(BaseModel):
    id: uuid.UUID
    deadline_type: str
    source_phrase: str
    source_timezone: str
    due_at: datetime | None = None
    confidence: float = Field(ge=0, le=1)
    is_ambiguous: bool
    status: str
    updated_at: datetime


class EmailInboxProposalResponse(BaseModel):
    id: uuid.UUID
    action_type: str
    risk_level: str
    status: str
    explanation: str
    confidence: float = Field(ge=0, le=1)
    requires_approval: bool
    allowed_actions: list[
        Literal["approve", "reject", "dismiss"]
    ] = Field(default_factory=list)
    revision: int = Field(ge=1)


class EmailInboxDraftResponse(BaseModel):
    id: uuid.UUID
    recipients: list[str] = Field(default_factory=list)
    subject: str
    body_text: str
    status: str
    revision: int = Field(ge=1)
    sending_available: Literal[False] = False
    updated_at: datetime


class EmailLinkedPassengerResponse(BaseModel):
    id: uuid.UUID
    name: str


class EmailCandidateLinkResponse(BaseModel):
    entity_type: Literal["group", "passenger"]
    entity_id: uuid.UUID
    name: str
    confidence: float = Field(ge=0, le=1)
    rationale: str
    canonical: bool = False


class EmailIntelligenceResponse(BaseModel):
    id: uuid.UUID
    status: str
    intent: str | None = None
    priority: str | None = None
    summary: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    needs_attention: bool = False
    human_review_confirmed: bool = False
    linked_group_id: uuid.UUID | None = None
    linked_group_name: str | None = None
    linked_passenger_ids: list[uuid.UUID] = Field(default_factory=list)
    linked_passengers: list[EmailLinkedPassengerResponse] = Field(
        default_factory=list
    )
    candidate_links: list[EmailCandidateLinkResponse] = Field(
        default_factory=list
    )
    risks: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    model_version: str
    schema_version: str
    completed_at: datetime | None = None
    updated_at: datetime
    deadlines: list[EmailInboxDeadlineResponse] = Field(default_factory=list)
    proposals: list[EmailInboxProposalResponse] = Field(default_factory=list)
    draft: EmailInboxDraftResponse | None = None


class EmailInboxItemResponse(BaseModel):
    message_id: uuid.UUID
    analysis_id: uuid.UUID
    connection_id: uuid.UUID
    account_email: str
    provider: str
    sender_email: str
    sender_name: str | None = None
    subject: str
    received_at: datetime
    summary: str
    intent: str
    priority: str
    confidence: float = Field(ge=0, le=1)
    needs_attention: bool
    group_id: uuid.UUID | None = None
    group_name: str | None = None
    status: str
    section: Literal[
        "needs_attention",
        "upcoming_deadlines",
        "drafts_ready",
        "waiting",
        "completed_automatically",
        "all_activity",
    ]
    next_deadline: EmailInboxDeadlineResponse | None = None
    proposal_count: int = Field(default=0, ge=0)
    draft_status: str | None = None


class EmailInboxCountsResponse(BaseModel):
    needs_attention: int = 0
    upcoming_deadlines: int = 0
    drafts_ready: int = 0
    waiting: int = 0
    completed_automatically: int = 0
    all_activity: int = 0


class EmailInboxResponse(BaseModel):
    items: list[EmailInboxItemResponse] = Field(default_factory=list)
    counts: EmailInboxCountsResponse = Field(default_factory=EmailInboxCountsResponse)
    next_cursor: str | None = None


class DecideEmailProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "reject", "dismiss"]
    expected_revision: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=1000)


class EmailProposalDecisionResponse(BaseModel):
    proposal_id: uuid.UUID
    status: str
    revision: int
    message: str


class DecideEmailDeadlineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["acknowledge", "complete", "dismiss"]
    expected_status: Literal["detected", "review_required", "acknowledged"]
    expected_updated_at: datetime

    @model_validator(mode="after")
    def require_aware_revision(self) -> "DecideEmailDeadlineRequest":
        if (
            self.expected_updated_at.tzinfo is None
            or self.expected_updated_at.utcoffset() is None
        ):
            raise ValueError("expected_updated_at must include a UTC offset")
        return self


class DecideEmailDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "dismiss"]
    expected_revision: int = Field(ge=1)


class UpdateEmailReplyDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=998)
    body_text: str = Field(min_length=1, max_length=20_000)
    expected_revision: int = Field(ge=1)


class EmailAiCorrectionValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, min_length=1, max_length=2_000)
    intent: Literal[
        "document_submission",
        "document_request",
        "itinerary_update",
        "itinerary_change",
        "visa_status",
        "information_request",
        "action_request",
        "deadline_notice",
        "deadline_update",
        "cancellation",
        "payment",
        "general_travel",
        "other",
    ] | None = None
    priority: Literal["low", "normal", "high", "urgent"] | None = None
    group_id: uuid.UUID | None = None
    passenger_ids: list[uuid.UUID] | None = Field(
        default=None,
        max_length=20,
    )
    deadline_id: uuid.UUID | None = None
    due_at: datetime | None = None
    notification_expected: bool | None = None


class EmailAiFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback_type: Literal["correction", "confirmation", "dismissal"]
    field_name: Literal[
        "analysis",
        "summary",
        "intent",
        "priority",
        "linked_group",
        "linked_passengers",
        "deadline",
        "notification",
    ]
    expected_status: Literal["completed", "review_required", "ignored"]
    expected_updated_at: datetime
    correction: EmailAiCorrectionValue | None = None
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_feedback_shape(self) -> "EmailAiFeedbackRequest":
        if self.expected_updated_at.tzinfo is None:
            raise ValueError("expected_updated_at must include a UTC offset")
        if self.feedback_type != "correction":
            if self.field_name != "analysis" or self.correction is not None:
                raise ValueError(
                    "confirmation and dismissal apply to the whole analysis"
                )
            return self
        if self.field_name == "analysis" or self.correction is None:
            raise ValueError("a typed correction value is required")
        correction = self.correction
        if correction.due_at is not None and correction.due_at.tzinfo is None:
            raise ValueError("a corrected deadline must include a UTC offset")
        valid = {
            "summary": bool(correction.text and correction.text.strip()),
            "intent": correction.intent is not None,
            "priority": correction.priority is not None,
            "linked_group": correction.group_id is not None,
            "linked_passengers": correction.passenger_ids is not None,
            "deadline": correction.due_at is not None,
            "notification": correction.notification_expected is not None,
        }
        if not valid[self.field_name]:
            raise ValueError(
                f"correction value does not match {self.field_name}"
            )
        supplied = set(correction.model_dump(exclude_none=True))
        allowed_fields = {
            "summary": {"text"},
            "intent": {"intent"},
            "priority": {"priority"},
            "linked_group": {"group_id"},
            "linked_passengers": {"passenger_ids"},
            "deadline": {"deadline_id", "due_at"},
            "notification": {"notification_expected"},
        }[self.field_name]
        if not supplied.issubset(allowed_fields):
            raise ValueError(
                f"correction contains values unrelated to {self.field_name}"
            )
        return self


class EmailAiFeedbackResponse(BaseModel):
    feedback_id: uuid.UUID
    analysis_id: uuid.UUID
    created_at: datetime
    analysis_status: str
    analysis_updated_at: datetime


class EmailAiRetryResponse(BaseModel):
    analysis_id: uuid.UUID
    status: Literal["pending"]
    retry_generation: int = Field(ge=1)
    message: str


class EmailAiRolloutTargetResponse(BaseModel):
    scope_type: Literal["agency", "user", "connection"]
    target_id: uuid.UUID
    agency_id: uuid.UUID
    owner_user_id: uuid.UUID | None = None
    connection_id: uuid.UUID | None = None
    label: str
    detail: str | None = None
    direct_enabled: bool | None = None
    effective_enabled: bool
    updated_at: datetime | None = None


class EmailAiRolloutTargetsResponse(BaseModel):
    global_enabled: bool
    global_notifications_enabled: bool
    scope_type: Literal["agency", "user", "connection"]
    items: list[EmailAiRolloutTargetResponse] = Field(default_factory=list)
    truncated: bool = False


class UpdateEmailAiRolloutPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_type: Literal["agency", "user", "connection"]
    target_id: uuid.UUID
    agency_id: uuid.UUID
    enabled: bool
    expected_updated_at: datetime | None = None

    @model_validator(mode="after")
    def require_aware_revision(
        self,
    ) -> "UpdateEmailAiRolloutPolicyRequest":
        if (
            self.expected_updated_at is not None
            and self.expected_updated_at.tzinfo is None
        ):
            raise ValueError("expected_updated_at must include a UTC offset")
        return self
