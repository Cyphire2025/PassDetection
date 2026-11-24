"""Client group field definitions and dataclass defaults."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

from app.domain.entities.enums import GroupStatus
from app.domain.entities.factories import _utcnow
from app.domain.value_objects.custom_questions import (
    CustomDetailDefinition,
    CustomQuestionDefinition,
)
from app.domain.value_objects.trip_timezone import DEFAULT_TRIP_TIMEZONE


@dataclass
class ClientGroupState:
    """Fields shared by group construction, configuration and lifecycle operations."""

    id: uuid.UUID
    name: str
    token: str
    agency_id: uuid.UUID
    status: GroupStatus
    created_by_user_id: uuid.UUID | None

    company_id: uuid.UUID | None = None
    company_revision: int = 0
    company: dict[str, object] | None = None

    banner_url: str | None = None
    background_url: str | None = None
    import_only: bool = False

    created_at: datetime = field(default_factory=_utcnow)
    closed_at: datetime | None = None

    destination: str | None = None
    travel_date: date | None = None
    return_date: date | None = None
    timezone: str = DEFAULT_TRIP_TIMEZONE
    package_name: str | None = None
    departure_cities: list[str] = field(default_factory=list)

    base_city_enabled: bool = False
    nearest_international_airport_enabled: bool = False
    staff_code_enabled: bool = False
    agent_employee_code_enabled: bool = False
    meal_preference_enabled: bool = False
    require_selfie: bool = False
    upload_configuration: dict[str, object] | None = None
    allow_files_from_device: bool = True
    ask_nearest_domestic_airport: bool = False
    relation_with_qualifier_enabled: bool = False
    designation_enabled: bool = False
    agency_dealership_name_enabled: bool = False

    custom_questions: list[CustomQuestionDefinition] = field(default_factory=list)
    custom_details: list[CustomDetailDefinition] = field(default_factory=list)

    notes: str | None = None

    deleted_at: datetime | None = None
    deleted_passport_count: int = 0
    deletion_retained_records: bool = False
    passport_purge_at: datetime | None = None
    passport_retention_days_applied: int | None = None

    # Legacy persistence only; legal holds no longer affect deletion or retention.
    passport_legal_hold: bool = False
    passport_legal_hold_reason: str | None = None
    passport_legal_hold_set_at: datetime | None = None
    passport_legal_hold_set_by_user_id: uuid.UUID | None = None
