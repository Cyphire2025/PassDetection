"""Focused passport summary API contracts."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.domain.value_objects.trip_timezone import DEFAULT_TRIP_TIMEZONE


class PassportGroupSummaryResponse(BaseModel):
    company_name: str | None = None
    company_logo_url: str | None = None
    banner_url: str | None = None
    background_url: str | None = None
    group_id: uuid.UUID
    group_name: str
    group_status: str
    total_passports: int
    pending_review_count: int
    confirmed_count: int
    failed_count: int
    latest_submission_at: datetime
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
    import_only: bool = False
    require_selfie: bool = False
    custom_questions: list[dict[str, object]] = Field(default_factory=list)
    custom_details: list[dict[str, object]] = Field(default_factory=list)
    upload_configuration: dict[str, object] | None = None
    allow_files_from_device: bool = True
    ask_nearest_domestic_airport: bool = False
    relation_with_qualifier_enabled: bool = False
    designation_enabled: bool = False
    agency_dealership_name_enabled: bool = False
    notes: str | None = None

    model_config = {"from_attributes": True}
