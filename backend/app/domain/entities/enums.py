"""Persisted role, group and passport workflow values shared across domain owners."""

from __future__ import annotations

from enum import Enum


class UserRole(str, Enum):
    """Roles controlling access throughout the platform."""

    SUPER_ADMIN = "super_admin"
    AGENCY_ADMIN = "agency_admin"
    AGENCY_MANAGER = "agency_manager"
    AGENCY_STAFF = "agency_staff"
    AGENCY_COORDINATOR = "agency_coordinator"
    # External client-side principal. This role intentionally has no implicit
    # agency-wide dashboard permissions; mobile access is granted only through
    # explicit GC App group assignments.
    CLIENT_MANAGER = "client_manager"


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


class PassportExtractionStatus(str, Enum):
    """Independent extraction state after image persistence succeeds."""

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
