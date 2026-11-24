"""Passport cell/date/contact display conversion; source values remain unchanged."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pycountry

from app.infrastructure.export.passport_excel_columns import _ExportColumn
from app.infrastructure.export.passport_excel_phone_columns import VERIFIED_WHATSAPP_HEADER
from app.infrastructure.export.workbook_values import excel_date_value as _excel_date_value
from app.infrastructure.export.workbook_values import safe_xlsx_value as _safe_xlsx_value


def _whatsapp_phone_value(value: Any) -> Any:
    """Remove only an explicit leading India code from WhatsApp export values."""

    if not isinstance(value, str):
        return value
    if value.startswith("'+91"):
        return value[4:].lstrip(" -")
    if value.startswith("+91"):
        return value[3:].lstrip(" -")
    return value


def _uppercase(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).upper()


def _export_cell_value(column: _ExportColumn, value: Any) -> Any:
    if column.number_format:
        value = _excel_date_value(value)
    if column.header == VERIFIED_WHATSAPP_HEADER:
        value = _whatsapp_phone_value(value)
    return _safe_xlsx_value(value)


def _gender_display_value(value: Any) -> str | None:
    """Normalize recognized passport sex values without mutating stored data."""

    if value in (None, ""):
        return None
    normalized = " ".join(str(value).strip().split()).casefold()
    if normalized in {"m", "male"}:
        return "Male"
    if normalized in {"f", "female"}:
        return "Female"
    # Do not invent a binary value for an unsupported or non-binary document
    # marker. Returning the trimmed source is safer than silently misgendering
    # the traveller while still normalizing every supported legacy value.
    return " ".join(str(value).strip().split()) or None


def _country_display_name(value: Any) -> str | None:
    if value in (None, ""):
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    try:
        country = pycountry.countries.lookup(normalized)
    except LookupError:
        return normalized
    return str(getattr(country, "common_name", country.name))


def _nationality_display_value(value: Any) -> str | None:
    """Format nationality for export without changing its stored source value."""

    if value in (None, ""):
        return None
    normalized = " ".join(str(value).strip().split())
    if not normalized:
        return None
    if normalized.casefold() in {"in", "ind", "india", "indian"}:
        return "Indian"
    return _country_display_name(normalized)


def _date_value(value: Any) -> date | None:
    converted = _excel_date_value(value)
    if isinstance(converted, datetime):
        return converted.date()
    return converted if isinstance(converted, date) else None


def passport_age_group(date_of_birth: Any, departure_date: Any) -> str | None:
    """Classify a traveller by completed age on the group's departure date."""

    birth = _date_value(date_of_birth)
    departure = _date_value(departure_date)
    if not birth or not departure or birth > departure:
        return None
    age = (
        departure.year - birth.year - ((departure.month, departure.day) < (birth.month, birth.day))
    )
    if age < 2:
        return "Infant"
    if age < 12:
        return "Child"
    return "Adult"


# These same function objects remain available from the original import path.
for _function in (
    _whatsapp_phone_value,
    _uppercase,
    _export_cell_value,
    _gender_display_value,
    _country_display_name,
    _nationality_display_value,
    _date_value,
    passport_age_group,
):
    _function.__module__ = "app.infrastructure.export.passport_excel_exporter"
del _function
