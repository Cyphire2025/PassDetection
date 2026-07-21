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
from datetime import UTC, date, datetime, timedelta
from enum import Enum

from app.domain.exceptions.exceptions import (
    StaffApprovalStaleError,
    StaffApprovalUnavailableError,
    ValidationError,
)
from app.domain.value_objects.passport_fields import reconcile_confirmed_with_extraction
from app.domain.value_objects.qualifier_relations import normalize_qualifier_choice


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


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
    # Canonical workflow states. Legacy values above remain readable for
    # backwards-compatible rows and API filters.
    PENDING_EXTRACTION = "pending_extraction"
    EXTRACTING = "extracting"
    READY_FOR_CLIENT_REVIEW = "ready_for_client_review"
    SUBMITTED = "submitted"
    AI_APPROVED = "ai_approved"
    NEEDS_REVIEW = "needs_review"
    STAFF_APPROVED = "staff_approved"


class StaffApprovalOutcome(str, Enum):
    """Stable staff-approval command outcomes."""

    APPROVED = "approved"
    ALREADY_APPROVED = "already_approved"


OFFICE_VISIBLE_PASSPORT_STATUS_VALUES = (
    PassportProcessingStatus.CLIENT_SUBMITTED.value,
    PassportProcessingStatus.CONFIRMED.value,
    PassportProcessingStatus.SUBMITTED.value,
    PassportProcessingStatus.AI_APPROVED.value,
    PassportProcessingStatus.NEEDS_REVIEW.value,
    PassportProcessingStatus.STAFF_APPROVED.value,
)

OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES = (
    PassportProcessingStatus.CLIENT_SUBMITTED.value,
    PassportProcessingStatus.CONFIRMED.value,
    PassportProcessingStatus.AI_APPROVED.value,
    PassportProcessingStatus.STAFF_APPROVED.value,
)

PENDING_REVIEW_PASSPORT_STATUS_VALUES = (
    PassportProcessingStatus.CLIENT_SUBMITTED.value,
    PassportProcessingStatus.SUBMITTED.value,
    PassportProcessingStatus.NEEDS_REVIEW.value,
)

CONFIRMED_PASSPORT_STATUS_VALUES = (
    PassportProcessingStatus.CONFIRMED.value,
    PassportProcessingStatus.AI_APPROVED.value,
    PassportProcessingStatus.STAFF_APPROVED.value,
)

RETRYABLE_POST_SUBMISSION_PROVIDER_STATUSES = frozenset(
    {
        "network_error",
        "provider_unavailable",
        "rate_limited",
        "timeout",
    }
)


