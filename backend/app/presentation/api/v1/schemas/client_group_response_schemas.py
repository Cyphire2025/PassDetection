"""Authenticated client group response fields."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.domain.value_objects.trip_timezone import DEFAULT_TRIP_TIMEZONE
from app.domain.value_objects.upload_configuration import UploadConfiguration
from app.presentation.api.v1.schemas.client_group_collection_schemas import (
    CustomDetailResponse,
    CustomQuestionResponse,
)
from app.presentation.api.v1.schemas.client_group_qualifier_schemas import (
    QualifierRelationOptionResponse,
)


class ClientGroupResponse(BaseModel):
    banner_url: str | None = None
    background_url: str | None = None
    company_id: uuid.UUID | None = None
    company_revision: int = 0
    company: dict[str, object] | None = None
    id: uuid.UUID
    name: str
    token: str
    agency_id: uuid.UUID
    status: str
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    import_only: bool = False
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

    model_config = {"from_attributes": True}
