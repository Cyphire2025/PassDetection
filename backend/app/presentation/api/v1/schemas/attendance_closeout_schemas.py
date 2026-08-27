"""Privacy-bounded attendance closeout checkpoint contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AttendanceCloseoutCheckpointRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Optional during the rolling compatibility window. New browser clients
    # send the server-issued runtime registration; native mobile routes derive
    # it from bearer claims. Older clients remain legacy account-scoped.
    runtime_id: uuid.UUID | None = None
    pending_count: int = Field(ge=0, le=1_000_000)
    sending_count: int = Field(ge=0, le=1_000_000)
    retryable_count: int = Field(ge=0, le=1_000_000)
    needs_review_count: int = Field(ge=0, le=1_000_000)
    unreviewed_rejected_count: int = Field(ge=0, le=1_000_000)
    oldest_pending_age_seconds: int | None = Field(
        default=None,
        ge=0,
        le=31_536_000,
    )

    @model_validator(mode="after")
    def require_oldest_pending_age(self) -> AttendanceCloseoutCheckpointRequest:
        delivery_count = self.pending_count + self.sending_count + self.retryable_count
        if delivery_count == 0 and self.oldest_pending_age_seconds is not None:
            raise ValueError("Oldest pending age must be omitted for an empty delivery queue")
        if delivery_count > 0 and self.oldest_pending_age_seconds is None:
            raise ValueError("Oldest pending age is required for unresolved delivery")
        return self


class AttendanceCloseoutCheckpointResponse(AttendanceCloseoutCheckpointRequest):
    reported_at: datetime


class AttendanceCloseoutCoordinatorStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    coordinator_id: uuid.UUID
    coordinator_name: str
    runtime_id: uuid.UUID | None = None
    runtime_kind: Literal["native_mobile", "pwa", "webview", "legacy_account"] = "legacy_account"
    runtime_status: Literal["active", "revoked", "expired", "lost", "replaced"] = "active"
    state: Literal["ready", "missing", "stale", "blocked"]
    reported_at: datetime | None = None
    report_age_seconds: int | None = Field(default=None, ge=0)
    pending_count: int = Field(ge=0)
    sending_count: int = Field(ge=0)
    retryable_count: int = Field(ge=0)
    needs_review_count: int = Field(ge=0)
    unreviewed_rejected_count: int = Field(ge=0)
    oldest_pending_age_seconds: int | None = Field(default=None, ge=0)


class AttendanceCloseoutStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    ready: bool
    checkpoint_ttl_seconds: int = Field(ge=1)
    active_assignment_count: int = Field(ge=0)
    ready_assignment_count: int = Field(ge=0)
    missing_assignment_count: int = Field(ge=0)
    stale_assignment_count: int = Field(ge=0)
    nonzero_assignment_count: int = Field(ge=0)
    blocked_assignment_count: int = Field(ge=0)
    unresolved_count: int = Field(ge=0)
    oldest_pending_age_seconds: int | None = Field(default=None, ge=0)
    coordinators: list[AttendanceCloseoutCoordinatorStatusResponse]


class AttendanceCloseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exception_reason: str | None = Field(default=None, min_length=10, max_length=500)

    @field_validator("exception_reason")
    @classmethod
    def normalize_exception_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if len(normalized) < 10:
            raise ValueError("A closeout exception reason must contain at least 10 characters")
        return normalized
