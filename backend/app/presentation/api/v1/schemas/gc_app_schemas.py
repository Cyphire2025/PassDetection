"""Dashboard contracts for GC App administration and publication."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class ClientOrganizationCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Organization name is required")
        return normalized


class ClientOrganizationResponse(BaseModel):
    id: uuid.UUID
    agency_id: uuid.UUID
    name: str
    status: Literal["active", "inactive"]
    created_at: datetime
    updated_at: datetime


class ClientOrganizationPageResponse(BaseModel):
    items: list[ClientOrganizationResponse]
    total: int
    offset: int
    limit: int


class ClientManagerCreateRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    phone_number: str = Field(min_length=8, max_length=64)
    organization_id: uuid.UUID
    group_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    temporary_password: None = None
    return_temporary_password_once: Literal[False] = False
    invitation_flow: Literal[True] = True
    return_activation_token_once: Literal[True] = True
    force_password_change: Literal[False] = False

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def require_explicit_secret_return(self) -> ClientManagerCreateRequest:
        if self.temporary_password is not None or self.return_temporary_password_once:
            raise ValueError("Client Managers must set their own password through activation")
        return self


class ClientManagerUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = None
    phone_number: str | None = Field(default=None, min_length=8, max_length=64)
    organization_id: uuid.UUID | None = None
    expected_revision: int = Field(ge=1)


class ClientManagerStatusRequest(BaseModel):
    status: Literal["active", "suspended"]
    expected_revision: int = Field(ge=1)


class ClientManagerForcePasswordChangeRequest(BaseModel):
    force_password_change: bool
    expected_revision: int = Field(ge=1)


class ClientManagerPasswordResetRequest(BaseModel):
    issue_activation_link: Literal[True] = True

    model_config = {"extra": "forbid"}


class ClientManagerAssignmentRequest(BaseModel):
    group_ids: list[uuid.UUID] = Field(max_length=100)
    expected_revision: int = Field(ge=1)


class ClientManagerAssignedGroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    destination: str | None = None
    travel_date: date | None = None
    return_date: date | None = None
    lifecycle_status: str
    gc_enabled: bool
    client_organization_id: uuid.UUID
    client_organization_name: str


class ClientManagerResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    agency_id: uuid.UUID
    full_name: str
    email: str
    phone_number: str
    organization_id: uuid.UUID
    organization_name: str
    status: Literal["active", "suspended", "deleted", "invited"]
    force_password_change: bool
    revision: int
    group_ids: list[uuid.UUID]
    assigned_groups: list[ClientManagerAssignedGroupResponse] = Field(
        default_factory=list,
        max_length=100,
    )
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    temporary_password: str | None = None
    activation_token: str | None = None


class ClientManagerPageResponse(BaseModel):
    items: list[ClientManagerResponse]
    total: int
    offset: int
    limit: int


class ClientManagerSessionResponse(BaseModel):
    id: uuid.UUID
    platform: str
    app_version: str
    status: str
    last_seen_at: datetime | None
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


class ClientManagerSessionPageResponse(BaseModel):
    items: list[ClientManagerSessionResponse] = Field(max_length=100)
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)


class GCAppAuditResponse(BaseModel):
    id: uuid.UUID
    action: str
    entity_type: str
    entity_id: str | None
    actor_email: str | None
    metadata: dict[str, object]
    created_at: datetime


class GCAppAuditPageResponse(BaseModel):
    items: list[GCAppAuditResponse] = Field(max_length=100)
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)


class GCAgencyResponse(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    is_active: bool


class GCAgencyPageResponse(BaseModel):
    items: list[GCAgencyResponse]
    total: int
    offset: int
    limit: int


class GCGroupSearchAccess(BaseModel):
    group_id: uuid.UUID
    agency_id: uuid.UUID
    client_organization_id: uuid.UUID
    client_organization_name: str
    enabled: bool
    passenger_access_enabled: bool
    client_manager_access_enabled: bool
    coordinator_access_enabled: bool
    access_starts_at: datetime | None
    access_expires_at: datetime | None
    revoked_at: datetime | None
    access_generation: int
    itinerary_version: int
    common_document_version: int
    announcement_version: int
    revision: int
    last_successful_sync_at: datetime | None
    active_mobile_users: int = 0
    synced_device_count: int = 0
    updated_at: datetime


class GCGroupSearchItem(BaseModel):
    id: uuid.UUID
    agency_id: uuid.UUID
    name: str
    destination: str | None = None
    travel_date: date | None = None
    return_date: date | None = None
    lifecycle_status: str
    gc_enabled: bool
    client_organization_id: uuid.UUID | None = None
    client_organization_name: str | None = None
    access: GCGroupSearchAccess | None = None


class GCGroupSearchPageResponse(BaseModel):
    items: list[GCGroupSearchItem]
    total: int
    offset: int
    limit: int


class GCGroupAccessUpdateRequest(BaseModel):
    client_organization_id: uuid.UUID | None = None
    enabled: bool
    passenger_access_enabled: bool = True
    client_manager_access_enabled: bool = True
    coordinator_access_enabled: bool = True
    access_starts_at: datetime | None = None
    access_expires_at: datetime | None = None
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_window(self) -> GCGroupAccessUpdateRequest:
        if (
            self.access_starts_at is not None
            and self.access_expires_at is not None
            and self.access_expires_at <= self.access_starts_at
        ):
            raise ValueError("Access expiry must be after access start")
        return self


class GCMyPhotosFeatureUpdateRequest(BaseModel):
    enabled: bool
    expected_revision: int = Field(ge=1)


class GCGroupAccessResponse(BaseModel):
    group_id: uuid.UUID
    agency_id: uuid.UUID
    name: str
    destination: str | None = None
    travel_date: date | None = None
    return_date: date | None = None
    lifecycle_status: str
    client_organization_id: uuid.UUID
    client_organization_name: str
    enabled: bool
    passenger_access_enabled: bool
    client_manager_access_enabled: bool
    coordinator_access_enabled: bool
    my_photos_enabled: bool
    access_starts_at: datetime | None
    access_expires_at: datetime | None
    revoked_at: datetime | None
    access_generation: int
    itinerary_version: int
    common_document_version: int
    announcement_version: int
    revision: int
    last_successful_sync_at: datetime | None
    active_mobile_users: int = 0
    synced_device_count: int = 0
    updated_at: datetime


class PassengerIdentityReconciliationResponse(BaseModel):
    created: int = Field(ge=0)
    updated: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    revoked: int = Field(ge=0)
    skipped_ambiguous: int = Field(ge=0)
    skipped_without_secondary_factor: int = Field(ge=0)


class ItineraryItemInput(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    location_name: str | None = Field(default=None, max_length=255)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    sort_order: int = Field(default=0, ge=0, le=10_000)


class ItineraryDayInput(BaseModel):
    day_number: int = Field(ge=1, le=365)
    trip_date: date | None = Field(default=None, alias="date")
    title: str | None = Field(default=None, max_length=255)
    items: list[ItineraryItemInput] = Field(default_factory=list, max_length=250)

    model_config = {"populate_by_name": True}


class ItineraryDraftRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    days: list[ItineraryDayInput] = Field(min_length=1, max_length=365)
    expected_access_revision: int = Field(ge=1)

    @model_validator(mode="after")
    def bound_total_items(self) -> ItineraryDraftRequest:
        if sum(len(day.items) for day in self.days) > 1_500:
            raise ValueError("An itinerary may contain at most 1,500 items")
        return self


class ItineraryVersionResponse(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    version: int
    status: Literal["draft", "published", "retired"]
    title: str
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    days: list[ItineraryDayInput]


class CommonDocumentResponse(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    category: str
    display_name: str
    original_filename: str
    content_type: str
    size_bytes: int
    checksum_sha256: str
    version: int
    status: Literal["draft", "published", "retired", "revoked"]
    sort_order: int
    available_from: datetime | None
    available_until: datetime | None
    published_at: datetime | None
    updated_at: datetime


CommonDocumentCategory = Literal[
    "itinerary_pdf",
    "travel_tips",
    "common_instructions",
    "destination",
    "emergency",
    "hotel",
    "flight_summary",
    "meeting_point",
    "dress_code",
    "baggage",
    "other",
]


class CommonDocumentReorderRequest(BaseModel):
    ordered_document_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    expected_access_revision: int = Field(ge=1)


class AnnouncementCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    message: str = Field(min_length=1, max_length=10_000)
    priority: Literal["normal", "important", "emergency"] = "normal"
    available_from: datetime | None = None
    available_until: datetime | None = None
    expected_access_revision: int = Field(ge=1)


class AnnouncementResponse(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    title: str
    message: str
    priority: str
    status: Literal["draft", "published", "retired", "revoked"]
    version: int
    available_from: datetime | None
    available_until: datetime | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
