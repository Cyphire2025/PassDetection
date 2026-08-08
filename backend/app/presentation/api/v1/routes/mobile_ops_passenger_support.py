"""Passenger projection and document boundaries for Group Companion operations."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import func

from app.domain.value_objects.travel_document_taxonomy import mobile_document_category
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.rooming.priority_fields import normalize_imported_field_key
from app.presentation.api.v1.schemas.mobile_schemas import MobileCoordinatorOperationalDetail

_MAX_COORDINATOR_OPERATIONAL_DETAILS = 300
_COORDINATOR_PROJECTED_METADATA_KEYS = frozenset(
    {
        "agency_dealership_name",
        "base_city",
        "birth_date",
        "birthdate",
        "client_email",
        "client_name",
        "client_phone",
        "contact",
        "contact_no",
        "contact_number",
        "date_of_birth",
        "date_of_expiration",
        "date_of_expiry",
        "date_of_issue",
        "date_of_issuance",
        "department",
        "departure_city",
        "departure_hub",
        "designation",
        "dob",
        "doe",
        "doi",
        "domestic_airport",
        "e_mail",
        "email",
        "email_address",
        "emergency_contact_name",
        "emergency_contact_number",
        "emergency_contact_person",
        "emergency_contact_phone",
        "emergency_contact_relation",
        "emergency_mobile",
        "emergency_name",
        "emergency_person",
        "emergency_phone",
        "emergency_relation",
        "employee_code",
        "employee_id",
        "employee_type",
        "expiration",
        "expiration_date",
        "expiry",
        "expiry_date",
        "family_name",
        "first_name",
        "forename",
        "forenames",
        "full_name",
        "gender",
        "given_name",
        "given_names",
        "guest_name",
        "hub",
        "international_airport",
        "issue_country",
        "issue_date",
        "issue_place",
        "issuing_country",
        "last_name",
        "meal_preference",
        "mobile",
        "mobile_no",
        "mobile_number",
        "name",
        "nationality",
        "nearest_airport_domestic",
        "nearest_domestic_airport",
        "passenger",
        "passenger_email",
        "passenger_name",
        "phone",
        "phone_no",
        "phone_number",
        "place_of_issue",
        "place_of_issuance",
        "recipient_name",
        "remark",
        "remarks",
        "sex",
        "source_zone",
        "staff_code",
        "staff_id",
        "staff_name",
        "staffname",
        "sur_name",
        "surname",
        "telephone",
        "traveler_name",
        "traveller_name",
        "valid_till",
        "valid_until",
        "whatsapp",
        "whatsapp_no",
        "whatsapp_number",
        "zone",
        "zone_name",
        "zonename",
    }
)
_COORDINATOR_SENSITIVE_METADATA_TOKENS = frozenset(
    {
        "aadhaar",
        "aadhar",
        "address",
        "admin",
        "ai",
        "booking",
        "bucket",
        "confidence",
        "credential",
        "document",
        "error",
        "extraction",
        "file",
        "filename",
        "hash",
        "image",
        "internal",
        "mrz",
        "note",
        "notes",
        "object",
        "ocr",
        "pan",
        "passport",
        "password",
        "path",
        "photo",
        "private",
        "pnr",
        "prompt",
        "reference",
        "reservation",
        "raw",
        "s3",
        "scan",
        "score",
        "secret",
        "selfie",
        "signature",
        "storage",
        "ticket",
        "token",
        "uri",
        "url",
        "visa",
    }
)
_COORDINATOR_SENSITIVE_METADATA_COMPOUNDS = (
    "bookingcode",
    "internalcomment",
    "internalnote",
    "passportno",
    "passportnum",
    "passportnumber",
    "postsubmissionverification",
    "staffcomment",
    "staffnote",
)
_COORDINATOR_DOCUMENT_CATEGORY_ALIASES = {
    "ticket": "flight_ticket",
    "insurance": "insurance",
    "travel_insurance": "insurance",
    "hotel_voucher": "hotel_voucher",
    "voucher": "hotel_voucher",
    "other": "other",
}


def _validate_manager_document_signature(signature: bytes, content_type: str) -> None:
    valid = {
        "application/pdf": signature.startswith(b"%PDF-"),
        "image/jpeg": signature.startswith(b"\xff\xd8\xff"),
        "image/png": signature.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": (
            len(signature) >= 12
            and signature.startswith(b"RIFF")
            and signature[8:12] == b"WEBP"
        ),
    }.get(content_type, False)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="The stored document type does not match its content",
        )


def _coordinator_reviewed_passport_field(field: str) -> Any:
    """Resolve reviewed passport data before extraction fallback.

    The raw JSON documents never leave the server; callers select only one
    named operational field at a time.
    """

    return func.coalesce(
        PassportSubmissionModel.confirmed_fields[field].as_string(),
        PassportSubmissionModel.extracted_fields[field].as_string(),
    )


def _coordinator_document_category(value: object) -> str:
    """Map only recognized document categories; unknown values stay generic."""

    normalized = normalize_imported_field_key(value)
    distribution_category = mobile_document_category(normalized)
    if distribution_category is not None:
        return distribution_category
    return _COORDINATOR_DOCUMENT_CATEGORY_ALIASES.get(normalized, "other")


def _coordinator_metadata_value(
    metadata: dict[object, object],
    keys: tuple[str, ...],
    *,
    max_length: int,
) -> str | None:
    normalized = {
        normalize_imported_field_key(raw_key): raw_value for raw_key, raw_value in metadata.items()
    }
    for key in keys:
        value = _bounded_optional_text(normalized.get(key), max_length)
        if value is not None:
            return value
    return None


def _coordinator_operational_details(
    *,
    staff_metadata: dict[object, object],
    custom_answers: object,
    custom_detail_answers: object,
) -> list[MobileCoordinatorOperationalDetail]:
    """Build a bounded, fail-closed projection of extra passenger attributes.

    Imported spreadsheets intentionally retain their source columns for office
    workflows. Mobile coordinators receive only display-safe operational
    values. Known first-class fields are de-duplicated, while storage details,
    government identifiers, document secrets, extraction/AI data, and internal
    notes are rejected by normalized key and label.
    """

    details: list[MobileCoordinatorOperationalDetail] = []
    seen: set[str] = set()

    def append_detail(
        *,
        raw_key: object,
        raw_label: object,
        raw_value: object,
        source: Literal["imported", "custom_question", "custom_detail"],
    ) -> None:
        if len(details) >= _MAX_COORDINATOR_OPERATIONAL_DETAILS:
            return
        key = normalize_imported_field_key(raw_key)
        label_key = normalize_imported_field_key(raw_label)
        if not key or not label_key:
            return
        if source == "imported" and key in _COORDINATOR_PROJECTED_METADATA_KEYS:
            return
        if not _coordinator_metadata_field_is_safe(key, label_key):
            return
        value = _bounded_operational_value(raw_value, 2048)
        label = _bounded_optional_text(raw_label, 120)
        if value is None or label is None:
            return
        stable_key = f"{source}:{key}"[:160]
        if stable_key in seen:
            return
        seen.add(stable_key)
        details.append(
            MobileCoordinatorOperationalDetail(
                key=stable_key,
                label=label,
                value=value,
                source=source,
            )
        )

    def append_custom_details(
        values: object,
        *,
        source: Literal["custom_question", "custom_detail"],
        id_key: Literal["question_id", "detail_id"],
    ) -> None:
        if not isinstance(values, list):
            return
        for item in values:
            if not isinstance(item, dict):
                continue
            label = item.get("label")
            append_detail(
                raw_key=item.get(id_key) or label,
                raw_label=label,
                raw_value=item.get("value"),
                source=source,
            )

    for raw_key, raw_value in staff_metadata.items():
        key = normalize_imported_field_key(raw_key)
        append_detail(
            raw_key=key,
            raw_label=_coordinator_metadata_label(key),
            raw_value=raw_value,
            source="imported",
        )
    append_custom_details(
        custom_answers,
        source="custom_question",
        id_key="question_id",
    )
    append_custom_details(
        custom_detail_answers,
        source="custom_detail",
        id_key="detail_id",
    )
    return details


def _coordinator_metadata_field_is_safe(key: str, label_key: str) -> bool:
    normalized = f"{key}_{label_key}"
    tokens = set(normalized.split("_"))
    compact = normalized.replace("_", "")
    return not (
        key.startswith("source_")
        or bool(tokens & _COORDINATOR_SENSITIVE_METADATA_TOKENS)
        or any(value in compact for value in _COORDINATOR_SENSITIVE_METADATA_COMPOUNDS)
    )


def _coordinator_metadata_label(key: str) -> str:
    acronyms = {"dob": "DOB", "id": "ID", "pnr": "PNR"}
    return " ".join(acronyms.get(part, part.capitalize()) for part in key.split("_") if part)


def _bounded_operational_value(value: object, max_length: int) -> str | None:
    """Render only bounded scalar spreadsheet values for coordinator display."""

    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)):
        return str(value)[:max_length]
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:max_length]
    return _bounded_optional_text(value, max_length)


def _bounded_optional_text(value: object, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned[:max_length] or None


def _safe_optional_date(value: object) -> date | None:
    """Parse only known imported date formats without leaking malformed data."""

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    cleaned = _bounded_optional_text(value, 32)
    if cleaned is None:
        return None
    for parser in (
        date.fromisoformat,
        lambda item: datetime.strptime(item, "%d/%m/%Y").date(),
        lambda item: datetime.strptime(item, "%d-%m-%Y").date(),
    ):
        try:
            return parser(cleaned)
        except ValueError:
            continue
    return None
