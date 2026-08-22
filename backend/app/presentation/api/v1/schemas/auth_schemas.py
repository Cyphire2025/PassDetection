"""
Auth Presentation Schemas (Pydantic)
=====================================
Request/response schemas for the auth API endpoints.
These are ONLY for serialization/deserialization — not domain logic.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

# ── Request Schemas ───────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    """
    OAuth2 password flow uses form data, not JSON.
    This schema is used for the JSON variant of the login endpoint.
    """
    email: EmailStr
    password: str = Field(..., min_length=8)


class RefreshTokenRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=1)


class CompleteIdentityActionRequest(BaseModel):
    token: str = Field(min_length=32, max_length=512)
    new_password: str = Field(min_length=10, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        from app.core.security.password import validate_password_strength

        validate_password_strength(value)
        return value


class PasswordRecoveryRequest(BaseModel):
    email: EmailStr


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=10, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        from app.core.security.password import validate_password_strength

        validate_password_strength(value)
        return value


class MFAChallengeVerifyRequest(BaseModel):
    challenge_token: str = Field(min_length=32, max_length=512)
    code: str = Field(min_length=6, max_length=64)


class MFAStepUpRequest(BaseModel):
    code: str = Field(min_length=6, max_length=64)


# ── Response Schemas ──────────────────────────────────────────────────────────

class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    agency_id: uuid.UUID | None
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime
    capabilities: list[str] = Field(default_factory=list)
    credential_state: Literal["invited", "active"] = "active"
    mfa_required: bool = False
    mfa_enabled: bool = False

    model_config = {"from_attributes": True}


class AuthResponse(BaseModel):
    """Returned on login and token refresh."""
    status: Literal["authenticated"] = "authenticated"
    user: UserResponse
    token_type: str = "bearer"
    access_token_expires_at: datetime | None = None


class AuthChallengeResponse(BaseModel):
    """No bearer session exists until this challenge is completed."""

    status: Literal["mfa_required", "mfa_enrollment_required"]
    challenge_token: str
    expires_at: datetime
    setup_secret: str | None = None
    otpauth_uri: str | None = None


class IdentityActionCompletedResponse(BaseModel):
    """A credential action completed for a non-dashboard principal."""

    status: Literal["action_completed"] = "action_completed"
    message: str
    next_step: Literal["return_to_mobile_app"] = "return_to_mobile_app"


class MFAEnrollmentResult(AuthResponse):
    recovery_codes: list[str] = Field(default_factory=list, min_length=10, max_length=10)


class PasswordRecoveryRequestResponse(BaseModel):
    message: str = "If the account can be recovered, reset instructions are available."
    development_recovery_token: str | None = None


class MFARecoveryCodesResponse(BaseModel):
    recovery_codes: list[str] = Field(min_length=10, max_length=10)
