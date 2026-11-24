"""Tracker spreadsheet bounds, identity normalization and canonical field values."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from app.infrastructure.database.models import PassportSubmissionModel

MAX_UPLOAD_BYTES = 8 * 1024 * 1024


MAX_IMPORT_ROWS = 1000


MAX_EXPORT_ROWS = 20000


MAX_COLUMNS = 256


class TrackerSpreadsheetError(ValueError):
    pass


def field_values(passenger: PassportSubmissionModel) -> dict[str, Any]:
    return {**(passenger.extracted_fields or {}), **(passenger.confirmed_fields or {})}


def text_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip() or None


def full_name(passenger: PassportSubmissionModel) -> str:
    fields = field_values(passenger)
    return (
        " ".join(str(passenger.client_name or "").split())
        or " ".join(
            str(fields.get(key) or "").strip() for key in ("given_names", "surname")
        ).strip()
        or "Unnamed passenger"
    )


def normalized_name(value: Any) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).split()).casefold()


def normalized_passport(value: Any) -> str:
    return re.sub(r"[\s-]+", "", unicodedata.normalize("NFKC", str(value or ""))).upper()
