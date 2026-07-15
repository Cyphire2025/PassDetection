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
from datetime import date, datetime, timedelta, timezone
from enum import Enum


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


def _normalize_departure_cities(values: list[str]) -> list[str]:
    seen: set[str] = set()
    cities: list[str] = []
    for value in values:
        city = " ".join(str(value).strip().split())
        if not city:
            continue
        key = city.casefold()
        if key in seen:
            continue
        seen.add(key)
        cities.append(city[:120])
    return cities


# ── Enumerations ──────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    """Roles controlling access throughout the platform."""
    SUPER_ADMIN = "super_admin"
    AGENCY_ADMIN = "agency_admin"
    AGENCY_MANAGER = "agency_manager"
    AGENCY_STAFF = "agency_staff"
    AGENCY_COORDINATOR = "agency_coordinator"


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
    DELETED = "deleted"


class AttendanceSessionStatus(str, Enum):
    """Lifecycle states for tour attendance sessions."""
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class AttendanceScanSource(str, Enum):
    """Source used to record an attendance scan."""
    ONLINE = "online"
    OFFLINE = "offline"


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
            UserRole.AGENCY_MANAGER,
            UserRole.AGENCY_STAFF,
        }


# ── Tour Operations Entities ─────────────────────────────────────────────────

@dataclass
class PassengerQRToken:
    """
    Opaque QR token mapped to a passenger submission.

    The raw token is never represented here; persistence stores only a hash so
    leaked database rows cannot be used as scannable passenger QR codes.
    """

    id: uuid.UUID
    agency_id: uuid.UUID
    passenger_id: uuid.UUID
    token_hash: str
    token_version: int
    expires_at: datetime = field(default_factory=lambda: _utcnow() + timedelta(days=365))
    is_active: bool = True
    created_by_user_id: uuid.UUID | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    revoked_at: datetime | None = None

    def revoke(self) -> None:
        self.is_active = False
        self.revoked_at = _utcnow()
        self.updated_at = _utcnow()

    def deactivate(self) -> None:
        self.is_active = False
        self.updated_at = _utcnow()

    def activate(self) -> None:
        now = _utcnow()
        if self.revoked_at is not None or self.expires_at <= now:
            raise ValueError("Revoked or expired QR tokens cannot be activated")
        self.is_active = True
        self.updated_at = now

    def expire(self) -> None:
        now = _utcnow()
        self.is_active = False
        self.expires_at = now
        self.updated_at = now


@dataclass
class CoordinatorAssignment:
    """Assignment of one passenger to a coordinator for one group."""

    id: uuid.UUID
    agency_id: uuid.UUID
    group_id: uuid.UUID
    passenger_id: uuid.UUID
    coordinator_user_id: uuid.UUID
    assigned_by_user_id: uuid.UUID | None
    active: bool = True
    assigned_at: datetime = field(default_factory=_utcnow)
    unassigned_at: datetime | None = None

    def unassign(self) -> None:
        self.active = False
        self.unassigned_at = _utcnow()


@dataclass
class AttendanceSession:
    """A generic tour checkpoint such as Airport Arrival or Hotel Check-In."""

    id: uuid.UUID
    agency_id: uuid.UUID
    group_id: uuid.UUID
    name: str
    status: AttendanceSessionStatus
    created_by_user_id: uuid.UUID
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None

    def start(self) -> None:
        self.status = AttendanceSessionStatus.ACTIVE
        self.started_at = _utcnow()
        self.updated_at = _utcnow()

    def complete(self) -> None:
        self.status = AttendanceSessionStatus.COMPLETED
        self.completed_at = _utcnow()
        self.updated_at = _utcnow()

    def cancel(self) -> None:
        self.status = AttendanceSessionStatus.CANCELLED
        self.cancelled_at = _utcnow()
        self.updated_at = _utcnow()


