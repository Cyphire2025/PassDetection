"""Canonical contact values and workbook capacity limits."""

from __future__ import annotations

import re
from typing import Any, cast

from fastapi import HTTPException, status

from app.application.use_cases.whatsapp.contact_import_limits import (
    MAX_WHATSAPP_EXCEL_ROWS as MAX_WHATSAPP_EXCEL_ROWS,
)
from app.application.use_cases.whatsapp.contact_import_limits import (
    MAX_WHATSAPP_REJECTED_CONTACTS_PER_GROUP as MAX_WHATSAPP_REJECTED_CONTACTS_PER_GROUP,
)
from app.application.use_cases.whatsapp.contact_import_limits import (
    MAX_WHATSAPP_REJECTED_ROWS as MAX_WHATSAPP_REJECTED_ROWS,
)
from app.application.use_cases.whatsapp.contact_normalization import (
    clean_whatsapp_name,
    normalize_whatsapp_phone,
)
from app.application.use_cases.whatsapp.spreadsheet_values import (
    excel_cell_text,
    validate_excel_archive,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppContactRejectionCode,
)

_excel_cell_text = excel_cell_text

PHONE_RE = re.compile(r"(?:\+|00)?\d[\d\s().-]{7,}\d")

MAX_WHATSAPP_EXCEL_UNCOMPRESSED_BYTES = 50 * 1024 * 1024

MAX_WHATSAPP_EXCEL_ARCHIVE_MEMBERS = 2_000

MAX_WHATSAPP_EXCEL_COMPRESSION_RATIO = 250

MAX_WHATSAPP_EXCEL_HEADER_SCAN_ROWS = 25

MAX_WHATSAPP_IMPORTED_FIELDS = 256

MAX_WHATSAPP_IMPORTED_FIELD_KEY_LENGTH = 64

MAX_WHATSAPP_IMPORTED_FIELD_VALUE_LENGTH = 256

MAX_WHATSAPP_IMPORTED_FIELDS_BYTES = 8 * 1024

WHATSAPP_UPLOAD_READ_CHUNK_BYTES = 1024 * 1024

WHATSAPP_ROSTER_SOURCE_FIELDS = frozenset(
    {"source_file", "source_order", "source_sheet", "source_row"}
)

WHATSAPP_NON_MATCHING_IMPORTED_FIELDS = WHATSAPP_ROSTER_SOURCE_FIELDS | frozenset(
    {"duplicate_conflicting_fields"}
)

_MATCHING_FIELD_LABELS = {
    "name": "Name",
    "phone_number": "Mobile number",
    "email": "Email",
    "date_of_birth": "Date of birth",
    "dob": "DOB",
    "passport_number": "Passport number",
    "staff_code": "Staff code",
    "agent_employee_code": "Producer code",
}

_EXCEL_FIELD_ALIASES = {
    "contact name": "name",
    "employee": "name",
    "employee name": "name",
    "full name": "name",
    "passenger": "name",
    "passenger name": "name",
    "recipient": "name",
    "recipient name": "name",
    "staff": "name",
    "staff name": "name",
    "staffname": "name",
    "contact": "phone_number",
    "contact no": "phone_number",
    "contact number": "phone_number",
    "mobile": "phone_number",
    "mobile no": "phone_number",
    "mobile number": "phone_number",
    "phone": "phone_number",
    "phone no": "phone_number",
    "phone number": "phone_number",
    "telephone": "phone_number",
    "whatsapp": "phone_number",
    "whatsapp no": "phone_number",
    "whatsapp number": "phone_number",
    "verified whatsapp number": "phone_number",
    "verified whatsapp numbers": "phone_number",
    "email address": "email",
    "e mail": "email",
    "mail": "email",
    "upload email": "client_email",
    "upload e mail": "client_email",
    "upload email address": "client_email",
    "passport": "passport_number",
    "passport no": "passport_number",
    "passport number": "passport_number",
    "passport_no": "passport_number",
    "staff code": "staff_code",
    "staffcode": "staff_code",
    "employee code": "staff_code",
    "agent code": "agent_code",
    "agentcode": "agent_code",
    "agent company": "agent_company",
    "company name": "company",
    "given name": "given_names",
    "given names": "given_names",
}

_EMPTY_EXCEL_VALUES = frozenset({"-", "--", "n a", "na", "none", "null", "#n/a"})

_WHATSAPP_CONTACT_REJECTION_REASONS: dict[WhatsAppContactRejectionCode, str] = {
    "missing_phone": "Add a WhatsApp number for this contact.",
    "invalid_phone": (
        "Use a 10-digit Indian mobile number, or an international number of "
        "8 to 15 digits with its country code (prefix shorter numbers with + or 00)."
    ),
    "missing_name": "Add the recipient's name so staff can identify this contact.",
    "duplicate_phone": (
        "This WhatsApp number is already listed; the first delivery contact is "
        "retained and this source row remains available for staff review."
    ),
}


def _validated_rejection_code(value: str) -> WhatsAppContactRejectionCode:
    if value not in {
        "missing_phone",
        "invalid_phone",
        "missing_name",
        "duplicate_phone",
    }:
        raise RuntimeError("Invalid persisted WhatsApp contact rejection code.")
    return cast(WhatsAppContactRejectionCode, value)


def _normalize_phone(raw: str) -> str | None:
    return normalize_whatsapp_phone(raw)


def _clean_name(value: Any) -> str | None:
    return clean_whatsapp_name(value)


def _clean_required_name(value: Any, field_label: str) -> str:
    cleaned = _clean_name(value)
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_label} is required",
        )
    return cleaned


def _validate_excel_archive(payload: bytes) -> None:
    try:
        validate_excel_archive(
            payload,
            max_members=MAX_WHATSAPP_EXCEL_ARCHIVE_MEMBERS,
            max_uncompressed_bytes=MAX_WHATSAPP_EXCEL_UNCOMPRESSED_BYTES,
            max_compression_ratio=MAX_WHATSAPP_EXCEL_COMPRESSION_RATIO,
            ratio_threshold_bytes=WHATSAPP_UPLOAD_READ_CHUNK_BYTES,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _excel_header_label(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _excel_cell_text(value).casefold()).strip()


def _excel_field_key(value: Any) -> str:
    label = _excel_header_label(value)
    if not label:
        return ""
    alias = _EXCEL_FIELD_ALIASES.get(label)
    if alias:
        return alias
    return re.sub(r"_+", "_", label.replace(" ", "_"))[:MAX_WHATSAPP_IMPORTED_FIELD_KEY_LENGTH]
