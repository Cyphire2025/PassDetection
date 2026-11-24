"""Pure client submission values rules; the submission use case owns effects."""

from __future__ import annotations

import re

from app.domain.exceptions.exceptions import ValidationError
from app.domain.value_objects.phone_number import normalize_phone_number


def _normalize_phone(value: str | None) -> str:
    return normalize_phone_number(value) or ""


def _normalize_departure_city(
    value: str | None, allowed_cities: list[str], *, enabled: bool, required: bool = True
) -> str | None:
    if not enabled:
        return None
    selected = " ".join(value.strip().split()) if value else ""
    if not selected and not required:
        return None
    cities = [" ".join(city.strip().split()) for city in allowed_cities if city and city.strip()]
    if not cities:
        raise ValidationError(
            "No nearest international airports are configured for this group.",
            field="departure_city",
        )
    if not selected:
        raise ValidationError("Select your nearest international airport.", field="departure_city")
    city_by_key = {city.casefold(): city for city in cities}
    matched = city_by_key.get(selected.casefold())
    if not matched:
        raise ValidationError(
            "Select a valid nearest international airport for this group.", field="departure_city"
        )
    return matched


def _normalize_configured_text(
    value: str | None,
    *,
    enabled: bool,
    field: str,
    label: str,
    max_length: int,
    required: bool = True,
) -> str | None:
    if not enabled:
        return None
    normalized = " ".join(value.strip().split())[:max_length] if value and value.strip() else ""
    if not normalized and not required:
        return None
    if not normalized:
        raise ValidationError(f"Enter your {label}.", field=field)
    return normalized


def _normalize_meal_preference(
    value: str | None, *, enabled: bool, required: bool = True
) -> str | None:
    if not enabled:
        return None
    normalized = " ".join(value.strip().split()).casefold() if value else ""
    if not normalized and not required:
        return None
    meals = {"veg": "Veg", "non veg": "Non Veg", "jain": "Jain"}
    matched = meals.get(normalized)
    if not matched:
        raise ValidationError("Select Veg, Non Veg, or Jain.", field="meal_preference")
    return matched


def _normalize_agent_employee_code(
    person_type: str | None,
    code: str | None,
    *,
    enabled: bool,
    required: bool = True,
    label: str = "Agent/Employee Code",
) -> tuple[str | None, str | None]:
    if not enabled:
        return None, None
    normalized_code = " ".join(code.strip().split()) if code else ""
    if not normalized_code:
        if not required:
            return None, None
        raise ValidationError(f"Enter your {label}.", field="agent_employee_code")
    if len(normalized_code) > 80:
        raise ValidationError(
            f"{label} must be 80 characters or fewer.", field="agent_employee_code"
        )
    # New forms collect one configurable code without a role dropdown.
    # Explicit legacy role payloads retain their original validation.
    if not person_type:
        return None, normalized_code
    normalized_type = " ".join(person_type.strip().split()).casefold() if person_type else ""
    if normalized_type not in {"agent", "employee"}:
        raise ValidationError(
            "Select Agent or Employee.",
            field="agent_employee_type",
        )
    if not re.fullmatch(r"\d{1,10}", normalized_code):
        raise ValidationError(
            "Enter an Agent/Employee code using up to 10 numbers.",
            field="agent_employee_code",
        )
    return normalized_type, normalized_code


def _content_type(suffix: str) -> str:
    suffix = suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    return "image/jpeg"
