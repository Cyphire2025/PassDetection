"""
Upload Link Presentation Schemas
================================
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _normalize_departure_cities(values: list[str] | None) -> list[str]:
    if not values:
        return []
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


def _normalize_broadcast_group_ids(
    values: list[uuid.UUID] | None,
) -> list[uuid.UUID]:
    if not values:
        return []
    return list(dict.fromkeys(values))


class CreateClientGroupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=100)
    destination: str | None = Field(default=None, max_length=255)
    travel_date: date | None = None
    return_date: date | None = None
    package_name: str | None = Field(default=None, max_length=255)
    departure_cities: list[str] = Field(default_factory=list, max_length=50)
    base_city_enabled: bool = False
    nearest_international_airport_enabled: bool = False
    staff_code_enabled: bool = False
    meal_preference_enabled: bool = False
    require_selfie: bool = False
    allow_files_from_device: bool = True
    ask_nearest_domestic_airport: bool = False
    relation_with_qualifier_enabled: bool = False
    notes: str | None = Field(default=None, max_length=2000)
    whatsapp_broadcast_group_ids: list[uuid.UUID] = Field(
        default_factory=list,
        max_length=50,
    )

    @field_validator("departure_cities", mode="before")
    @classmethod
    def normalize_departure_cities(cls, value: list[str] | None) -> list[str]:
        return _normalize_departure_cities(value)

    @field_validator("whatsapp_broadcast_group_ids", mode="before")
    @classmethod
    def normalize_whatsapp_broadcast_group_ids(
        cls,
        value: list[uuid.UUID] | None,
    ) -> list[uuid.UUID]:
        return _normalize_broadcast_group_ids(value)

    @model_validator(mode="after")
    def validate_airport_configuration(self) -> CreateClientGroupRequest:
        if self.nearest_international_airport_enabled and not self.departure_cities:
            raise ValueError("Add at least one nearest international airport when the option is enabled.")
        if not self.nearest_international_airport_enabled:
            self.departure_cities = []
        if self.travel_date and self.return_date and self.return_date < self.travel_date:
            raise ValueError("Return date cannot be before the travel date.")
        return self


class UpdateClientGroupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=100)
    destination: str | None = Field(default=None, max_length=255)
    travel_date: date | None = None
    return_date: date | None = None
    package_name: str | None = Field(default=None, max_length=255)
    departure_cities: list[str] = Field(default_factory=list, max_length=50)
    base_city_enabled: bool = False
    nearest_international_airport_enabled: bool = False
    staff_code_enabled: bool = False
    meal_preference_enabled: bool = False
    require_selfie: bool = False
    allow_files_from_device: bool = True
    ask_nearest_domestic_airport: bool = False
    relation_with_qualifier_enabled: bool = False
    notes: str | None = Field(default=None, max_length=2000)
    whatsapp_broadcast_group_ids: list[uuid.UUID] | None = Field(
        default=None,
        max_length=50,
    )

    @field_validator("departure_cities", mode="before")
    @classmethod
    def normalize_departure_cities(cls, value: list[str] | None) -> list[str]:
        return _normalize_departure_cities(value)

    @field_validator("whatsapp_broadcast_group_ids", mode="before")
    @classmethod
    def normalize_whatsapp_broadcast_group_ids(
        cls,
        value: list[uuid.UUID] | None,
    ) -> list[uuid.UUID] | None:
        if value is None:
            return None
        return _normalize_broadcast_group_ids(value)

    @model_validator(mode="after")
    def validate_airport_configuration(self) -> UpdateClientGroupRequest:
        if self.nearest_international_airport_enabled and not self.departure_cities:
            raise ValueError("Add at least one nearest international airport when the option is enabled.")
        if not self.nearest_international_airport_enabled:
            self.departure_cities = []
        if self.travel_date and self.return_date and self.return_date < self.travel_date:
            raise ValueError("Return date cannot be before the travel date.")
        return self


class QualifierRelationOptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=1, max_length=40)
    label: str = Field(..., min_length=1, max_length=80)


class WhatsAppBroadcastSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    name: str
    recipient_count: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime


class ClientGroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    token: str
    agency_id: uuid.UUID
    status: str
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    closed_at: datetime | None = None
    destination: str | None = None
    travel_date: date | None = None
    return_date: date | None = None
    package_name: str | None = None
    departure_cities: list[str] = Field(default_factory=list)
    base_city_enabled: bool = False
    nearest_international_airport_enabled: bool = False
    staff_code_enabled: bool = False
    meal_preference_enabled: bool = False
    require_selfie: bool = False
    allow_files_from_device: bool = True
    ask_nearest_domestic_airport: bool = False
    relation_with_qualifier_enabled: bool = False
    qualifier_relation_options: list[QualifierRelationOptionResponse] = Field(
        default_factory=list
    )
    notes: str | None = None
    deleted_at: datetime | None = None
    deleted_passport_count: int = 0
    deletion_retained_records: bool = False

    model_config = {"from_attributes": True}


class ReplaceWhatsAppBroadcastLinksRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    whatsapp_broadcast_group_ids: list[uuid.UUID] = Field(
        ...,
        max_length=50,
    )

    @field_validator("whatsapp_broadcast_group_ids", mode="before")
    @classmethod
    def normalize_whatsapp_broadcast_group_ids(
        cls,
        value: list[uuid.UUID] | None,
    ) -> list[uuid.UUID]:
        return _normalize_broadcast_group_ids(value)


class ClientGroupWhatsAppLinksResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_group_id: uuid.UUID
    broadcasts: list[WhatsAppBroadcastSummaryResponse] = Field(
        default_factory=list
    )
    broadcast_count: int = Field(default=0, ge=0)
    recipient_count: int = Field(default=0, ge=0)
    can_manage: bool = False


class WhatsAppSubmissionMatchCountsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_recipients: int = Field(ge=0)
    submitted_count: int = Field(ge=0)
    not_submitted_count: int = Field(ge=0)
    multiple_submission_count: int = Field(ge=0)
    matched_submission_count: int = Field(ge=0)


class WhatsAppSubmissionMatchRowResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "submitted",
        "not_submitted",
        "multiple_submissions",
    ]
    match_basis: Literal["phone"] | None = None
    normalized_phone: str | None = None
    recipient_ids: list[uuid.UUID] = Field(default_factory=list)
    submission_ids: list[uuid.UUID] = Field(default_factory=list)
    broadcast_ids: list[uuid.UUID] = Field(default_factory=list)
    broadcast_names: list[str] = Field(default_factory=list)
    recipient_names: list[str] = Field(default_factory=list)
    submission_names: list[str] = Field(default_factory=list)
    updated_at: datetime


class ClientGroupWhatsAppMatchesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_group_id: uuid.UUID
    linked_broadcast_count: int = Field(ge=0)
    counts: WhatsAppSubmissionMatchCountsResponse
    matches: list[WhatsAppSubmissionMatchRowResponse] = Field(
        default_factory=list
    )
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_pages: int = Field(ge=0)


class CreateQualifierSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    is_self: bool
    relation_code: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def validate_exactly_one_path(self) -> CreateQualifierSelectionRequest:
        if self.is_self and self.relation_code:
            raise ValueError("Choose either Self or a relationship, not both.")
        if not self.is_self and not self.relation_code:
            raise ValueError("Choose the passenger's relationship with the qualifier.")
        return self


class QualifierSelectionStateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    is_self: bool
    relation_code: str | None = None
    relation_label: str
    selected_at: datetime
    expires_at: datetime
    status: Literal["active", "expired", "consumed"]
    submission_id: uuid.UUID | None = None


class CreateQualifierSelectionResponse(QualifierSelectionStateResponse):
    selection_token: str = Field(..., min_length=32, max_length=256)


class PublicFlowTelemetryRequest(BaseModel):
    """Fixed-enum, PII-free client quality/flow signal."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    event: Literal[
        "visa_photo_rejection",
        "passport_scanner_rejection",
        "public_flow",
    ]
    reason: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
