"""
Upload Link Presentation Schemas
================================
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.exceptions.exceptions import ValidationError as DomainValidationError
from app.domain.value_objects.qualifier_relations import normalize_qualifier_choice
from app.domain.value_objects.trip_timezone import (
    DEFAULT_TRIP_TIMEZONE,
    normalize_trip_timezone,
)
from app.domain.value_objects.upload_configuration import UploadConfiguration
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppMatchingFieldOption,
)


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


def _normalize_matching_fields_by_broadcast(
    value: object,
) -> dict[uuid.UUID, list[str]] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Matching fields must be keyed by WhatsApp broadcast id")
    if len(value) > 50:
        raise ValueError("Configure matching fields for at most 50 broadcasts")
    normalized: dict[uuid.UUID, list[str]] = {}
    for raw_broadcast_id, raw_fields in value.items():
        try:
            broadcast_id = uuid.UUID(str(raw_broadcast_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("Matching fields require valid WhatsApp broadcast ids") from exc
        if not isinstance(raw_fields, list):
            raise ValueError("Each WhatsApp broadcast requires a list of matching fields")
        fields: list[str] = []
        for raw_field in raw_fields:
            if not isinstance(raw_field, str):
                raise ValueError("Matching field keys must be text")
            key = re.sub(
                r"_+",
                "_",
                re.sub(r"[^a-z0-9]+", "_", raw_field.strip().casefold()),
            ).strip("_")
            if len(key) > 64:
                raise ValueError("Matching field keys must be 64 characters or fewer")
            if key and key not in fields:
                fields.append(key)
        if not fields:
            raise ValueError("Select at least one matching field for each broadcast")
        if len(fields) > 32:
            raise ValueError("Select at most 32 matching fields for each broadcast")
        normalized[broadcast_id] = fields
    return normalized


class CustomQuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: uuid.UUID
    label: str = Field(..., min_length=1, max_length=100)
    options: list[str] = Field(..., min_length=2, max_length=50)
    enabled: bool = True
    required: bool = True

    @field_validator("options", mode="before")
    @classmethod
    def normalize_options(cls, values: list[str] | None) -> list[str]:
        seen: set[str] = set()
        options: list[str] = []
        for value in values or []:
            option = " ".join(str(value).strip().split())
            if not option:
                continue
            if len(option) > 120:
                raise ValueError("Custom options must be 120 characters or fewer.")
            key = option.casefold()
            if key in seen:
                continue
            seen.add(key)
            options.append(option)
        return options


class CustomQuestionResponse(CustomQuestionRequest):
    pass


class CustomDetailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: uuid.UUID
    label: str = Field(..., min_length=1, max_length=100)
    enabled: bool = True
    required: bool = True


class CustomDetailResponse(CustomDetailRequest):
    pass


class CreateClientGroupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=100)
    destination: str = Field(..., min_length=1, max_length=255)
    travel_date: date
    return_date: date
    timezone: str = Field(default=DEFAULT_TRIP_TIMEZONE, min_length=1, max_length=64)
    package_name: str | None = Field(default=None, max_length=255)
    departure_cities: list[str] = Field(default_factory=list, max_length=50)
    base_city_enabled: bool = False
    nearest_international_airport_enabled: bool = False
    staff_code_enabled: bool = False
    agent_employee_code_enabled: bool = False
    meal_preference_enabled: bool = False
    require_selfie: bool = False
    upload_configuration: UploadConfiguration | None = None
    allow_files_from_device: bool = True
    ask_nearest_domestic_airport: bool = False
    relation_with_qualifier_enabled: bool = False
    designation_enabled: bool = False
    agency_dealership_name_enabled: bool = False
    custom_questions: list[CustomQuestionRequest] = Field(
        default_factory=list,
        max_length=20,
    )
    custom_details: list[CustomDetailRequest] = Field(
        default_factory=list,
        max_length=20,
    )
    notes: str | None = Field(default=None, max_length=2000)
    whatsapp_broadcast_group_ids: list[uuid.UUID] = Field(
        default_factory=list,
        max_length=50,
    )
    matching_fields_by_broadcast: dict[uuid.UUID, list[str]] | None = None

    @field_validator("departure_cities", mode="before")
    @classmethod
    def normalize_departure_cities(cls, value: list[str] | None) -> list[str]:
        return _normalize_departure_cities(value)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return normalize_trip_timezone(value)

    @field_validator("whatsapp_broadcast_group_ids", mode="before")
    @classmethod
    def normalize_whatsapp_broadcast_group_ids(
        cls,
        value: list[uuid.UUID] | None,
    ) -> list[uuid.UUID]:
        return _normalize_broadcast_group_ids(value)

    @field_validator("matching_fields_by_broadcast", mode="before")
    @classmethod
    def normalize_matching_fields(
        cls,
        value: object,
    ) -> dict[uuid.UUID, list[str]] | None:
        return _normalize_matching_fields_by_broadcast(value)

    @model_validator(mode="after")
    def validate_airport_configuration(self) -> CreateClientGroupRequest:
        self._validate_qualifier_methods()
        if self.matching_fields_by_broadcast is not None and not set(
            self.matching_fields_by_broadcast
        ).issubset(self.whatsapp_broadcast_group_ids):
            raise ValueError("Matching fields must belong to a selected WhatsApp broadcast")
        if self.nearest_international_airport_enabled and not self.departure_cities:
            raise ValueError(
                "Add at least one nearest international airport when the option is enabled."
            )
        if not self.nearest_international_airport_enabled:
            self.departure_cities = []
        if self.return_date < self.travel_date:
            raise ValueError("Return date cannot be before the Travel/Departure date.")
        return self

    def _validate_qualifier_methods(self) -> None:
        config = self.upload_configuration or UploadConfiguration()
        if self.relation_with_qualifier_enabled and not (
            config.qualifier_relation_list_enabled or config.qualifier_relation_other_enabled
        ):
            raise ValueError("Enable at least one relationship entry option.")


class UpdateClientGroupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=100)
    destination: str | None = Field(default=None, max_length=255)
    travel_date: date | None = None
    return_date: date | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    package_name: str | None = Field(default=None, max_length=255)
    departure_cities: list[str] = Field(default_factory=list, max_length=50)
    base_city_enabled: bool = False
    nearest_international_airport_enabled: bool = False
    staff_code_enabled: bool = False
    agent_employee_code_enabled: bool = False
    meal_preference_enabled: bool = False
    require_selfie: bool = False
    upload_configuration: UploadConfiguration | None = None
    allow_files_from_device: bool = True
    ask_nearest_domestic_airport: bool = False
    relation_with_qualifier_enabled: bool = False
    designation_enabled: bool = False
    agency_dealership_name_enabled: bool = False
    custom_questions: list[CustomQuestionRequest] | None = Field(
        default=None,
        max_length=20,
    )
    custom_details: list[CustomDetailRequest] | None = Field(
        default=None,
        max_length=20,
    )
    notes: str | None = Field(default=None, max_length=2000)
    whatsapp_broadcast_group_ids: list[uuid.UUID] | None = Field(
        default=None,
        max_length=50,
    )
    matching_fields_by_broadcast: dict[uuid.UUID, list[str]] | None = None

    @field_validator("departure_cities", mode="before")
    @classmethod
    def normalize_departure_cities(cls, value: list[str] | None) -> list[str]:
        return _normalize_departure_cities(value)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        return normalize_trip_timezone(value) if value is not None else None

    @field_validator("whatsapp_broadcast_group_ids", mode="before")
    @classmethod
    def normalize_whatsapp_broadcast_group_ids(
        cls,
        value: list[uuid.UUID] | None,
    ) -> list[uuid.UUID] | None:
        if value is None:
            return None
        return _normalize_broadcast_group_ids(value)

    @field_validator("matching_fields_by_broadcast", mode="before")
    @classmethod
    def normalize_matching_fields(
        cls,
        value: object,
    ) -> dict[uuid.UUID, list[str]] | None:
        return _normalize_matching_fields_by_broadcast(value)

    @model_validator(mode="after")
    def validate_airport_configuration(self) -> UpdateClientGroupRequest:
        if self.matching_fields_by_broadcast is not None:
            if self.whatsapp_broadcast_group_ids is None:
                raise ValueError(
                    "Include selected WhatsApp broadcasts when updating matching fields"
                )
            if not set(self.matching_fields_by_broadcast).issubset(
                self.whatsapp_broadcast_group_ids
            ):
                raise ValueError("Matching fields must belong to a selected WhatsApp broadcast")
        config = self.upload_configuration or UploadConfiguration()
        if self.relation_with_qualifier_enabled and not (
            config.qualifier_relation_list_enabled or config.qualifier_relation_other_enabled
        ):
            raise ValueError("Enable at least one relationship entry option.")
        if "timezone" in self.model_fields_set and self.timezone is None:
            raise ValueError("Trip timezone cannot be null.")
        if self.nearest_international_airport_enabled and not self.departure_cities:
            raise ValueError(
                "Add at least one nearest international airport when the option is enabled."
            )
        if not self.nearest_international_airport_enabled:
            self.departure_cities = []
        if self.travel_date and self.return_date and self.return_date < self.travel_date:
            raise ValueError("Return date cannot be before the Travel/Departure date.")
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
    available_matching_fields: list[WhatsAppMatchingFieldOption] = Field(default_factory=list)
    matching_field_keys: list[str] | None = None
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
    timezone: str = DEFAULT_TRIP_TIMEZONE
    package_name: str | None = None
    departure_cities: list[str] = Field(default_factory=list)
    base_city_enabled: bool = False
    nearest_international_airport_enabled: bool = False
    staff_code_enabled: bool = False
    agent_employee_code_enabled: bool = False
    meal_preference_enabled: bool = False
    require_selfie: bool = False
    upload_configuration: UploadConfiguration | None = None
    allow_files_from_device: bool = True
    ask_nearest_domestic_airport: bool = False
    relation_with_qualifier_enabled: bool = False
    designation_enabled: bool = False
    agency_dealership_name_enabled: bool = False
    custom_questions: list[CustomQuestionResponse] = Field(default_factory=list)
    custom_details: list[CustomDetailResponse] = Field(default_factory=list)
    qualifier_relation_options: list[QualifierRelationOptionResponse] = Field(default_factory=list)
    notes: str | None = None
    deleted_at: datetime | None = None
    deleted_passport_count: int = 0
    deletion_retained_records: bool = False
    passport_purge_at: datetime | None = None
    passport_legal_hold: bool = False

    model_config = {"from_attributes": True}


class ReplaceWhatsAppBroadcastLinksRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    whatsapp_broadcast_group_ids: list[uuid.UUID] = Field(
        ...,
        max_length=50,
    )
    matching_fields_by_broadcast: dict[uuid.UUID, list[str]] | None = None

    @field_validator("whatsapp_broadcast_group_ids", mode="before")
    @classmethod
    def normalize_whatsapp_broadcast_group_ids(
        cls,
        value: list[uuid.UUID] | None,
    ) -> list[uuid.UUID]:
        return _normalize_broadcast_group_ids(value)

    @field_validator("matching_fields_by_broadcast", mode="before")
    @classmethod
    def normalize_matching_fields(
        cls,
        value: object,
    ) -> dict[uuid.UUID, list[str]] | None:
        return _normalize_matching_fields_by_broadcast(value)

    @model_validator(mode="after")
    def validate_matching_fields(self) -> ReplaceWhatsAppBroadcastLinksRequest:
        if self.matching_fields_by_broadcast is not None and not set(
            self.matching_fields_by_broadcast
        ).issubset(self.whatsapp_broadcast_group_ids):
            raise ValueError("Matching fields must belong to a selected WhatsApp broadcast")
        return self


class ClientGroupWhatsAppLinksResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_group_id: uuid.UUID
    broadcasts: list[WhatsAppBroadcastSummaryResponse] = Field(default_factory=list)
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
    needs_review_count: int = Field(default=0, ge=0)
    needs_review_submission_count: int = Field(default=0, ge=0)
    unmatched_submission_count: int = Field(default=0, ge=0)
    replacement_count: int = Field(default=0, ge=0)
    rejected_upload_count: int = Field(default=0, ge=0)


class WhatsAppSubmissionMatchEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_id: uuid.UUID
    kind: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    recipient_value: str
    submission_value: str
    weight: int = Field(ge=0)


class WhatsAppRecipientImportedFieldsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient_id: uuid.UUID
    fields: dict[str, str] = Field(default_factory=dict)


class WhatsAppSubmissionDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_id: uuid.UUID
    name: str
    phone: str | None = None
    email: str | None = None
    fields: dict[str, object] = Field(default_factory=dict)


class WhatsAppSubmissionMatchRowResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "submitted",
        "not_submitted",
        "multiple_submissions",
        "needs_review",
        "unmatched_submission",
        "replacement",
        "rejected_upload",
    ]
    match_basis: str | None = None
    normalized_phone: str | None = None
    recipient_ids: list[uuid.UUID] = Field(default_factory=list)
    submission_ids: list[uuid.UUID] = Field(default_factory=list)
    broadcast_ids: list[uuid.UUID] = Field(default_factory=list)
    broadcast_names: list[str] = Field(default_factory=list)
    recipient_names: list[str] = Field(default_factory=list)
    submission_names: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "none"] = "none"
    match_evidence: list[WhatsAppSubmissionMatchEvidenceResponse] = Field(default_factory=list)
    candidate_submission_ids: list[uuid.UUID] = Field(default_factory=list)
    duplicate_submission_ids: list[uuid.UUID] = Field(default_factory=list)
    recipient_fields: list[WhatsAppRecipientImportedFieldsResponse] = Field(default_factory=list)
    submission_details: list[WhatsAppSubmissionDetailResponse] = Field(default_factory=list)
    resolution_id: uuid.UUID | None = None
    updated_at: datetime


class ClientGroupWhatsAppMatchesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_group_id: uuid.UUID
    selected_broadcast_id: uuid.UUID | None = None
    linked_broadcast_count: int = Field(ge=0)
    counts: WhatsAppSubmissionMatchCountsResponse
    matches: list[WhatsAppSubmissionMatchRowResponse] = Field(default_factory=list)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_pages: int = Field(ge=0)


class ReplacementCandidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient_id: uuid.UUID
    recipient_ids: list[uuid.UUID] = Field(min_length=1)
    name: str | None = None
    phone: str
    broadcast_ids: list[uuid.UUID] = Field(default_factory=list)
    broadcast_names: list[str] = Field(default_factory=list)
    imported_fields: dict[str, str] = Field(default_factory=dict)


class ReplacementCandidateListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_group_id: uuid.UUID
    items: list[ReplacementCandidateResponse] = Field(default_factory=list)


class ResolveUnidentifiedReplacementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient_id: uuid.UUID
    request_id: uuid.UUID


class RejectUnidentifiedUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: uuid.UUID


class PassportRosterResolutionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    client_group_id: uuid.UUID
    submission_id: uuid.UUID
    resolution_type: Literal["replacement", "rejected"]
    status: Literal["active", "restored"]
    broadcast_recipient_id: uuid.UUID | None = None
    suppressed_recipient_ids: list[uuid.UUID] = Field(default_factory=list)
    excluded_submission_ids: list[uuid.UUID] = Field(default_factory=list)
    created_at: datetime
    restored_at: datetime | None = None


class CreateQualifierSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    is_self: bool
    relation_code: str | None = Field(default=None, max_length=40)
    other_relation: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("other_relation", mode="before")
    @classmethod
    def normalize_other_relation_input(cls, value: object) -> object:
        return unicodedata.normalize("NFC", value).strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_exactly_one_path(self) -> CreateQualifierSelectionRequest:
        if self.is_self and (self.relation_code or self.other_relation is not None):
            raise ValueError("Choose either Self or a relationship, not both.")
        if not self.is_self and not self.relation_code:
            raise ValueError("Choose the passenger's relationship with the qualifier.")
        if (self.relation_code or "").casefold() != "other":
            if self.other_relation is not None:
                raise ValueError("Choose Other to enter a relationship.")
            return self
        try:
            _is_self, code, label = normalize_qualifier_choice(
                is_self=self.is_self,
                relation_code=self.relation_code,
                other_relation=self.other_relation,
            )
        except DomainValidationError as exc:
            raise ValueError(str(exc)) from exc
        self.relation_code = code
        self.other_relation = label if code == "other" else None
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
