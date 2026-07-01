"""
Auth Presentation Schemas (Pydantic)
=====================================
Request/response schemas for the auth API endpoints.
These are ONLY for serialization/deserialization — not domain logic.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


# ── Request Schemas ───────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    """
    OAuth2 password flow uses form data, not JSON.
    This schema is used for the JSON variant of the login endpoint.
    """
    email: EmailStr
    password: str = Field(..., min_length=8)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


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

    model_config = {"from_attributes": True}


class AuthResponse(BaseModel):
    """Returned on login and token refresh."""
    user: UserResponse
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    access_token_expires_at: datetime | None = None
