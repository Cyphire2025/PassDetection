"""Shared XLSX cell conversion without rewriting legacy source values."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FORMULA_PREFIXES = ("=", "+", "-", "@")


def safe_xlsx_value(value: Any) -> Any:
    """Keep untrusted text from being interpreted as an Excel formula."""
    if isinstance(value, str) and value.lstrip().startswith(_FORMULA_PREFIXES):
        return f"'{value}"
    return value


def excel_date_value(value: Any) -> Any:
    """Use native dates for canonical values and preserve other legacy text."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not _ISO_DATE_PATTERN.fullmatch(value.strip()):
        return value
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return value