class PassportExtractionStatus(str, Enum):
    """Independent OCR state after image persistence succeeds."""

    NOT_STARTED = "not_started"
    PROCESSING = "processing"
    COMPLETE = "extraction_complete"
    PARTIAL = "extraction_partial"
    FAILED = "extraction_failed"
    READY_FOR_REVIEW = "ready_for_review"


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
    def create(cls, name: str, email: str, phone: str | None = None) -> Agency:
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
    base_city_enabled: bool = False
    nearest_international_airport_enabled: bool = False
    staff_code_enabled: bool = False
    agent_employee_code_enabled: bool = False
    meal_preference_enabled: bool = False
    require_selfie: bool = False
    allow_files_from_device: bool = True
    ask_nearest_domestic_airport: bool = False
    relation_with_qualifier_enabled: bool = False
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
        base_city_enabled: bool = False,
        nearest_international_airport_enabled: bool = False,
        staff_code_enabled: bool = False,
        agent_employee_code_enabled: bool = False,
        meal_preference_enabled: bool = False,
        require_selfie: bool = False,
        allow_files_from_device: bool = True,
        ask_nearest_domestic_airport: bool = False,
        relation_with_qualifier_enabled: bool = False,
        notes: str | None = None,
    ) -> ClientGroup:
        normalized_name = " ".join(name.strip().split())
        if not normalized_name:
            raise ValidationError("Group name is required.", field="name")
        if travel_date and return_date and return_date < travel_date:
            raise ValidationError(
                "Return date cannot be before the Travel/Departure date.",
                field="return_date",
            )
        normalized_departure_cities = (
            _normalize_departure_cities(departure_cities or [])
            if nearest_international_airport_enabled
            else []
        )
        if nearest_international_airport_enabled and not normalized_departure_cities:
            raise ValidationError(
                "Add at least one nearest international airport.",
                field="departure_cities",
            )
        return cls(
            id=_new_uuid(),
            name=normalized_name,
            token=token,
            agency_id=agency_id,
            status=GroupStatus.ACTIVE,
            created_by_user_id=created_by_user_id,
            destination=destination.strip() if destination else None,
            travel_date=travel_date,
            return_date=return_date,
            package_name=package_name.strip() if package_name else None,
            departure_cities=normalized_departure_cities,
            base_city_enabled=base_city_enabled,
            nearest_international_airport_enabled=nearest_international_airport_enabled,
            staff_code_enabled=staff_code_enabled,
            agent_employee_code_enabled=agent_employee_code_enabled,
            meal_preference_enabled=meal_preference_enabled,
            require_selfie=require_selfie,
            allow_files_from_device=allow_files_from_device,
            ask_nearest_domestic_airport=ask_nearest_domestic_airport,
            relation_with_qualifier_enabled=relation_with_qualifier_enabled,
            notes=notes.strip() if notes else None,
        )

    def update_configuration(
        self,
        *,
        name: str,
        destination: str | None,
        travel_date: date | None,
        return_date: date | None,
        package_name: str | None,
        departure_cities: list[str] | None,
        base_city_enabled: bool,
        nearest_international_airport_enabled: bool,
        staff_code_enabled: bool,
        agent_employee_code_enabled: bool,
        meal_preference_enabled: bool,
        require_selfie: bool,
        allow_files_from_device: bool,
        ask_nearest_domestic_airport: bool,
        relation_with_qualifier_enabled: bool,
        notes: str | None,
    ) -> None:
        """Apply editable group settings through one domain boundary."""

        normalized_name = " ".join(name.strip().split())
        if not normalized_name:
            raise ValidationError("Group name is required.", field="name")
        if travel_date and return_date and return_date < travel_date:
            raise ValidationError(
                "Return date cannot be before the Travel/Departure date.",
                field="return_date",
            )
        normalized_departure_cities = (
            _normalize_departure_cities(departure_cities or [])
            if nearest_international_airport_enabled
            else []
        )
        if nearest_international_airport_enabled and not normalized_departure_cities:
            raise ValidationError(
                "Add at least one nearest international airport.",
                field="departure_cities",
            )

        self.name = normalized_name
        self.destination = " ".join(destination.strip().split()) if destination else None
        self.travel_date = travel_date
        self.return_date = return_date
        self.package_name = " ".join(package_name.strip().split()) if package_name else None
        self.departure_cities = normalized_departure_cities
        self.base_city_enabled = base_city_enabled
        self.nearest_international_airport_enabled = nearest_international_airport_enabled
        self.staff_code_enabled = staff_code_enabled
        self.agent_employee_code_enabled = agent_employee_code_enabled
        self.meal_preference_enabled = meal_preference_enabled
        self.require_selfie = require_selfie
        self.allow_files_from_device = allow_files_from_device
        self.ask_nearest_domestic_airport = ask_nearest_domestic_airport
        self.relation_with_qualifier_enabled = relation_with_qualifier_enabled
        self.notes = notes.strip() if notes else None

    def require_allowed_acquisition_mode(self, acquisition_mode: str) -> str:
        """Validate whether a public upload came through an enabled capture path."""

        normalized = acquisition_mode.strip().lower()
        if normalized not in {"camera", "file"}:
            raise ValidationError(
                "Choose a supported passport capture method.",
                field="acquisition_mode",
            )
        if normalized == "file" and not self.allow_files_from_device:
            raise ValidationError(
                "This group requires live passport scanning. Files from the device are not allowed.",
                field="acquisition_mode",
            )
        return normalized

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


