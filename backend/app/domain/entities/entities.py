"""
Domain Entities — Core Business Objects
========================================
Entities are the heart of the domain layer.
They encapsulate identity and business rules.

Rules:
  - No ORM imports (SQLAlchemy is infrastructure).
  - No HTTP framework imports.
  - Entities use Python dataclasses or plain classes.
  - All mutation goes through domain methods, never direct attribute setting.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


# ── Enumerations ──────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    """Roles controlling access throughout the platform."""
    SUPER_ADMIN = "super_admin"
    AGENCY_ADMIN = "agency_admin"
    AGENCY_STAFF = "agency_staff"


class PassportProcessingStatus(str, Enum):
    """Lifecycle states of a passport submission."""
    PENDING_UPLOAD = "pending_upload"
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    REVIEW_REQUIRED = "review_required"
    CLIENT_SUBMITTED = "client_submitted"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class GroupStatus(str, Enum):
    """States for a client group and its common upload link."""
    ACTIVE = "active"
    CLOSED = "closed"
    ARCHIVED = "archived"


# ── User Entity ───────────────────────────────────────────────────────────────

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

    @classmethod
    def create(
        cls,
        email: str,
        hashed_password: str,
        full_name: str,
        role: UserRole,
        agency_id: uuid.UUID | None = None,
    ) -> "User":
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
            UserRole.AGENCY_STAFF,
        }


# ── Agency Entity ─────────────────────────────────────────────────────────────

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
    def create(cls, name: str, email: str, phone: str | None = None) -> "Agency":
        return cls(
            id=_new_uuid(),
            name=name.strip(),
            email=email.lower().strip(),
            phone=phone,
        )


# ── Client Group Entity ────────────────────────────────────────────────────────

@dataclass
class ClientGroup:
    """
    A group of clients (e.g., a tour group) managed by an agency.

    Business rules:
      - Has a common upload link token shared via WhatsApp/email.
      - Can accept multiple passport submissions.
      - Can be closed or archived.
    """

    id: uuid.UUID
    name: str
    token: str
    agency_id: uuid.UUID
    status: GroupStatus
    created_by_user_id: uuid.UUID
    created_at: datetime = field(default_factory=_utcnow)
    closed_at: datetime | None = None

    @classmethod
    def create(
        cls,
        name: str,
        token: str,
        agency_id: uuid.UUID,
        created_by_user_id: uuid.UUID,
    ) -> "ClientGroup":
        return cls(
            id=_new_uuid(),
            name=name.strip(),
            token=token,
            agency_id=agency_id,
            status=GroupStatus.ACTIVE,
            created_by_user_id=created_by_user_id,
        )

    def is_active(self) -> bool:
        """True if the group is still accepting uploads."""
        return self.status == GroupStatus.ACTIVE

    def close(self) -> None:
        """Close the group so no more uploads are accepted."""
        self.status = GroupStatus.CLOSED
        self.closed_at = _utcnow()

    def archive(self) -> None:
        """Archive the group so it is hidden from active workflows."""
        self.status = GroupStatus.ARCHIVED
        self.closed_at = self.closed_at or _utcnow()

    def restore(self) -> None:
        """Restore an archived group to active workflows."""
        self.status = GroupStatus.ACTIVE
        self.closed_at = None


# ── Passport Submission Entity ────────────────────────────────────────────────

@dataclass
class PassportSubmission:
    """
    Represents a passport image submitted by a client.

    This is the central entity of the platform.
    It tracks the image, extracted fields, processing status,
    and confidence scores.
    """

    id: uuid.UUID
    group_id: uuid.UUID
    agency_id: uuid.UUID
    client_name: str
    client_email: str | None
    client_phone: str | None
    image_s3_key: str                          # Key in S3 bucket
    thumbnail_s3_key: str | None
    status: PassportProcessingStatus
    extracted_fields: dict | None              # Raw extraction result
    confirmed_fields: dict | None              # Client-reviewed final data
    overall_confidence: float | None
    confidence_score: dict | None              # Layered confidence breakdown
    mrz_raw: str | None                        # Raw MRZ string
    error_message: str | None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    client_reviewed_at: datetime | None = None
    confirmed_at: datetime | None = None

    @classmethod
    def create(
        cls,
        group_id: uuid.UUID,
        agency_id: uuid.UUID,
        client_name: str,
        client_email: str | None,
        image_s3_key: str,
    ) -> "PassportSubmission":
        return cls(
            id=_new_uuid(),
            group_id=group_id,
            agency_id=agency_id,
            client_name=client_name.strip(),
            client_email=client_email.lower().strip() if client_email else None,
            client_phone=None,
            image_s3_key=image_s3_key,
            thumbnail_s3_key=None,
            status=PassportProcessingStatus.UPLOADED,
            extracted_fields=None,
            confirmed_fields=None,
            overall_confidence=None,
            confidence_score=None,
            mrz_raw=None,
            error_message=None,
        )

    def mark_processing(self) -> None:
        self.status = PassportProcessingStatus.PROCESSING
        self.updated_at = _utcnow()

    def mark_review_required(
        self,
        extracted_fields: dict,
        confidence: float,
        confidence_score: dict | None = None,
        mrz_raw: str | None = None,
    ) -> None:
        self.status = PassportProcessingStatus.REVIEW_REQUIRED
        self.extracted_fields = extracted_fields
        self.overall_confidence = confidence
        self.confidence_score = confidence_score
        self.mrz_raw = mrz_raw
        self.updated_at = _utcnow()

    def confirm(self, confirmed_fields: dict) -> None:
        self.status = PassportProcessingStatus.CONFIRMED
        self.confirmed_fields = confirmed_fields
        self.confirmed_at = _utcnow()
        self.updated_at = _utcnow()

    def submit_client_review(
        self,
        confirmed_fields: dict,
        *,
        client_email: str,
        client_phone: str,
    ) -> None:
        self.status = PassportProcessingStatus.CLIENT_SUBMITTED
        self.client_email = client_email.lower().strip()
        self.client_phone = client_phone.strip()
        self.confirmed_fields = confirmed_fields
        self.client_reviewed_at = _utcnow()
        self.updated_at = _utcnow()

    def mark_failed(self, reason: str) -> None:
        self.status = PassportProcessingStatus.FAILED
        self.error_message = reason
        self.updated_at = _utcnow()
