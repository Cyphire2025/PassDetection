"""Focused passport collection API contracts."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.domain.value_objects.phone_number import normalize_phone_number


class ConfirmPassportSubmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed_fields: dict[str, str] = Field(..., min_length=1)


class StaffApprovePassportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed_fields: dict[str, str] | None = Field(default=None, min_length=1)
    expected_extraction_revision: int = Field(..., ge=0)
    review_reason: str | None = Field(default=None, max_length=240)


class ClientSubmitPassportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed_fields: dict[str, str] = Field(..., min_length=1)
    client_email: EmailStr = Field(max_length=255)
    client_phone: str = Field(min_length=8, max_length=64)
    phone_verification_id: uuid.UUID
    departure_city: str | None = Field(default=None, max_length=120)
    nearest_domestic_airport: str | None = Field(default=None, max_length=120)
    base_city: str | None = Field(default=None, max_length=120)
    staff_code: str | None = Field(default=None, max_length=80)
    agent_employee_type: str | None = Field(default=None, max_length=20)
    agent_employee_code: str | None = Field(default=None, max_length=80)
    designation: str | None = Field(default=None, max_length=160)
    agency_dealership_name: str | None = Field(default=None, max_length=200)
    meal_preference: str | None = Field(default=None, max_length=20)
    group_token: str = Field(..., min_length=10)
    submission_mode: str = Field(default="single", pattern="^(single|family)$")
    family_group_id: uuid.UUID | None = None
    family_member_index: int | None = Field(default=None, ge=0, le=100)
    family_relation: str | None = Field(default=None, max_length=80)
    family_gender: str | None = Field(default=None, max_length=40)
    family_head_name: str | None = Field(default=None, max_length=255)
    family_head_email: EmailStr | None = None
    family_head_phone: str | None = Field(default=None, max_length=64)
    custom_answers: list["ClientCustomAnswerRequest"] = Field(
        default_factory=list,
        max_length=20,
    )
    custom_detail_answers: list["ClientCustomDetailAnswerRequest"] = Field(
        default_factory=list,
        max_length=20,
    )

    @field_validator("client_phone", "family_head_phone")
    @classmethod
    def normalize_contact_phone(cls, value: str | None) -> str | None:
        if not value or not value.strip():
            return None
        normalized = normalize_phone_number(value)
        if normalized is None:
            raise ValueError(
                "Enter a valid phone number with a country code or a 10-digit Indian number."
            )
        return normalized

    @field_validator("client_phone")
    @classmethod
    def require_client_phone(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("Enter your WhatsApp number.")
        return value


class ClientCustomAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question_id: uuid.UUID
    value: str = Field(..., min_length=1, max_length=120)


class ClientCustomDetailAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    detail_id: uuid.UUID
    value: str = Field(..., min_length=1, max_length=500)


class ReconcilePassportUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upload_idempotency_key: str = Field(
        ...,
        min_length=32,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


class ReconcilePassportUploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_id: uuid.UUID | None = None


# Resolve the two request types declared after their collection request.
ClientSubmitPassportRequest.model_rebuild(_types_namespace=globals())
