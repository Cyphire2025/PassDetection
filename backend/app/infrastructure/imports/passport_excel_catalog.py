"""Reviewed Excel resource limits, exact header aliases and normalization rules."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Final

MAX_PASSPORT_EXCEL_WORKSHEETS: Final[int] = 50
MAX_PASSPORT_EXCEL_ROWS: Final[int] = 10_000
MAX_PASSPORT_EXCEL_COLUMNS: Final[int] = 256
MAX_PASSPORT_EXCEL_ARCHIVE_MEMBERS: Final[int] = 2_000
MAX_PASSPORT_EXCEL_UNCOMPRESSED_BYTES: Final[int] = 50 * 1024 * 1024
MAX_PASSPORT_EXCEL_COMPRESSION_RATIO: Final[int] = 250
PASSPORT_EXCEL_COMPRESSION_RATIO_MIN_BYTES: Final[int] = 1024 * 1024
PASSPORT_EXCEL_HEADER_SCAN_ROWS: Final[int] = 25
MAX_PASSPORT_NUMBER_LENGTH: Final[int] = 32
MAX_PASSPORT_EXCEL_CELL_CHARACTERS: Final[int] = 2_048
MAX_PASSPORT_EXCEL_POPULATED_CELLS: Final[int] = 100_000
MAX_PASSPORT_EXCEL_METADATA_CHARACTERS: Final[int] = 8_000_000

_NAME_FIELDS: Final[frozenset[str]] = frozenset({"client_name", "given_names", "surname"})
_DATE_FIELDS: Final[frozenset[str]] = frozenset(
    {"date_of_birth", "date_of_issue", "date_of_expiry"}
)
_RESERVED_METADATA_KEYS: Final[frozenset[str]] = frozenset({
    "source_sheet", "source_zone", "client_collection_submitted",
})
_EMPTY_CELL_VALUES: Final[frozenset[str]] = frozenset(
    {"", "-", "--", "#n/a", "n/a", "na", "none", "null"}
)
_EXCEL_ERROR_CELL_VALUES: Final[frozenset[str]] = frozenset(
    {
        "#blocked!",
        "#calc!",
        "#connect!",
        "#div/0!",
        "#field!",
        "#getting_data",
        "#name?",
        "#null!",
        "#num!",
        "#ref!",
        "#spill!",
        "#unknown!",
        "#value!",
    }
)
_MIXED_NUMERIC_DATE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^\s*([0-9]{1,4})[\s._/-]+([0-9]{1,2})[\s._/-]+([0-9]{1,4})\s*$"
)


def _normalized_header_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _header_identity(value: Any) -> str:
    """Collapse harmless spacing/punctuation variants into one exact key."""

    return _normalized_header_text(value).replace(" ", "")


def _canonicalize_numeric_date_separators(value: str) -> str:
    """Unify strict three-part numeric dates before shared validation."""

    match = _MIXED_NUMERIC_DATE_PATTERN.fullmatch(value)
    if match is None:
        return value
    first, second, third = match.groups()
    if (len(first) == 4 and len(third) <= 2) or (len(first) <= 2 and len(third) == 4):
        return f"{first}-{second}-{third}"
    return value


_HEADER_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    # An explicit spreadsheet contact source, never a public collection/OTP marker.
    "verified_whatsapp_numbers": ("verified whatsapp numbers", "verified whatsapp number"),
    "client_name": (
        "passenger name",
        "full name",
        "client name",
        "traveller name",
        "traveler name",
        "guest name",
        "recipient name",
        "staff name",
        "staffname",
        "passenger",
        "name",
    ),
    "client_email": (
        "email address",
        "client email",
        "passenger email",
        "email",
        "e-mail",
    ),
    "client_phone": (
        "whatsapp number",
        "whatsapp no",
        "mobile number",
        "mobile no",
        "phone number",
        "phone no",
        "contact number",
        "contact no",
        "client phone",
        "telephone",
        "whatsapp",
        "mobile",
        "phone",
        "contact",
    ),
    "departure_city": (
        "departure city",
        "departure hub",
        "hub",
        "city",
    ),
    "nearest_domestic_airport": (
        "nearest domestic airport",
        "nearest airport domestic",
        "domestic airport",
    ),
    "surname": (
        "surname",
        "sur name",
        "family name",
        "last name",
    ),
    "given_names": (
        "given names",
        "given name",
        "first name",
        "forenames",
        "forename",
    ),
    "passport_number": (
        "passport number",
        "passport no",
        "passport num",
        "passport #",
        "passport",
        "pp number",
        "pp no",
        "ppt number",
        "ppt no",
    ),
    "nationality": ("nationality", "citizenship"),
    "place_of_issue": (
        "place of issue",
        "place of issuance",
        "passport place of issue",
        "issue place",
    ),
    "issuing_country": (
        # Preserve legacy imports under their original meaning. These values
        # are not Place of Issue and are never AI-verified as such.
        "issuing country",
        "issue country",
        "country of issue",
    ),
    "date_of_birth": (
        "date of birth",
        "birth date",
        "birthdate",
        "dob",
    ),
    "date_of_issue": (
        "date of issue",
        "date of issuance",
        "passport issue date",
        "passport issue",
        "issue date",
        "doi",
    ),
    "date_of_expiry": (
        "date of expiry",
        "date of expiration",
        "passport expiry date",
        "passport expiration date",
        "passport expiry",
        "passport expiration",
        "expiry date",
        "expiration date",
        "expiry",
        "expiration",
        "valid until",
        "valid till",
        "doe",
    ),
    "sex": ("gender", "sex"),
    "staff_code": (
        "staff code",
        "staffcode",
        "employee code",
        "employee id",
        "staff id",
    ),
}


@dataclass(frozen=True)
class _HeaderAlias:
    field: str
    priority: int


def _build_header_alias_index() -> dict[str, _HeaderAlias]:
    index: dict[str, _HeaderAlias] = {}
    for field, aliases in _HEADER_ALIASES.items():
        for priority, alias in enumerate(aliases):
            identity = _header_identity(alias)
            existing = index.get(identity)
            if existing is not None and existing.field != field:
                raise RuntimeError(f"Excel header alias {alias!r} maps to multiple fields")
            if existing is None or priority < existing.priority:
                index[identity] = _HeaderAlias(field=field, priority=priority)
    return index


_HEADER_ALIAS_INDEX: Final[dict[str, _HeaderAlias]] = _build_header_alias_index()

# Preserve the legacy import identity used by diagnostics and serialization.
_HeaderAlias.__module__ = "app.infrastructure.imports.passport_excel_importer"
