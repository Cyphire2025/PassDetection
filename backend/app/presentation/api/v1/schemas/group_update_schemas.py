"""Group-wide update preview and explicit send contract."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.application.use_cases.whatsapp.group_updates import GroupUpdateFilters


class GroupUpdateAudience(BaseModel):
    model_config = ConfigDict(extra="forbid")
    submission_status: Literal["all", "submitted", "not_submitted"] = "all"
    document_status: Literal["all", "sent", "pending"] = "all"
    document_type: str = "visa"

    @model_validator(mode="after")
    def validate_lane(self) -> "GroupUpdateAudience":
        GroupUpdateFilters(**self.model_dump())
        return self


class GroupUpdateAttempt(BaseModel):
    id: uuid.UUID
    status: str
    phone_number: str | None
    created_at: datetime
    status_updated_at: datetime
    message: str | None
    error: str | None
    template_name: str | None
    provider_message_id: str | None
    document_type: str | None


class GroupUpdateRecipient(BaseModel):
    audience_key: str
    name: str
    recipient_id: uuid.UUID | None
    broadcast_group_id: uuid.UUID
    passenger_id: uuid.UUID | None
    phone_number: str | None
    phone_source: Literal["submitted", "imported"]
    submission_status: Literal["submitted", "not_submitted", "needs_review"]
    document_count: int
    confirmed_count: int
    eligible: bool
    reason: str | None
    latest_update_status: str | None = None
    latest_update_at: datetime | None = None
    passport_number: str | None = None
    email: str | None = None
    imported_details: dict[str, str] = Field(default_factory=dict)
    latest_update: GroupUpdateAttempt | None = None
    update_attempt_count: int = 0


class GroupUpdatePreview(BaseModel):
    group_id: uuid.UUID
    audience: GroupUpdateAudience
    preview_token: str
    template_name: str
    template_language: str
    can_send: bool
    configuration_error: str | None
    recipients: list[GroupUpdateRecipient]


class SendGroupUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    preview_token: str = Field(pattern=r"^[a-f0-9]{64}$")
    audience: GroupUpdateAudience
    audience_keys: list[str] = Field(min_length=1, max_length=1500)
    message_content: str = Field(min_length=1, max_length=600)
