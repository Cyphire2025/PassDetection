"""Compact contracts for the GC mobile authentication and trip APIs."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from app.domain.value_objects.trip_timezone import (
    DEFAULT_TRIP_TIMEZONE,
    normalize_trip_timezone,
)


class MobileDeviceInput(BaseModel):
    installation_id: str = Field(min_length=16, max_length=128)
    platform: Literal["android", "ios"]
    app_version: str = Field(min_length=1, max_length=40)
    device_name: str | None = Field(default=None, max_length=120)


class MobileIntegrityChallengeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["play_integrity", "app_attest"]
    action: Literal["document_download_authorize", "app_attest_key_register"]
    request_hash: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    installation_id: str = Field(min_length=16, max_length=128)
    key_id: str | None = Field(
        default=None,
        min_length=32,
        max_length=512,
        pattern=r"^[A-Za-z0-9_+/=-]+$",
    )

    @model_validator(mode="after")
    def validate_provider_shape(self) -> MobileIntegrityChallengeRequest:
        if self.provider == "play_integrity" and self.key_id is not None:
            raise ValueError("Play Integrity challenges do not use an App Attest key")
        if self.provider == "app_attest" and self.key_id is None:
            raise ValueError("App Attest challenges require a key identifier")
        if self.action == "app_attest_key_register" and self.provider != "app_attest":
            raise ValueError("Only App Attest can register an Apple key")
        return self


class MobileIntegrityChallengeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["disabled", "issued"]
    mode: Literal["disabled", "monitor", "enforce"]
    required: bool
    provider: Literal["play_integrity", "app_attest"]
    challenge_id: uuid.UUID | None = None
    provider_request_hash: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_-]{43}$",
    )
    expires_at: datetime | None = None


class MobileIntegrityProofRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: uuid.UUID
    provider: Literal["play_integrity", "app_attest"]
    proof: str = Field(min_length=16, max_length=65_536)
    installation_id: str = Field(min_length=16, max_length=128)
    key_id: str | None = Field(
        default=None,
        min_length=32,
        max_length=512,
        pattern=r"^[A-Za-z0-9_+/=-]+$",
    )

    @model_validator(mode="after")
    def validate_provider_shape(self) -> MobileIntegrityProofRequest:
        if self.provider == "play_integrity" and self.key_id is not None:
            raise ValueError("Play Integrity proofs do not use an App Attest key")
        if self.provider == "app_attest" and self.key_id is None:
            raise ValueError("App Attest proofs require a key identifier")
        return self


class MobileDocumentAuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    integrity: MobileIntegrityProofRequest | None = None


class MobileAppAttestRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: uuid.UUID
    installation_id: str = Field(min_length=16, max_length=128)
    key_id: str = Field(
        min_length=32,
        max_length=512,
        pattern=r"^[A-Za-z0-9_+/=-]+$",
    )
    attestation_object: str = Field(min_length=32, max_length=65_536)


class MobileAppAttestRegistrationResponse(BaseModel):
    registered: bool = True


class MobileOTPRequest(BaseModel):
    phone_number: str = Field(min_length=8, max_length=64)


class MobileOTPRequestResponse(BaseModel):
    """Intentionally identical whether or not an eligible identity exists."""

    accepted: bool = True
    challenge_id: uuid.UUID
    expires_in_seconds: int
    resend_after_seconds: int


class MobileOTPVerifyRequest(BaseModel):
    challenge_id: uuid.UUID
    code: str = Field(min_length=4, max_length=12, pattern=r"^[0-9]+$")
    device: MobileDeviceInput


class MobileTripClaimSummary(BaseModel):
    claim_id: uuid.UUID
    group_id: uuid.UUID
    group_name: str
    destination: str | None = None
    travel_date: date | None = None
    return_date: date | None = None
    timezone: str = Field(default=DEFAULT_TRIP_TIMEZONE, min_length=1, max_length=64)
    requires_secondary_verification: bool = False

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return normalize_trip_timezone(value)


class MobileClaimVerifyRequest(BaseModel):
    challenge_id: uuid.UUID
    claim_id: uuid.UUID | None = None
    verification_value: str | None = Field(default=None, min_length=2, max_length=128)
    device: MobileDeviceInput


class MobilePassengerTripSwitchRequest(BaseModel):
    """Select one group from the identities proven for the live session."""

    group_id: uuid.UUID
    installation_id: str = Field(min_length=16, max_length=128)


class MobileCredentialLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    device: MobileDeviceInput


class MobileActivationRequest(BaseModel):
    activation_token: str = Field(min_length=32, max_length=512)
    new_password: str = Field(min_length=10, max_length=256)
    device: MobileDeviceInput


class MobileRefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=512)
    installation_id: str = Field(min_length=16, max_length=128)


class MobileLogoutRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=32, max_length=512)


class MobilePasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=8, max_length=256)
    new_password: str = Field(min_length=10, max_length=256)
    device: MobileDeviceInput


class MobilePrincipalResponse(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    principal_type: Literal["passenger", "client_manager", "coordinator"]
    agency_id: uuid.UUID
    # The authoritative travel/passenger record selected by this mobile
    # identity.  This is intentionally distinct from ``id``: passenger
    # principals are mobile identity records, while personal resources are
    # owned by the underlying passenger submission.
    passenger_id: uuid.UUID | None = None
    display_name: str
    email: str | None = None
    phone_number: str | None = None
    force_password_change: bool = False


class MobileTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    access_token_expires_at: datetime
    refresh_token_expires_at: datetime
    session_id: uuid.UUID
    offline_authorization_lease: str = Field(
        min_length=256,
        max_length=4_096,
        pattern=r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$",
    )
    principal: MobilePrincipalResponse


class MobileOTPVerifyResponse(BaseModel):
    status: Literal[
        "claim_selection_required",
        "secondary_verification_required",
        "authenticated",
    ]
    claims: list[MobileTripClaimSummary] = Field(default_factory=list, max_length=50)
    tokens: MobileTokenResponse | None = None

    @model_validator(mode="after")
    def validate_status_payload(self) -> MobileOTPVerifyResponse:
        """Keep OTP state transitions unambiguous at the API boundary."""

        if self.status == "authenticated":
            if self.tokens is None or self.claims:
                raise ValueError(
                    "Authenticated OTP responses require tokens and no pending claims"
                )
            return self
        if self.tokens is not None:
            raise ValueError("Unauthenticated OTP responses must not contain tokens")
        if self.status == "claim_selection_required" and not self.claims:
            raise ValueError("Claim selection responses require at least one claim")
        if self.status == "secondary_verification_required" and self.claims:
            raise ValueError(
                "Secondary verification responses must not disclose claims"
            )
        return self


class MobileTripSummaryResponse(BaseModel):
    id: uuid.UUID
    name: str
    destination: str | None = None
    travel_date: date | None = None
    return_date: date | None = None
    timezone: str = Field(default=DEFAULT_TRIP_TIMEZONE, min_length=1, max_length=64)
    role: Literal["passenger", "client_manager", "coordinator"]
    access_generation: int
    itinerary_version: int
    common_document_version: int
    announcement_version: int

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return normalize_trip_timezone(value)


class MobileTripsResponse(BaseModel):
    items: list[MobileTripSummaryResponse] = Field(max_length=100)
    next_cursor: str | None = None


class MobileManifestResponse(BaseModel):
    trip: MobileTripSummaryResponse
    sync_cursor: int
    server_time: datetime
    access_expires_at: datetime | None = None
    versions: "MobileManifestVersions"
    resources: "MobileManifestResources"


class MobileManifestVersions(BaseModel):
    manifest: int = Field(ge=0)
    itinerary: int = Field(ge=0)
    common_documents: int = Field(ge=0)
    personal_documents: int = Field(ge=0)
    announcements: int = Field(ge=0)
    rooming: int = Field(ge=0)
    meals: int = Field(ge=0)
    qr: int = Field(ge=0)
    readiness: int = Field(ge=0)
    roster: int = Field(ge=0)


class MobileManifestResources(BaseModel):
    itinerary: str
    announcements: str
    common_documents: str
    personal_documents: str
    room: str
    meals: str
    qr: str
    sync_changes: str


class MobileSyncAcknowledgementRequest(BaseModel):
    trip_id: uuid.UUID
    cursor: int = Field(ge=0)
    access_generation: int = Field(ge=0)
    versions: MobileManifestVersions


class MobileSyncAcknowledgementResponse(BaseModel):
    trip_id: uuid.UUID
    cursor: int = Field(ge=0)
    access_generation: int = Field(ge=0)
    acknowledged_at: datetime


class MobileSyncChangeResponse(BaseModel):
    sequence: int
    group_id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID | None = None
    operation: Literal["upsert", "delete", "revoke"]
    version: int
    occurred_at: datetime
    payload: dict[str, object] = Field(default_factory=dict)


class MobileSyncPageResponse(BaseModel):
    changes: list[MobileSyncChangeResponse]
    next_cursor: int
    has_more: bool


class MobileSyncSnapshotResources(BaseModel):
    """Metadata-only resource map used to build a replacement local projection."""

    manifest: str
    itinerary: str
    announcements: str
    common_documents: str
    personal_documents: str | None = None
    room: str | None = None
    meals: str | None = None
    qr: str | None = None
    readiness: str | None = None
    roster: str | None = None
    attendance_sessions: str | None = None
    sync_changes: str
    acknowledge: str


class MobileSyncSnapshotResourceCounts(BaseModel):
    """Exact item counts for every paginated resource in one snapshot fence."""

    announcements: int = Field(ge=0)
    common_documents: int = Field(ge=0)
    personal_documents: int | None = Field(default=None, ge=0)
    roster: int | None = Field(default=None, ge=0)
    attendance_sessions: int | None = Field(default=None, ge=0)


class MobileSyncSnapshotResponse(BaseModel):
    """Stable rebase fence; resource bodies remain in their paginated APIs."""

    strategy: Literal["full_rebase"] = "full_rebase"
    trip: MobileTripSummaryResponse
    baseline_cursor: int = Field(ge=0)
    access_generation: int = Field(ge=0)
    server_time: datetime
    access_expires_at: datetime | None = None
    versions: MobileManifestVersions
    resources: MobileSyncSnapshotResources
    resource_counts: MobileSyncSnapshotResourceCounts
    max_incremental_changes: int = Field(gt=0)
    max_group_passengers: int = Field(gt=0)
    max_attendance_sessions_per_group: int = Field(gt=0)


class MobileItineraryItemResponse(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    location_name: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    sort_order: int = Field(ge=0)


class MobileItineraryDayResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: uuid.UUID
    day_number: int = Field(ge=1, le=365)
    trip_date: date | None = Field(default=None, alias="date")
    title: str | None = None
    sort_order: int = Field(ge=0)
    items: list[MobileItineraryItemResponse] = Field(max_length=250)


class MobileItineraryResponse(BaseModel):
    trip_id: uuid.UUID
    version: int = Field(ge=1)
    title: str
    published_at: datetime
    days: list[MobileItineraryDayResponse] = Field(max_length=365)


class MobileAnnouncementResponse(BaseModel):
    id: uuid.UUID
    trip_id: uuid.UUID
    version: int = Field(ge=1)
    title: str
    message: str
    priority: Literal["normal", "important", "emergency"]
    published_at: datetime
    available_until: datetime | None = None
    is_read: bool = False


class MobileAnnouncementPageResponse(BaseModel):
    items: list[MobileAnnouncementResponse] = Field(max_length=200)
    next_cursor: str | None = None


class MobileCommonDocumentResponse(BaseModel):
    id: uuid.UUID
    logical_document_id: uuid.UUID
    trip_id: uuid.UUID
    category: str
    title: str
    description: str | None = None
    media_type: str
    byte_size: int = Field(gt=0)
    checksum_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    version: int = Field(ge=1)
    offline_available: bool
    published_at: datetime
    updated_at: datetime


class MobileCommonDocumentPageResponse(BaseModel):
    items: list[MobileCommonDocumentResponse] = Field(max_length=200)
    next_cursor: str | None = None


class MobilePersonalDocumentResponse(BaseModel):
    id: uuid.UUID
    trip_id: uuid.UUID
    passenger_id: uuid.UUID
    scope: Literal["personal"] = "personal"
    category: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=255)
    content_type: Literal[
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/webp",
    ]
    size_bytes: int | None = Field(default=None, gt=0, le=25 * 1024 * 1024)
    version: int = Field(ge=1)
    checksum_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    offline_available: bool
    metadata_state: Literal["ready", "pending"]
    updated_at: datetime
    revoked_at: datetime | None = None


class MobilePersonalDocumentPageResponse(BaseModel):
    items: list[MobilePersonalDocumentResponse] = Field(max_length=200)
    next_cursor: str | None = None


class MobileDocumentAuthorizationResponse(BaseModel):
    document_id: uuid.UUID
    version: int = Field(ge=1)
    size_bytes: int = Field(gt=0, le=25 * 1024 * 1024)
    checksum_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    content_type: Literal[
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/webp",
    ]
    content_path: str = Field(pattern=r"^/api/v1/mobile/")
    download_token: str = Field(min_length=32, max_length=4096)
    expires_at: datetime


class MobileRoomResponse(BaseModel):
    id: uuid.UUID
    trip_id: uuid.UUID
    passenger_id: uuid.UUID
    hotel_name: str | None = None
    room_number: str | None = None
    roommate_summary: str | None = None
    version: int = Field(ge=0)
    updated_at: datetime


class MobileMealResponse(BaseModel):
    id: uuid.UUID
    trip_id: uuid.UUID
    passenger_id: uuid.UUID
    preference: str | None = None
    notes: str | None = None
    version: int = Field(ge=0)
    updated_at: datetime


class MobileQRResponse(BaseModel):
    id: uuid.UUID
    trip_id: uuid.UUID
    passenger_id: uuid.UUID
    signed_payload: str
    version: int = Field(ge=1)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    offline_allowed: bool
    updated_at: datetime


class MobileManagerReadinessResponse(BaseModel):
    trip_id: uuid.UUID
    passenger_count: int = Field(ge=0)
    passports_complete: int = Field(ge=0)
    visas_available: int = Field(ge=0)
    tickets_available: int = Field(ge=0)
    items_needing_attention: int = Field(ge=0)
    rooms_assigned: int = Field(ge=0)
    meals_confirmed: int = Field(ge=0)
    version: int = Field(ge=0)
    updated_at: datetime


class MobileCoordinatorAttendanceTokenEvidence(BaseModel):
    """Non-bearer proof used only to reject unsafe offline attendance scans."""

    token_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    token_version: int | None = Field(default=None, ge=1)
    state: Literal["active", "missing", "inactive", "revoked", "expired"]
    token_expires_at: datetime | None = None
    token_updated_at: datetime | None = None
    evidence_observed_at: datetime
    evidence_valid_until: datetime

    @model_validator(mode="after")
    def validate_active_evidence(self) -> "MobileCoordinatorAttendanceTokenEvidence":
        active_fields_present = (
            self.token_hash is not None
            and self.token_version is not None
            and self.token_expires_at is not None
            and self.token_updated_at is not None
            and self.evidence_valid_until > self.evidence_observed_at
            and self.evidence_valid_until <= self.token_expires_at
        )
        if self.state == "active" and not active_fields_present:
            raise ValueError("Active attendance evidence was incomplete")
        if self.state != "active" and self.token_hash is not None:
            raise ValueError("Inactive attendance evidence cannot expose a token hash")
        return self


class MobileCoordinatorPassengerResponse(BaseModel):
    id: uuid.UUID
    display_name: str
    employee_code: str | None = None
    attendance_status: Literal["not_marked", "present", "missing", "excused"]
    room_number: str | None = None
    meal_preference: str | None = None
    has_alert: bool = False
    attendance_token: MobileCoordinatorAttendanceTokenEvidence


class MobileCoordinatorOperationalDetail(BaseModel):
    """One bounded, display-safe imported or configured passenger attribute."""

    key: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=2048)
    source: Literal["imported", "custom_question", "custom_detail"]


class MobileCoordinatorPassengerDetailResponse(BaseModel):
    """Permission-minimized operational projection for one assigned passenger.

    This deliberately excludes passport numbers, MRZ data, document storage
    locations, extraction confidence, and internal dashboard notes.  Mobile
    clients must never receive an unreviewed ORM/JSON projection.
    """

    id: uuid.UUID
    display_name: str = Field(min_length=1, max_length=255)
    employee_code: str | None = Field(default=None, max_length=120)
    employee_type: str | None = Field(default=None, max_length=120)
    staff_code: str | None = Field(default=None, max_length=120)
    base_city: str | None = Field(default=None, max_length=120)
    agency_dealership_name: str | None = Field(default=None, max_length=200)
    zone_name: str | None = Field(default=None, max_length=120)
    attendance_status: Literal["not_marked", "present", "missing", "excused"]
    has_alert: bool = False
    phone_number: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=255)
    departure_city: str | None = Field(default=None, max_length=120)
    nearest_domestic_airport: str | None = Field(default=None, max_length=120)
    designation: str | None = Field(default=None, max_length=160)
    department: str | None = Field(default=None, max_length=160)
    gender: str | None = Field(default=None, max_length=40)
    date_of_birth: date | None = None
    nationality: str | None = Field(default=None, max_length=80)
    passport_surname: str | None = Field(default=None, max_length=160)
    passport_given_names: str | None = Field(default=None, max_length=255)
    passport_place_of_issue: str | None = Field(default=None, max_length=160)
    passport_issuing_country: str | None = Field(default=None, max_length=120)
    passport_date_of_issue: date | None = None
    passport_date_of_expiry: date | None = None
    hotel_name: str | None = Field(default=None, max_length=255)
    room_number: str | None = Field(default=None, max_length=80)
    roommate_summary: str | None = Field(default=None, max_length=500)
    meal_preference: str | None = Field(default=None, max_length=255)
    family_relation: str | None = Field(default=None, max_length=80)
    family_head_name: str | None = Field(default=None, max_length=255)
    family_head_phone: str | None = Field(default=None, max_length=32)
    family_head_email: str | None = Field(default=None, max_length=255)
    qualifier_relation: str | None = Field(default=None, max_length=80)
    emergency_contact_name: str | None = Field(default=None, max_length=255)
    emergency_contact_phone: str | None = Field(default=None, max_length=64)
    emergency_contact_relation: str | None = Field(default=None, max_length=120)
    operational_remarks: str | None = Field(default=None, max_length=2048)
    submission_mode: Literal["single", "family"]
    submission_status: str = Field(min_length=1, max_length=40)
    passport_status: Literal["available", "not_available"]
    visa_status: Literal["available", "not_available"]
    flight_ticket_status: Literal["available", "not_available"]
    insurance_status: Literal["available", "not_available"]
    hotel_voucher_status: Literal["available", "not_available"]
    other_document_status: Literal["available", "not_available"]
    attendance_token: MobileCoordinatorAttendanceTokenEvidence | None = None
    additional_details: list[MobileCoordinatorOperationalDetail] = Field(
        default_factory=list,
        max_length=300,
    )
    updated_at: datetime


class MobileCoordinatorRosterResponse(BaseModel):
    items: list[MobileCoordinatorPassengerResponse] = Field(max_length=200)
    next_cursor: str | None = None
    total: int = Field(ge=0)
    roster_revision: int = Field(ge=0, le=(2**53) - 1)


class MobileManagerPassengerResponse(BaseModel):
    id: uuid.UUID
    display_name: str = Field(min_length=1, max_length=255)
    employee_code: str | None = Field(default=None, max_length=120)
    visa_status: Literal["available", "not_available"]
    flight_ticket_status: Literal["available", "not_available"]


class MobileManagerRosterResponse(BaseModel):
    items: list[MobileManagerPassengerResponse] = Field(max_length=200)
    next_cursor: str | None = None
    total: int = Field(ge=0)


class MobileAttendanceActionInput(BaseModel):
    client_event_id: uuid.UUID
    signed_qr: str = Field(
        min_length=49,
        max_length=49,
        pattern=r"^pdatt:[A-Za-z0-9_-]{43}$",
    )
    scanned_at: datetime
    source: Literal["qr"] = "qr"
    session_id: uuid.UUID | None = None

    @field_validator("scanned_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("scanned_at must include a timezone offset")
        return value


class MobileAttendanceBatchRequest(BaseModel):
    actions: list[MobileAttendanceActionInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def require_unique_event_ids(self) -> "MobileAttendanceBatchRequest":
        ids = [item.client_event_id for item in self.actions]
        if len(ids) != len(set(ids)):
            raise ValueError("client_event_id values must be unique within a batch")
        return self


class MobileAttendanceActionResult(BaseModel):
    client_event_id: uuid.UUID
    status: Literal["accepted", "already_applied", "rejected", "refresh_required"]
    server_version: int | None = Field(default=None, ge=0)
    reason_code: str | None = Field(default=None, max_length=100)


class MobileAttendanceBatchResponse(BaseModel):
    results: list[MobileAttendanceActionResult] = Field(min_length=1, max_length=100)


class MobileAttendanceSummaryResponse(BaseModel):
    trip_id: uuid.UUID
    total: int = Field(ge=0)
    present: int = Field(ge=0)
    missing: int = Field(ge=0)
    excused: int = Field(ge=0)
    not_marked: int = Field(ge=0)
    version: int = Field(ge=0)
    updated_at: datetime


class MobileAttendanceSessionCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=160)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Attendance activity name is required")
        return normalized


class MobileAttendanceSessionResponse(BaseModel):
    id: uuid.UUID
    name: str
    status: Literal["draft", "active", "completed", "cancelled"]
    scanned_count: int = Field(ge=0)
    assigned_count: int = Field(ge=0)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class MobileAttendanceSessionPageResponse(BaseModel):
    items: list[MobileAttendanceSessionResponse] = Field(max_length=100)
    next_cursor: str | None = None


class MobileAttendanceMissingPassengerResponse(BaseModel):
    id: uuid.UUID
    display_name: str = Field(min_length=1, max_length=255)


class MobileAttendanceRosterPageResponse(BaseModel):
    session: MobileAttendanceSessionResponse
    items: list[MobileAttendanceMissingPassengerResponse] = Field(max_length=200)
    next_cursor: str | None = None


class MobileAttendanceSessionDetailsResponse(BaseModel):
    session: MobileAttendanceSessionResponse
    missing: list[MobileAttendanceMissingPassengerResponse] = Field(max_length=200)
    next_cursor: str | None = None


class MobileIncidentCreateRequest(BaseModel):
    client_event_id: uuid.UUID
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=3, max_length=2_000)
    severity: Literal["low", "medium", "high", "critical"]
    occurred_at: datetime

    @field_validator("title", "description")
    @classmethod
    def normalize_incident_text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 3:
            raise ValueError("Incident text is required")
        return normalized

    @field_validator("occurred_at")
    @classmethod
    def require_incident_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone offset")
        return value


class MobileIncidentActionResponse(BaseModel):
    client_event_id: uuid.UUID
    status: Literal["accepted", "already_applied", "rejected"]
    incident_id: uuid.UUID | None = None
    reason_code: str | None = Field(default=None, max_length=100)


class MobilePushRegistrationResponse(BaseModel):
    registration_id: uuid.UUID
    registered: bool = True


class MobilePushUnregisterRequest(BaseModel):
    installation_id: str = Field(min_length=16, max_length=128)
    provider: Literal["expo", "fcm", "apns"] | None = None


class MobilePushUnregisterResponse(BaseModel):
    unregistered: bool = True
    revoked_count: int = Field(ge=0)


class MobileNotificationResponse(BaseModel):
    id: uuid.UUID
    trip_id: uuid.UUID | None = None
    notification_type: str
    category: str
    priority: Literal["normal", "important", "emergency"]
    title: str
    body: str
    deep_link_path: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)
    available_at: datetime
    expires_at: datetime | None = None
    read_at: datetime | None = None


class MobileNotificationPageResponse(BaseModel):
    items: list[MobileNotificationResponse] = Field(max_length=200)
    next_cursor: str | None = None
    unread_count: int = Field(ge=0)


class MobileNotificationReadResponse(BaseModel):
    id: uuid.UUID
    read_at: datetime


class MobilePushRegistrationRequest(BaseModel):
    provider: Literal["expo", "fcm", "apns"]
    push_token: str = Field(min_length=16, max_length=512)
    installation_id: str = Field(min_length=16, max_length=128)

    @field_validator("push_token", mode="before")
    @classmethod
    def normalize_push_token(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value
