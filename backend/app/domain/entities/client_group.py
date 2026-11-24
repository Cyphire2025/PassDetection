"""Public client group entity and validated construction."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from app.domain.entities.client_group_configuration import ClientGroupConfiguration
from app.domain.entities.client_group_lifecycle import ClientGroupLifecycle
from app.domain.entities.enums import GroupStatus
from app.domain.entities.factories import _new_uuid, _utcnow
from app.domain.value_objects.custom_questions import (
    normalize_custom_details,
    normalize_custom_questions,
)
from app.domain.value_objects.group_trip_settings import normalize_group_trip_settings
from app.domain.value_objects.trip_timezone import DEFAULT_TRIP_TIMEZONE
from app.domain.value_objects.upload_configuration import (
    normalize_upload_configuration,
    validate_capture_configuration,
)


@dataclass
class ClientGroup(ClientGroupConfiguration, ClientGroupLifecycle):
    """
    A group of clients (e.g., a tour group) managed by an agency.

    Business rules:
      - Has a common upload link token shared via WhatsApp/email.
      - Can accept multiple passport submissions.
      - Can be closed or archived.
    """

    @classmethod
    def create(
        cls,
        name: str,
        token: str,
        agency_id: uuid.UUID,
        created_by_user_id: uuid.UUID,
        destination: str | None = None,
        travel_date: date | None = None,
        return_date: date | None = None,
        timezone: str = DEFAULT_TRIP_TIMEZONE,
        package_name: str | None = None,
        departure_cities: list[str] | None = None,
        base_city_enabled: bool = False,
        nearest_international_airport_enabled: bool = False,
        staff_code_enabled: bool = False,
        agent_employee_code_enabled: bool = False,
        meal_preference_enabled: bool = False,
        require_selfie: bool = False,
        upload_configuration: dict[str, object] | None = None,
        allow_files_from_device: bool = True,
        ask_nearest_domestic_airport: bool = False,
        relation_with_qualifier_enabled: bool = False,
        designation_enabled: bool = False,
        agency_dealership_name_enabled: bool = False,
        custom_questions: list[dict[str, object]] | None = None,
        custom_details: list[dict[str, object]] | None = None,
        notes: str | None = None,
        initial_status: GroupStatus = GroupStatus.ACTIVE,
        passport_retention_days: int | None = None,
        import_only: bool = False,
    ) -> ClientGroup:
        normalized_name, normalized_timezone, normalized_departure_cities = (
            normalize_group_trip_settings(
                name=name,
                travel_date=travel_date,
                return_date=return_date,
                timezone=timezone,
                departure_cities=departure_cities,
                nearest_international_airport_enabled=nearest_international_airport_enabled,
                import_only=import_only,
            )
        )
        lifecycle_at = _utcnow()
        group = cls(
            id=_new_uuid(),
            name=normalized_name,
            token=token,
            agency_id=agency_id,
            status=initial_status,
            import_only=import_only,
            created_by_user_id=created_by_user_id,
            created_at=lifecycle_at,
            closed_at=lifecycle_at if initial_status == GroupStatus.CLOSED else None,
            destination=destination.strip() if destination else None,
            travel_date=travel_date,
            return_date=return_date,
            timezone=normalized_timezone,
            package_name=package_name.strip() if package_name else None,
            departure_cities=normalized_departure_cities,
            base_city_enabled=base_city_enabled,
            nearest_international_airport_enabled=nearest_international_airport_enabled,
            staff_code_enabled=staff_code_enabled,
            agent_employee_code_enabled=agent_employee_code_enabled,
            meal_preference_enabled=meal_preference_enabled,
            require_selfie=require_selfie,
            upload_configuration=normalize_upload_configuration(upload_configuration)
            if not import_only
            else None,
            allow_files_from_device=allow_files_from_device,
            ask_nearest_domestic_airport=ask_nearest_domestic_airport,
            relation_with_qualifier_enabled=relation_with_qualifier_enabled,
            designation_enabled=designation_enabled,
            agency_dealership_name_enabled=agency_dealership_name_enabled,
            custom_questions=normalize_custom_questions(custom_questions)
            if not import_only
            else [],
            custom_details=normalize_custom_details(custom_details) if not import_only else [],
            notes=notes.strip() if notes else None,
        )
        if import_only:
            group._disable_public_collection()
        validate_capture_configuration(group)
        if initial_status == GroupStatus.CLOSED and passport_retention_days is not None:
            group.schedule_passport_purge(passport_retention_days)
        return group
