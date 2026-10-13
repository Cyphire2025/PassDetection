"""Fresh trip details reuse the existing collection validators unchanged."""

from __future__ import annotations

from typing import cast

from pydantic import EmailStr, TypeAdapter
from pydantic import ValidationError as PydanticValidationError
from typing_extensions import TypedDict

from app.application.platform_policies import PlatformPolicies
from app.application.use_cases.passports.client_submit_passport_use_case import (
    ClientSubmitPassportUseCase,
)
from app.domain.exceptions.exceptions import ValidationError
from app.domain.value_objects.upload_configuration import RequiredField, configuration_for
from app.infrastructure.database.models import ClientGroupModel


class CurrentDetailField(TypedDict):
    key: str
    label: str
    required: bool
    options: list[str]
    type: str


def detail_fields(group: ClientGroupModel, policies: PlatformPolicies) -> list[CurrentDetailField]:
    config = configuration_for(group)
    definitions: list[tuple[str, str, bool, list[str]]] = [
        ("base_city", "Base city", group.base_city_enabled, []),
        ("nearest_domestic_airport", "Nearest domestic airport", group.ask_nearest_domestic_airport, []),
        ("staff_code", "Staff code", group.staff_code_enabled, []),
        ("agent_employee_code", config.agent_employee_code_label, group.agent_employee_code_enabled, []),
        ("designation", "Designation", group.designation_enabled, []),
        ("agency_dealership_name", config.agency_dealership_name_label, group.agency_dealership_name_enabled, []),
        ("meal_preference", "Meal preference", group.meal_preference_enabled, ["Veg", "Non Veg", "Jain"]),
        ("departure_city", "Nearest international airport", group.nearest_international_airport_enabled
            or (group.upload_configuration is None and bool(group.departure_cities)), group.departure_cities),
    ]
    result = [CurrentDetailField(key=key, label=label, required=config.required(cast(RequiredField, key)),
        options=options, type="select" if options else "text") for key, label, enabled, options in definitions if enabled]
    result.append(CurrentDetailField(key="client_email", label="Email address", required=policies.require_client_email, options=[], type="email"))
    return result


def normalize_current_details(
    group: ClientGroupModel, policies: PlatformPolicies, answers: dict[str, str],
) -> dict[str, str]:
    definitions = detail_fields(group, policies)
    if set(answers) - {field["key"] for field in definitions}:
        raise ValidationError("Some details no longer match this group's requirements.", field="current_details")
    if any(len(value) > 500 for value in answers.values()):
        raise ValidationError("A current trip detail is too long.", field="current_details")
    validator = ClientSubmitPassportUseCase
    normalized: dict[str, str] = {}
    for field in definitions:
        key, value, required = field["key"], answers.get(field["key"], ""), field["required"]
        result: str | None
        if key == "client_email":
            if required and not value.strip():
                raise ValidationError("Enter a valid email address.", field="client_email")
            try:
                result = str(TypeAdapter(EmailStr).validate_python(value)).lower() if value.strip() else None
            except PydanticValidationError as exc:
                raise ValidationError("Enter a valid email address.", field="client_email") from exc
        elif key == "departure_city":
            result = validator._normalize_departure_city(value, group.departure_cities, enabled=True, required=required)
        elif key == "meal_preference":
            result = validator._normalize_meal_preference(value, enabled=True, required=required)
        elif key == "agent_employee_code":
            _, result = validator._normalize_agent_employee_code(None, value, enabled=True, required=required, label=field["label"])
        else:
            result = validator._normalize_configured_text(value, enabled=True, field=key, label=field["label"],
                max_length={"staff_code": 80, "designation": 160, "agency_dealership_name": 200}.get(key, 120), required=required)
        if result:
            normalized[key] = result
    return normalized
