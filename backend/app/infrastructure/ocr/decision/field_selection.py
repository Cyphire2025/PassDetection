"""Field completeness rules for deterministic OCR decisions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class FieldCompletenessPolicy:
    """Knows the minimum field set required for a complete Indian passport result."""

    _CORE_FIELDS = (
        "surname",
        "given_names",
        "passport_number",
        "nationality",
        "issuing_country",
        "date_of_birth",
        "date_of_expiry",
        "sex",
    )

    def has_complete_core_fields(self, fields: Mapping[str, Any]) -> bool:
        return all(fields.get(field) for field in self._CORE_FIELDS)