@dataclass
class QualifierSelection:
    """A short-lived, server-persisted choice made before document upload."""

    id: uuid.UUID
    group_id: uuid.UUID
    token_hash: str
    is_self: bool
    relation_code: str | None
    relation_label: str
    selected_at: datetime
    expires_at: datetime
    created_at: datetime

    @classmethod
    def create(
        cls,
        *,
        group_id: uuid.UUID,
        token_hash: str,
        is_self: bool,
        relation_code: str | None,
        selected_at: datetime,
        expires_at: datetime,
    ) -> QualifierSelection:
        if expires_at <= selected_at:
            raise ValidationError(
                "Qualifier selection expiry must be after selection time.",
                field="expires_at",
            )
        canonical_self, canonical_code, label = normalize_qualifier_choice(
            is_self=is_self,
            relation_code=relation_code,
        )
        return cls(
            id=_new_uuid(),
            group_id=group_id,
            token_hash=token_hash,
            is_self=canonical_self,
            relation_code=canonical_code,
            relation_label=label,
            selected_at=selected_at,
            expires_at=expires_at,
            created_at=selected_at,
        )

    def is_expired(self, *, now: datetime | None = None) -> bool:
        return self.expires_at <= (now or _utcnow())


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
    qualifier_enabled_snapshot: bool = False
    qualifier_selection_id: uuid.UUID | None = None
    qualifier_is_self: bool | None = None
    qualifier_relation_code: str | None = None
    qualifier_relation_label: str | None = None
    qualifier_selected_at: datetime | None = None
    nearest_domestic_airport: str | None = None
    acquisition_mode: str = "file"
    upload_idempotency_key: str | None = None
    extraction_status: PassportExtractionStatus = PassportExtractionStatus.NOT_STARTED
    extraction_revision: int = 0
    extraction_conflicts: list[dict[str, str | None]] = field(default_factory=list)
    post_submission_verification: dict | None = None
    post_submission_verification_revision: int = 0
    post_submission_verified_at: datetime | None = None
    verification_reviewed_by_user_id: uuid.UUID | None = None
    verification_reviewer_name: str | None = None
    verification_reviewed_at: datetime | None = None
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
        acquisition_mode: str = "file",
        upload_idempotency_key: str | None = None,
    ) -> PassportSubmission:
        normalized_acquisition_mode = acquisition_mode.strip().lower()
        if normalized_acquisition_mode not in {"camera", "file"}:
            raise ValidationError(
                "Choose a supported passport capture method.",
                field="acquisition_mode",
            )
        normalized_idempotency_key = (
            upload_idempotency_key.strip() if upload_idempotency_key else None
        )
        if normalized_idempotency_key and len(normalized_idempotency_key) > 128:
            raise ValidationError(
                "Upload idempotency key is too long.",
                field="upload_idempotency_key",
            )
        return cls(
            id=_new_uuid(),
            group_id=group_id,
            agency_id=agency_id,
            client_name=client_name.strip(),
            client_email=client_email.lower().strip() if client_email else None,
            client_phone=None,
            departure_city=None,
            nearest_domestic_airport=None,
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
            acquisition_mode=normalized_acquisition_mode,
            upload_idempotency_key=normalized_idempotency_key,
            extraction_status=PassportExtractionStatus.NOT_STARTED,
            extraction_revision=0,
            extraction_conflicts=[],
            post_submission_verification=None,
            post_submission_verification_revision=0,
            post_submission_verified_at=None,
            verification_reviewed_by_user_id=None,
            verification_reviewer_name=None,
            verification_reviewed_at=None,
            staff_metadata=None,
            status=PassportProcessingStatus.PENDING_EXTRACTION,
            extracted_fields=None,
            confirmed_fields=None,
            overall_confidence=None,
            confidence_score=None,
            mrz_raw=None,
            error_message=None,
        )

    def attach_qualifier_selection(self, selection: QualifierSelection) -> None:
        """Snapshot one validated selection onto this single passenger."""

        if selection.group_id != self.group_id:
            raise ValidationError(
                "The qualifier selection does not belong to this upload link.",
                field="qualifier_selection_token",
            )
        self.qualifier_enabled_snapshot = True
        self.qualifier_selection_id = selection.id
        self.qualifier_is_self = selection.is_self
        self.qualifier_relation_code = selection.relation_code
        self.qualifier_relation_label = selection.relation_label
        self.qualifier_selected_at = selection.selected_at
        self.updated_at = _utcnow()

    def mark_processing(self) -> int:
        """Start a new extraction revision and return its immutable revision."""

        self.extraction_revision += 1
        self.extraction_status = PassportExtractionStatus.PROCESSING
        if self.status not in {
            PassportProcessingStatus.CLIENT_SUBMITTED,
            PassportProcessingStatus.CONFIRMED,
            PassportProcessingStatus.SUBMITTED,
            PassportProcessingStatus.AI_APPROVED,
            PassportProcessingStatus.NEEDS_REVIEW,
            PassportProcessingStatus.STAFF_APPROVED,
        }:
            self.status = PassportProcessingStatus.EXTRACTING
        self.error_message = None
        self.updated_at = _utcnow()
        return self.extraction_revision

    def ensure_reextract_allowed(self) -> None:
        """Prevent extraction from mutating a pending or canonical approved row."""

        if self.status in {
            PassportProcessingStatus.SUBMITTED,
            PassportProcessingStatus.AI_APPROVED,
            PassportProcessingStatus.STAFF_APPROVED,
        }:
            raise ValidationError(
                "Re-extraction is unavailable while this passport is submitted or approved.",
                field="status",
            )

    def mark_review_required(
        self,
        extracted_fields: dict,
        confidence: float,
        confidence_score: dict | None = None,
        mrz_raw: str | None = None,
        *,
        expected_revision: int | None = None,
    ) -> bool:
        if expected_revision is not None and expected_revision != self.extraction_revision:
            return False
        # Excel imports are an authoritative source. OCR can enrich blank
        # imported fields but must never replace them (or make an imported row
        # disappear from normal group views while it is being reprocessed).
        preserve_submitted_status = self.status in {
            PassportProcessingStatus.CLIENT_SUBMITTED,
            PassportProcessingStatus.CONFIRMED,
            PassportProcessingStatus.SUBMITTED,
            PassportProcessingStatus.AI_APPROVED,
            PassportProcessingStatus.NEEDS_REVIEW,
            PassportProcessingStatus.STAFF_APPROVED,
        }
        if not preserve_submitted_status:
            self.status = PassportProcessingStatus.READY_FOR_CLIENT_REVIEW
        required_fields = (
            "passport_number",
            "surname",
            "given_names",
            "date_of_birth",
            "date_of_expiry",
        )
        raw_verification = extracted_fields.get("ai_verification")
        raw_absent_fields = (
            raw_verification.get("absent_fields")
            if isinstance(raw_verification, dict)
            else None
        )
        absent_fields = {
            field
            for field in (
                raw_absent_fields
                if isinstance(raw_absent_fields, list)
                else []
            )
            if field == "surname"
        }
        self.extraction_status = (
            PassportExtractionStatus.COMPLETE
            if all(
                extracted_fields.get(key) or key in absent_fields
                for key in required_fields
            )
            else PassportExtractionStatus.PARTIAL
        )
        self.extracted_fields = extracted_fields
        self.confirmed_fields, self.extraction_conflicts = (
            reconcile_confirmed_with_extraction(
                self.confirmed_fields,
                extracted_fields,
            )
        )
        self.overall_confidence = confidence
        self.confidence_score = confidence_score
        self.mrz_raw = mrz_raw
        self.error_message = None
        self.updated_at = _utcnow()
        return True

    def confirm(self, confirmed_fields: dict) -> None:
        # Invalidate any extraction job that started before this correction.
        self.extraction_revision += 1
        if self.extraction_status == PassportExtractionStatus.PROCESSING:
            self.extraction_status = PassportExtractionStatus.READY_FOR_REVIEW
        self.status = PassportProcessingStatus.CONFIRMED
        self.confirmed_fields = confirmed_fields
        self.extraction_conflicts = []
        self.confirmed_at = _utcnow()
        self.updated_at = _utcnow()

    def submit_client_review(
        self,
        confirmed_fields: dict,
        *,
        client_email: str | None,
        client_phone: str | None,
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
        nearest_domestic_airport: str | None = None,
    ) -> None:
        if self.status.value in OFFICE_VISIBLE_PASSPORT_STATUS_VALUES:
            raise ValidationError(
                "Passport details were already submitted.",
                field="status",
            )
        # Invalidate any extraction job that started before this correction.
        self.extraction_revision += 1
        if self.extraction_status == PassportExtractionStatus.PROCESSING:
            self.extraction_status = PassportExtractionStatus.READY_FOR_REVIEW
        self.status = PassportProcessingStatus.SUBMITTED
        self.client_email = client_email.lower().strip() if client_email else None
        self.client_phone = client_phone.strip() if client_phone else None
        self.departure_city = departure_city.strip() if departure_city else None
        normalized_domestic_airport = (
            " ".join(nearest_domestic_airport.strip().split())
            if nearest_domestic_airport
            else None
        )
        if normalized_domestic_airport and len(normalized_domestic_airport) > 120:
            raise ValidationError(
                "Nearest domestic airport must be 120 characters or fewer.",
                field="nearest_domestic_airport",
            )
        self.nearest_domestic_airport = normalized_domestic_airport
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
        self.extraction_conflicts = []
        self.post_submission_verification_revision += 1
        self.post_submission_verification = None
        self.post_submission_verified_at = None
        self.verification_reviewed_by_user_id = None
        self.verification_reviewer_name = None
        self.verification_reviewed_at = None
        self.client_reviewed_at = _utcnow()
        self.updated_at = _utcnow()

    def apply_post_submission_verification(
        self,
        *,
        expected_revision: int,
        decision: str,
        verification: dict,
    ) -> bool:
        """Apply one revision-matched AI decision without changing client fields."""

        if (
            expected_revision != self.post_submission_verification_revision
            or self.status != PassportProcessingStatus.SUBMITTED
        ):
            return False
        if decision not in {
            PassportProcessingStatus.AI_APPROVED.value,
            PassportProcessingStatus.NEEDS_REVIEW.value,
        }:
            raise ValidationError("Unsupported post-submission verification decision.")

        now = _utcnow()
        self.status = PassportProcessingStatus(decision)
        self.post_submission_verification = dict(verification)
        self.post_submission_verified_at = now
        self.updated_at = now
        return True

    def request_post_submission_verification_retry(self) -> int:
        """Requeue only a prior decision caused by a temporary AI provider failure."""

        if self.status != PassportProcessingStatus.NEEDS_REVIEW:
            raise ValidationError(
                "AI verification can only be retried after a temporary provider failure.",
                field="status",
            )
        verification = self.post_submission_verification
        provider_status = (
            str(verification.get("provider_status", "")).strip().lower()
            if isinstance(verification, dict)
            else ""
        )
        if provider_status not in RETRYABLE_POST_SUBMISSION_PROVIDER_STATUSES:
            raise ValidationError(
                "This passport received an AI review result and cannot be re-verified automatically.",
                field="post_submission_verification",
            )
        if not self.image_s3_key or self.image_s3_key.startswith("excel-imports/"):
            raise ValidationError(
                "A stored passport front image is required for AI verification.",
                field="image_s3_key",
            )
        if not self.confirmed_fields:
            raise ValidationError(
                "Submitted passport fields are required for AI verification.",
                field="confirmed_fields",
            )

        self.post_submission_verification_revision += 1
        self.status = PassportProcessingStatus.SUBMITTED
        self.post_submission_verification = None
        self.post_submission_verified_at = None
        self.verification_reviewed_by_user_id = None
        self.verification_reviewer_name = None
        self.verification_reviewed_at = None
        self.updated_at = _utcnow()
        return self.post_submission_verification_revision

    def staff_approve_verification(
        self,
        *,
        reviewer_id: uuid.UUID,
        reviewer_name: str,
        expected_extraction_revision: int,
        confirmed_fields: dict | None = None,
    ) -> StaffApprovalOutcome:
        """Atomically save optional corrections and transition Needs Review."""

        if self.status == PassportProcessingStatus.STAFF_APPROVED:
            if confirmed_fields is not None and any(
                (self.confirmed_fields or {}).get(key) != value
                for key, value in confirmed_fields.items()
            ):
                raise StaffApprovalUnavailableError(
                    current_status=self.status.value,
                    message=(
                        "This passport was already approved with different field "
                        "values. Refresh the record before taking further action."
                    ),
                )
            return StaffApprovalOutcome.ALREADY_APPROVED
        if self.status != PassportProcessingStatus.NEEDS_REVIEW:
            raise StaffApprovalUnavailableError(
                current_status=self.status.value,
            )
        if expected_extraction_revision != self.extraction_revision:
            raise StaffApprovalStaleError(
                expected_revision=expected_extraction_revision,
                current_revision=self.extraction_revision,
            )

        # Invalidate both extraction and post-submit AI work before publishing
        # the canonical staff decision. Replays return above without incrementing.
        self.extraction_revision += 1
        self.post_submission_verification_revision += 1
        if confirmed_fields is not None:
            self.confirmed_fields = {
                **dict(self.confirmed_fields or {}),
                **dict(confirmed_fields),
            }
            self.extraction_conflicts = []
            if self.post_submission_verification is not None:
                self.post_submission_verification = {
                    **self.post_submission_verification,
                    "stale_after_staff_edit": True,
                }
        now = _utcnow()
        self.status = PassportProcessingStatus.STAFF_APPROVED
        self.verification_reviewed_by_user_id = reviewer_id
        self.verification_reviewer_name = " ".join(reviewer_name.strip().split())[:255]
        self.verification_reviewed_at = now
        self.confirmed_at = now
        self.updated_at = now
        return StaffApprovalOutcome.APPROVED

    def update_reviewed_fields(self, confirmed_fields: dict) -> None:
        """Save staff edits without bypassing the canonical approval transition."""

        self.extraction_revision += 1
        self.confirmed_fields = {
            **dict(self.confirmed_fields or {}),
            **dict(confirmed_fields),
        }
        self.extraction_conflicts = []
        if self.status in {
            PassportProcessingStatus.SUBMITTED,
            PassportProcessingStatus.AI_APPROVED,
            PassportProcessingStatus.NEEDS_REVIEW,
            PassportProcessingStatus.STAFF_APPROVED,
        }:
            self.status = PassportProcessingStatus.NEEDS_REVIEW
            self.verification_reviewed_by_user_id = None
            self.verification_reviewer_name = None
            self.verification_reviewed_at = None
            self.confirmed_at = None
            if self.post_submission_verification is not None:
                self.post_submission_verification = {
                    **self.post_submission_verification,
                    "stale_after_staff_edit": True,
                }
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
        self.extraction_status = PassportExtractionStatus.FAILED
        self.error_message = reason
        self.updated_at = _utcnow()

    def mark_extraction_failed(
        self,
        public_message: str = (
            "Some passport fields could not be read automatically. "
            "Please enter the missing details manually."
        ),
        *,
        expected_revision: int | None = None,
        diagnostics: dict[str, object] | None = None,
    ) -> bool:
        """Keep stored images reviewable after OCR failure."""

        if expected_revision is not None and expected_revision != self.extraction_revision:
            return False
        if self.status not in {
            PassportProcessingStatus.CLIENT_SUBMITTED,
            PassportProcessingStatus.CONFIRMED,
            PassportProcessingStatus.SUBMITTED,
            PassportProcessingStatus.AI_APPROVED,
            PassportProcessingStatus.NEEDS_REVIEW,
            PassportProcessingStatus.STAFF_APPROVED,
        }:
            self.status = PassportProcessingStatus.READY_FOR_CLIENT_REVIEW
        self.extraction_status = PassportExtractionStatus.FAILED
        self.error_message = public_message
        if diagnostics:
            self.extracted_fields = {
                **dict(self.extracted_fields or {}),
                **dict(diagnostics),
            }
        self.updated_at = _utcnow()
        return True
