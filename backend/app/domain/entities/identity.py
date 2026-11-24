"""Agency and staff account entities and their local access predicates."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.domain.entities.enums import UserRole
from app.domain.entities.factories import _new_uuid, _utcnow


@dataclass
class User:
    """
    Represents an authenticated platform user (agency staff or admin).

    Business rules:
      - Email must be unique across the platform.
      - Password is always stored as a bcrypt hash — never plaintext.
      - Deactivated users cannot log in.
    """

    id: uuid.UUID
    email: str
    hashed_password: str
    full_name: str
    role: UserRole
    agency_id: uuid.UUID | None
    is_active: bool = True
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    last_login_at: datetime | None = None
    credential_state: str = "active"
    session_version: int = 1
    mfa_required: bool = False
    mfa_enabled: bool = False
    # Request-only access-level context; never persisted as the account's role.
    actual_role: UserRole | None = None
    actual_agency_id: uuid.UUID | None = None
    access_level_agency_name: str | None = None

    @classmethod
    def create(
        cls,
        email: str,
        hashed_password: str,
        full_name: str,
        role: UserRole,
        agency_id: uuid.UUID | None = None,
    ) -> User:
        """Factory method — enforces valid construction."""
        return cls(
            id=_new_uuid(),
            email=email.lower().strip(),
            hashed_password=hashed_password,
            full_name=full_name.strip(),
            role=role,
            agency_id=agency_id,
        )

    def record_login(self) -> None:
        """Update last login timestamp."""
        self.last_login_at = _utcnow()
        self.updated_at = _utcnow()

    def deactivate(self) -> None:
        """Deactivate the user account."""
        self.is_active = False
        self.updated_at = _utcnow()

    def can_manage_agency(self, agency_id: uuid.UUID) -> bool:
        """Check if this user can manage a specific agency."""
        if self.role == UserRole.SUPER_ADMIN:
            return True
        return self.agency_id == agency_id and self.role == UserRole.AGENCY_ADMIN

    def can_access_agency(self, agency_id: uuid.UUID) -> bool:
        """Check if this user can view resources for a specific agency."""
        if self.role == UserRole.SUPER_ADMIN:
            return True
        return self.agency_id == agency_id and self.role in {
            UserRole.AGENCY_ADMIN,
            UserRole.AGENCY_MANAGER,
            UserRole.AGENCY_STAFF,
        }


@dataclass
class Agency:
    """
    Represents a travel agency that uses the platform.

    An agency owns upload links and passport submissions.
    """

    id: uuid.UUID
    name: str
    email: str
    phone: str | None
    is_active: bool = True
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    @classmethod
    def create(cls, name: str, email: str, phone: str | None = None) -> Agency:
        return cls(
            id=_new_uuid(),
            name=name.strip(),
            email=email.lower().strip(),
            phone=phone,
        )
