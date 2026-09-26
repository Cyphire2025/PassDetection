"""Prepare independent role credentials without rotating existing credentials."""

from __future__ import annotations

import re
import secrets

ROLE_DEFAULTS = {
    "POSTGRES_RUNTIME_USER": "passdetection_runtime",
    "POSTGRES_MIGRATION_USER": "passdetection_migrator",
}
PASSWORD_KEYS = {"POSTGRES_RUNTIME_PASSWORD", "POSTGRES_MIGRATION_PASSWORD"}


def prepare_database_identity_environment(text: str) -> str:
    defaults = {**ROLE_DEFAULTS, **{key: secrets.token_urlsafe(48) for key in sorted(PASSWORD_KEYS)}}
    return prepare_environment_defaults(text, defaults)


def prepare_environment_defaults(text: str, defaults: dict[str, str]) -> str:
    """Fill only missing/placeholder values; preserve existing credentials."""
    lines, seen = [], set()
    for line in text.splitlines():
        match = re.match(r"^\s*(?:export\s+)?([A-Z_]+)\s*=\s*(.*)$", line)
        key = match.group(1) if match else ""
        if key in defaults:
            if key in seen:
                raise ValueError(f"Duplicate {key}; resolve the protected environment before release")
            seen.add(key)
            value = match.group(2).strip().strip("\"'")
            if not value or value.startswith("CHANGE_ME_"):
                line = f"{key}={defaults[key]}"
        lines.append(line)
    lines.extend(f"{key}={value}" for key, value in defaults.items() if key not in seen)
    return "\n".join(lines) + "\n"
