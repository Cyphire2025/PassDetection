"""Focused passport verification API contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PassportVerificationFieldName = Literal[
    "surname",
    "given_names",
    "passport_number",
    "nationality",
    "place_of_issue",
    # Backward-compatible read support for verification results persisted
    # before place_of_issue became the canonical field.
    "issuing_country",
    "date_of_birth",
    "date_of_issue",
    "date_of_expiry",
    "sex",
]


class PostSubmissionFieldOutcomeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: PassportVerificationFieldName
    verdict: Literal["correct", "suspicious", "incorrect"]
    observed_value: str | None = Field(default=None, max_length=100)
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason_code: str = Field(..., min_length=1, max_length=64)


class PostSubmissionVerificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_status: Literal["ai_approved", "needs_review"]
    confidence: float = Field(..., ge=0.0, le=1.0)
    incorrect_fields: list[PassportVerificationFieldName] = Field(default_factory=list)
    suspicious_fields: list[PassportVerificationFieldName] = Field(default_factory=list)
    explanation: str = Field(..., min_length=1, max_length=240)
    provider_status: str = Field(..., min_length=1, max_length=64)
    reason_code: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=120)
    fields: list[PostSubmissionFieldOutcomeResponse] = Field(default_factory=list)
    stale_after_staff_edit: bool = False
