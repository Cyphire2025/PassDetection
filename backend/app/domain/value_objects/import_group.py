"""Canonical collection settings for groups populated by staff Excel imports."""

from typing import Any

from app.domain.value_objects.upload_configuration import UploadConfiguration


def import_group_settings() -> dict[str, Any]:
    """Return fresh settings, discarding hidden public-form configuration."""
    return {
        "package_name": None,
        "departure_cities": [],
        "base_city_enabled": False,
        "nearest_international_airport_enabled": False,
        "staff_code_enabled": False,
        "agent_employee_code_enabled": False,
        "meal_preference_enabled": False,
        "require_selfie": False,
        "allow_files_from_device": False,
        "ask_nearest_domestic_airport": False,
        "relation_with_qualifier_enabled": False,
        "designation_enabled": False,
        "agency_dealership_name_enabled": False,
        "custom_questions": [],
        "custom_details": [],
        "notes": None,
        "upload_configuration": UploadConfiguration(
            passport_enabled=False,
            passport_required=False,
            passport_live_scan=False,
            passport_upload_pages=[],
            visa_photo_required=False,
            visa_photo_live_capture=False,
            visa_photo_upload=False,
            qualifier_relation_list_enabled=False,
        ).model_dump(mode="json"),
    }
