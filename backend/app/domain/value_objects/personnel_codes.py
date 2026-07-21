"""Canonical display values for staff and Agent/Employee codes."""

from __future__ import annotations

from typing import Any


def prefixed_staff_code(value: Any) -> str | None:
    return _prefixed_code("STF", value)


def prefixed_agent_employee_code(person_type: Any, code: Any) -> str | None:
    normalized_type = str(person_type or "").strip().casefold()
    prefix = {"agent": "AGT", "employee": "EMP"}.get(normalized_type)
    if not prefix:
        return None
    return _prefixed_code(prefix, code)


def _prefixed_code(prefix: str, value: Any) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    upper_value = normalized.upper()
    for separator in ("_", "-", " "):
        expected_prefix = f"{prefix}{separator}"
        if upper_value.startswith(expected_prefix):
            suffix = normalized[len(expected_prefix):].strip()
            return f"{prefix}_{suffix}" if suffix else None
    return f"{prefix}_{normalized}"
