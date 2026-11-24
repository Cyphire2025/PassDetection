"""Group creation and editable-settings request schemas."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.value_objects.import_group import import_group_settings
from app.domain.value_objects.trip_timezone import DEFAULT_TRIP_TIMEZONE, normalize_trip_timezone
from app.domain.value_objects.upload_configuration import UploadConfiguration
from app.presentation.api.v1.schemas.client_group_collection_schemas import (
    CustomDetailRequest,
    CustomQuestionRequest,
)
from app.presentation.api.v1.schemas.client_group_request_validation import (
    _normalize_broadcast_group_ids,
    _normalize_departure_cities,
    _normalize_matching_fields_by_broadcast,
)


class CreateClientGroupRequest(BaseModel):
    company_id: uuid.UUID
    agency_id: uuid.UUID | None = None
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    import_only: bool = Field(default=False, strict=True)
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

    @model_validator(mode="before")
    @classmethod
    def discard_import_collection_settings(cls, value: object) -> object:
        if isinstance(value, dict) and value.get("import_only") is True:
            return {
                **value,
                **import_group_settings(),
                "whatsapp_broadcast_group_ids": [],
                "matching_fields_by_broadcast": None,
            }
        return value

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
    company_id: uuid.UUID | None = None
    agency_id: uuid.UUID | None = None
    company_revision: int | None = Field(default=None, ge=0)
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