@dataclass
class AttendanceRecord:
    """One idempotent passenger check-in for a session."""

    id: uuid.UUID
    agency_id: uuid.UUID
    session_id: uuid.UUID
    passenger_id: uuid.UUID
    coordinator_user_id: uuid.UUID
    scanned_at: datetime
    sync_source: AttendanceScanSource
    client_event_id: str
    device_id: str | None = None
    created_at: datetime = field(default_factory=_utcnow)


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
    created_by_user_id: uuid.UUID | None
    created_at: datetime = field(default_factory=_utcnow)
    closed_at: datetime | None = None
    destination: str | None = None
    travel_date: date | None = None
    return_date: date | None = None
    package_name: str | None = None
    departure_cities: list[str] = field(default_factory=list)
    notes: str | None = None
    deleted_at: datetime | None = None
    deleted_passport_count: int = 0
    deletion_retained_records: bool = False

    @classmethod
    def create(
        cls,
        name: str,
        token: str,
        agency_id: uuid.UUID,
        created_by_user_id: uuid.UUID,
        destination: str | None = None,
        travel_date: date | None = None,
        return_date: date | None = None,
        package_name: str | None = None,
        departure_cities: list[str] | None = None,
        notes: str | None = None,
    ) -> "ClientGroup":
        return cls(
            id=_new_uuid(),
            name=name.strip(),
            token=token,
            agency_id=agency_id,
            status=GroupStatus.ACTIVE,
            created_by_user_id=created_by_user_id,
            destination=destination.strip() if destination else None,
            travel_date=travel_date,
            return_date=return_date,
            package_name=package_name.strip() if package_name else None,
            departure_cities=_normalize_departure_cities(departure_cities or []),
            notes=notes.strip() if notes else None,
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
        """Restore an archived or retained deleted group to active workflows."""
        self.status = GroupStatus.ACTIVE
        self.closed_at = None
        self.deleted_at = None
        self.deleted_passport_count = 0
        self.deletion_retained_records = False

    def mark_deleted(self, *, passport_count: int, retain_records: bool) -> None:
        """Hide a group from workflows while preserving deletion audit metadata."""
        self.status = GroupStatus.DELETED
        self.closed_at = self.closed_at or _utcnow()
        self.deleted_at = _utcnow()
        self.deleted_passport_count = passport_count
        self.deletion_retained_records = retain_records


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
    departure_city: str | None
    submission_mode: str
    family_group_id: uuid.UUID | None
    family_member_index: int | None
    family_relation: str | None
    family_gender: str | None
    family_head_name: str | None
    family_head_email: str | None
    family_head_phone: str | None
    family_broadcast_to_member: bool
    image_s3_key: str                          # Key in S3 bucket
    thumbnail_s3_key: str | None
    passport_photo_s3_key: str | None
    passport_back_s3_key: str | None
    staff_metadata: dict | None
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
            departure_city=None,
            submission_mode="single",
            family_group_id=None,
            family_member_index=None,
            family_relation=None,
            family_gender=None,
            family_head_name=None,
            family_head_email=None,
            family_head_phone=None,
            family_broadcast_to_member=False,
            image_s3_key=image_s3_key,
            thumbnail_s3_key=None,
            passport_photo_s3_key=None,
            passport_back_s3_key=None,
            staff_metadata=None,
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
        # Excel imports are an authoritative source. OCR can enrich blank
        # imported fields but must never replace them (or make an imported row
        # disappear from normal group views while it is being reprocessed).
        preserve_submitted_status = self.status in {
            PassportProcessingStatus.CLIENT_SUBMITTED,
            PassportProcessingStatus.CONFIRMED,
        }
        if not preserve_submitted_status:
            self.status = PassportProcessingStatus.REVIEW_REQUIRED
        self.extracted_fields = extracted_fields
        if self.confirmed_fields is not None:
            merged_fields = dict(self.confirmed_fields)
            for key, value in extracted_fields.items():
                if key in {"field_validation", "field_provenance"}:
                    continue
                if not merged_fields.get(key) and value not in (None, ""):
                    merged_fields[key] = value
            self.confirmed_fields = merged_fields
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
        departure_city: str | None = None,
        submission_mode: str = "single",
        family_group_id: uuid.UUID | None = None,
        family_member_index: int | None = None,
        family_relation: str | None = None,
        family_gender: str | None = None,
        family_head_name: str | None = None,
        family_head_email: str | None = None,
        family_head_phone: str | None = None,
        family_broadcast_to_member: bool = False,
    ) -> None:
        self.status = PassportProcessingStatus.CLIENT_SUBMITTED
        self.client_email = client_email.lower().strip() if client_email else None
        self.client_phone = client_phone.strip() if client_phone else None
        self.departure_city = departure_city.strip() if departure_city else None
        self.submission_mode = submission_mode
        self.family_group_id = family_group_id
        self.family_member_index = family_member_index
        self.family_relation = family_relation.strip() if family_relation else None
        self.family_gender = family_gender.strip() if family_gender else None
        self.family_head_name = family_head_name.strip() if family_head_name else None
        self.family_head_email = family_head_email.lower().strip() if family_head_email else None
        self.family_head_phone = family_head_phone.strip() if family_head_phone else None
        self.family_broadcast_to_member = family_broadcast_to_member
        self.confirmed_fields = confirmed_fields
        self.client_reviewed_at = _utcnow()
        self.updated_at = _utcnow()

    def promote_image(self, permanent_key: str) -> None:
        self.image_s3_key = permanent_key
        self.updated_at = _utcnow()

    def promote_passport_photo(self, permanent_key: str) -> None:
        self.passport_photo_s3_key = permanent_key
        self.updated_at = _utcnow()

    def promote_passport_back(self, permanent_key: str) -> None:
        self.passport_back_s3_key = permanent_key
        self.updated_at = _utcnow()

    def mark_failed(self, reason: str) -> None:
        self.status = PassportProcessingStatus.FAILED
        self.error_message = reason
        self.updated_at = _utcnow()
