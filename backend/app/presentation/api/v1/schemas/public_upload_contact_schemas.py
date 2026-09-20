"""Contact verification contracts for the public passport wizard."""

from __future__ import annotations

import re
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.domain.value_objects.phone_number import normalize_phone_number


class PublicContactOTPRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    group_token: str = Field(min_length=10, max_length=256)
    email: EmailStr = Field(max_length=255)
    phone_number: str = Field(min_length=8, max_length=64)

    @field_validator("phone_number")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        normalized = normalize_phone_number(value)
        digits = re.sub(r"\D", "", value)
        explicit_country_code = value.startswith(("+", "00"))
        if (
            normalized is None
            or (not explicit_country_code and len(digits) != 10)
            or (normalized.startswith("+91") and len(normalized) != 13)
        ):
            raise ValueError("Enter a valid WhatsApp number with its country code.")
        return normalized


class PublicContactOTPRequestResponse(BaseModel):
    challenge_id: uuid.UUID
    expires_in_seconds: int
    resend_after_seconds: int


class PublicContactOTPVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    group_token: str = Field(min_length=10, max_length=256)
    challenge_id: uuid.UUID
    code: str = Field(pattern=r"^[0-9]{6}$")


class PublicContactOTPVerifyResponse(BaseModel):
    phone_verification_id: uuid.UUID
    phone_number: str
    expires_in_seconds: int
