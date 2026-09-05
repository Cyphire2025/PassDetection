"""
Upload Link Application DTOs
=============================
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

from app.domain.entities.entities import ClientGroup
from app.domain.value_objects.custom_questions import (
    CustomDetailDefinition,
    CustomQuestionDefinition,
)
from app.domain.value_objects.qualifier_relations import qualifier_relation_options
from app.domain.value_objects.trip_timezone import DEFAULT_TRIP_TIMEZONE


@dataclass(frozen=True)
class CreateClientGroupInputDTO:
    name: str
    destination: str | None = None
    travel_date: date | None = None
    return_date: date | None = None
    timezone: str = DEFAULT_TRIP_TIMEZONE
    package_name: str | None = None
    departure_cities: list[str] | None = None
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
    custom_questions: list[dict[str, object]] | None = None
    custom_details: list[dict[str, object]] | None = None
    notes: str | None = None


@dataclass(frozen=True)
class UpdateClientGroupInputDTO:
    name: str
    destination: str | None = None
    travel_date: date | None = None
    return_date: date | None = None
    timezone: str | None = None
    package_name: str | None = None
    departure_cities: list[str] | None = None
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
    custom_questions: list[dict[str, object]] | None = None
    custom_details: list[dict[str, object]] | None = None
    notes: str | None = None


@dataclass(frozen=True)
class ClientGroupOutputDTO:
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
    departure_cities: list[str] | None = None
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
    qualifier_relation_options: list[dict[str, str]] = field(default_factory=list)
    notes: str | None = None
    deleted_at: datetime | None = None
    deleted_passport_count: int = 0
    deletion_retained_records: bool = False
    passport_purge_at: datetime | None = None
    passport_legal_hold: bool = False


def client_group_output_from_entity(link: ClientGroup) -> ClientGroupOutputDTO:
    return ClientGroupOutputDTO(
        id=link.id,
        name=link.name,
        token=link.token,
        agency_id=link.agency_id,
        status=link.status.value,
        created_by_user_id=link.created_by_user_id,
        created_at=link.created_at,
        closed_at=link.closed_at,
        destination=link.destination,
        travel_date=link.travel_date,
        return_date=link.return_date,
        timezone=link.timezone,
        package_name=link.package_name,
        departure_cities=link.departure_cities,
        base_city_enabled=link.base_city_enabled,
        nearest_international_airport_enabled=link.nearest_international_airport_enabled,
        staff_code_enabled=link.staff_code_enabled,
        agent_employee_code_enabled=link.agent_employee_code_enabled,
        meal_preference_enabled=link.meal_preference_enabled,
        require_selfie=link.require_selfie,
        upload_configuration=link.upload_configuration,
        allow_files_from_device=link.allow_files_from_device,
        ask_nearest_domestic_airport=link.ask_nearest_domestic_airport,
        relation_with_qualifier_enabled=link.relation_with_qualifier_enabled,
        designation_enabled=link.designation_enabled,
        agency_dealership_name_enabled=link.agency_dealership_name_enabled,
        custom_questions=list(link.custom_questions or []),
        custom_details=list(link.custom_details or []),
        qualifier_relation_options=qualifier_relation_options(),
        notes=link.notes,
        deleted_at=link.deleted_at,
        deleted_passport_count=link.deleted_passport_count,
        deletion_retained_records=link.deletion_retained_records,
        passport_purge_at=link.passport_purge_at,
        passport_legal_hold=link.passport_legal_hold,
    )
