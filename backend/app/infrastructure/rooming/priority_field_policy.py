"""Canonical rooming field privacy and normalization rules; no data access."""

from __future__ import annotations

import re
import unicodedata

MAX_ROOMING_PRIORITY_FIELDS = 6


MAX_ROOMING_METADATA_FIELDS = 256


MAX_ROOMING_FIELD_KEY_LENGTH = 180


ROOMING_GENDER_RULE = (
    "Male passengers are paired only with male passengers; "
    "female passengers only with female passengers."
)


_UNAVAILABLE_PRIORITY_ALIASES = frozenset(
    {
        # Required fixed output columns.
        "staff_code",
        "staffcode",
        "staff_id",
        "employee_id",
        "emp_id",
        "national_id",
        "government_id",
        "govt_id",
        "tax_id",
        "customer_id",
        "client_id",
        "voter_id",
        "ssn",
        "tin",
        "gstin",
        "agent_employee_code",
        "agent_employee_type",
        "agent_code",
        "employee_code",
        "age",
        "age_group",
        "given_names",
        "given_name",
        "first_name",
        "surname",
        "last_name",
        "family_name",
        "name",
        "full_name",
        "client_name",
        "passenger_name",
        "recipient_name",
        "staff_name",
        "employee_name",
        "sex",
        "gender",
        "passport_number",
        "passport_num",
        "passport_no",
        "passport",
        "passportnum",
        "date_of_birth",
        "dob",
        "birth_date",
        "date_of_issue",
        "dateofissue",
        "issue_date",
        "doi",
        "date_of_expiry",
        "dateofexpiry",
        "expiry_date",
        "expiration_date",
        "doe",
        "place_of_issue",
        "placeofissue",
        "issue_place",
        "room_number",
        "room_type",
        "vip",
        # Import provenance is not a traveller attribute.
        "source_file",
        "source_sheet",
        "sheet_name",
        "source_row",
        "source_order",
        "row_number",
        # Direct identity/contact, credentials, and government identifiers are
        # intentionally unavailable through the generic grouping surface.
        "id",
        "record_id",
        "user_id",
        "phone",
        "phone_number",
        "mobile",
        "mobile_number",
        "contact",
        "contact_no",
        "contact_number",
        "telephone",
        "telephone_number",
        "tel",
        "cell",
        "cell_number",
        "whatsapp",
        "whatsapp_number",
        "wa",
        "wa_no",
        "wa_number",
        "w_app",
        "w_app_no",
        "w_app_number",
        "mob",
        "mob_no",
        "mob_number",
        "ph",
        "ph_no",
        "ph_number",
        "email",
        "email_id",
        "mail",
        "mail_id",
        "address",
        "addr",
        "residential_addr",
        "residential_address",
        "home_address",
        "aadhaar",
        "aadhaar_number",
        "aadhar",
        "aadhar_number",
        "pan",
        "pan_number",
        "visa_number",
        "visa_reference",
        "token",
        "password",
        "secret",
    }
)


_UNAVAILABLE_COMPACT_PRIORITY_ALIASES = frozenset(
    alias.replace("_", "") for alias in _UNAVAILABLE_PRIORITY_ALIASES
)


_NON_GROUPABLE_FIELD_KEYS = frozenset(
    {
        "field:client_phone",
        "field:client_email",
        "field:family_group",
    }
)


def normalize_imported_field_key(value: object) -> str:
    """Normalize external spreadsheet headers into stable API keys."""

    raw_value = unicodedata.normalize("NFKC", str(value or ""))
    camel_case_split = re.sub(
        r"(?<=[A-Z])(?=[A-Z][a-z])|(?<=[a-z0-9])(?=[A-Z])",
        " ",
        raw_value,
    )
    return "_".join(
        part
        for part in "".join(
            character.casefold() if character.isalnum() else " " for character in camel_case_split
        ).split()
        if part
    )


def _is_unavailable_priority(value: object) -> bool:
    normalized = normalize_imported_field_key(value)
    # Compatibility normalization keeps useful Unicode labels intact while a
    # second accent-insensitive projection prevents visually varied identity
    # headers (for example full-width or accented phone labels) bypassing the
    # fail-closed grouping filter.
    security_normalized = "".join(
        character
        for character in unicodedata.normalize("NFKD", normalized)
        if not unicodedata.combining(character)
    )
    tokens = set(security_normalized.split("_"))
    compact = security_normalized.replace("_", "")
    return (
        not normalized
        or normalized in _UNAVAILABLE_PRIORITY_ALIASES
        or compact in _UNAVAILABLE_COMPACT_PRIORITY_ALIASES
        or bool(
            tokens
            & {
                "aadhaar",
                "aadhar",
                "address",
                "birth",
                "cell",
                "contact",
                "dob",
                "email",
                "gender",
                "hash",
                "mobile",
                "name",
                "pan",
                "passport",
                "password",
                "phone",
                "secret",
                "sex",
                "token",
                "visa",
                "whatsapp",
                "tel",
                "telephone",
            }
        )
        or compact.startswith("gender")
        or compact.endswith("gender")
        or security_normalized.endswith("_addr")
        or any(
            sensitive_compound in compact
            for sensitive_compound in (
                "whatsapp",
                "email",
                "telephone",
                "mobile",
                "phone",
                "contact",
                "address",
                "passport",
                "aadhaar",
                "aadhar",
                "password",
                "secret",
                "token",
            )
        )
        or (normalized.startswith("source_") and normalized != "source_zone")
    )


def _clean_value(value: object) -> str | None:
    normalized = " ".join(str(value or "").strip().split())
    if not normalized or normalized.casefold() in {"null", "none", "n/a", "na"}:
        return None
    return normalized


def is_rooming_roster_field(field: dict[str, str]) -> bool:
    """Return whether a priority field is safe for the generic roster UI."""

    key = field.get("key", "")
    label = field.get("label", "")
    return (
        bool(key) and key not in _NON_GROUPABLE_FIELD_KEYS and not _is_unavailable_priority(label)
    )
