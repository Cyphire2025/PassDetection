"""Editable group settings and public collection acquisition policy."""

from __future__ import annotations

from datetime import date

from app.domain.entities.client_group_state import ClientGroupState
from app.domain.exceptions.exceptions import ValidationError
from app.domain.value_objects.custom_questions import (
    normalize_custom_details,
    normalize_custom_questions,
)
from app.domain.value_objects.group_trip_settings import normalize_group_trip_settings
from app.domain.value_objects.import_group import import_group_settings
from app.domain.value_objects.upload_configuration import (
    configuration_for,
    normalize_upload_configuration,
    validate_capture_configuration,
)


class ClientGroupConfiguration(ClientGroupState):
    """Validate edits and enforce allowed public collection modes."""

    def update_configuration(
        self,
        *,
        name: str,
        destination: str | None,
        travel_date: date | None,
        return_date: date | None,
        timezone: str,
        package_name: str | None,
        departure_cities: list[str] | None,
        base_city_enabled: bool,
        nearest_international_airport_enabled: bool,
        staff_code_enabled: bool,
        agent_employee_code_enabled: bool,
        meal_preference_enabled: bool,
        require_selfie: bool,
        allow_files_from_device: bool,
        ask_nearest_domestic_airport: bool,
        relation_with_qualifier_enabled: bool,
        designation_enabled: bool,
        agency_dealership_name_enabled: bool,
        custom_questions: list[dict[str, object]] | None,
        custom_details: list[dict[str, object]] | None,
        notes: str | None,
        upload_configuration: dict[str, object] | None = None,
    ) -> None:
        """Apply editable group settings through one domain boundary."""

        normalized_name, normalized_timezone, normalized_departure_cities = (
            normalize_group_trip_settings(
                name=name,
                travel_date=travel_date,
                return_date=return_date,
                timezone=timezone,
                departure_cities=departure_cities,
                nearest_international_airport_enabled=nearest_international_airport_enabled,
                import_only=self.import_only,
            )
        )

        self.name = normalized_name
        self.destination = " ".join(destination.strip().split()) if destination else None
        self.travel_date = travel_date
        self.return_date = return_date
        self.timezone = normalized_timezone
        self.package_name = " ".join(package_name.strip().split()) if package_name else None
        self.departure_cities = normalized_departure_cities
        self.base_city_enabled = base_city_enabled
        self.nearest_international_airport_enabled = nearest_international_airport_enabled
        self.staff_code_enabled = staff_code_enabled
        self.agent_employee_code_enabled = agent_employee_code_enabled
        self.meal_preference_enabled = meal_preference_enabled
        self.require_selfie = require_selfie
        self.allow_files_from_device = allow_files_from_device
        self.ask_nearest_domestic_airport = ask_nearest_domestic_airport
        self.relation_with_qualifier_enabled = relation_with_qualifier_enabled
        self.designation_enabled = designation_enabled
        self.agency_dealership_name_enabled = agency_dealership_name_enabled
        if custom_questions is not None and not self.import_only:
            self.custom_questions = normalize_custom_questions(custom_questions)
        if custom_details is not None and not self.import_only:
            self.custom_details = normalize_custom_details(custom_details)
        if upload_configuration is not None and not self.import_only:
            self.upload_configuration = normalize_upload_configuration(upload_configuration)
        self.notes = notes.strip() if notes else None
        if self.import_only:
            self._disable_public_collection()
        validate_capture_configuration(self)

    def _disable_public_collection(self) -> None:
        for key, value in import_group_settings().items():
            setattr(self, key, value)

    def require_allowed_acquisition_mode(self, acquisition_mode: str) -> str:
        """Validate whether a public upload came through an enabled capture path."""

        normalized = acquisition_mode.strip().lower()
        if normalized not in {"camera", "file"}:
            raise ValidationError(
                "Choose a supported passport capture method.",
                field="acquisition_mode",
            )
        config = configuration_for(self)
        if not config.passport_enabled or (
            normalized == "camera" and not config.passport_live_scan
        ):
            raise ValidationError(
                "This passport collection method is disabled.", field="acquisition_mode"
            )
        if normalized == "file" and not self.allow_files_from_device:
            raise ValidationError(
                "This group requires live passport scanning. Files from the device are not allowed.",
                field="acquisition_mode",
            )
        return normalized
