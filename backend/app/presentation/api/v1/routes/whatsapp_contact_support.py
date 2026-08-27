"""Contact import, roster normalization, and response helpers for WhatsApp routes."""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from typing import Any, Literal, cast
from zipfile import ZipFile

from fastapi import HTTPException, status
from sqlalchemy import func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.contact_normalization import (
    clean_whatsapp_name,
    normalize_whatsapp_phone,
)
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
    WhatsAppBroadcastSupportContactModel,
    WhatsAppRecipientMessageStateModel,
)
from app.presentation.api.v1.routes.whatsapp_delivery_support import (
    WHATSAPP_ACCEPTED_STATUSES,
    WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES,
    WHATSAPP_SUPPRESSED_STATUSES,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppContactPreviewRecipient,
    WhatsAppContactPreviewRejectedRow,
    WhatsAppContactPreviewResponse,
    WhatsAppContactRejectionCode,
    WhatsAppRecipientInput,
    WhatsAppRecipientMessageStatusResponse,
    WhatsAppRecipientResponse,
    WhatsAppRejectedContactInput,
    WhatsAppRejectedContactResponse,
    WhatsAppSupportContactInput,
    WhatsAppSupportContactResponse,
)

PHONE_RE = re.compile(r"(?:\+|00)?\d[\d\s().-]{7,}\d")
MAX_WHATSAPP_EXCEL_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_WHATSAPP_EXCEL_ARCHIVE_MEMBERS = 2_000
MAX_WHATSAPP_EXCEL_COMPRESSION_RATIO = 250
MAX_WHATSAPP_EXCEL_HEADER_SCAN_ROWS = 25
MAX_WHATSAPP_REJECTED_CONTACTS_PER_GROUP = 500
MAX_WHATSAPP_IMPORTED_FIELDS = 256


def _validated_rejection_code(value: str) -> WhatsAppContactRejectionCode:
    if value not in {
        "missing_phone",
        "invalid_phone",
        "missing_name",
        "duplicate_phone",
    }:
        raise RuntimeError("Invalid persisted WhatsApp contact rejection code.")
    return cast(WhatsAppContactRejectionCode, value)
MAX_WHATSAPP_IMPORTED_FIELD_KEY_LENGTH = 64
MAX_WHATSAPP_IMPORTED_FIELD_VALUE_LENGTH = 256
MAX_WHATSAPP_IMPORTED_FIELDS_BYTES = 8 * 1024
WHATSAPP_UPLOAD_READ_CHUNK_BYTES = 1024 * 1024
WHATSAPP_ROSTER_SOURCE_FIELDS = frozenset(
    {"source_file", "source_order", "source_sheet", "source_row"}
)


@dataclass(slots=True)
class _WhatsAppExcelContactParseResult:
    contacts: list[WhatsAppRecipientInput]
    rejected_rows: list[WhatsAppContactPreviewRejectedRow]
    rejected_counts: dict[WhatsAppContactRejectionCode, int]

    @property
    def rejected_count(self) -> int:
        return sum(self.rejected_counts.values())


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
    with ZipFile(BytesIO(payload)) as archive:
        members = archive.infolist()
        if len(members) > MAX_WHATSAPP_EXCEL_ARCHIVE_MEMBERS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The Excel contact file contains too many archive entries",
            )
        total_uncompressed = sum(member.file_size for member in members)
        if total_uncompressed > MAX_WHATSAPP_EXCEL_UNCOMPRESSED_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The Excel contact file expands beyond the allowed size",
            )
        for member in members:
            if (
                member.file_size > WHATSAPP_UPLOAD_READ_CHUNK_BYTES
                and member.compress_size > 0
                and member.file_size / member.compress_size > MAX_WHATSAPP_EXCEL_COMPRESSION_RATIO
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="The Excel contact file has an unsafe compression ratio",
                )


def _excel_cell_text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        if value.is_integer():
            return str(int(value))
    return str(value).strip()


def _excel_header_label(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _excel_cell_text(value).casefold()).strip()


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
    "email address": "email",
    "e mail": "email",
    "mail": "email",
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


def _excel_field_key(value: Any) -> str:
    label = _excel_header_label(value)
    if not label:
        return ""
    alias = _EXCEL_FIELD_ALIASES.get(label)
    if alias:
        return alias
    return re.sub(r"_+", "_", label.replace(" ", "_"))[:MAX_WHATSAPP_IMPORTED_FIELD_KEY_LENGTH]


def _safe_imported_fields(value: Any) -> dict[str, str]:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recipient imported fields must be a key/value object",
        )

    cleaned: dict[str, str] = {}
    imported_field_count = 0
    total_size = 0
    for raw_key, raw_value in value.items():
        key = _excel_field_key(raw_key)
        text_value = _excel_cell_text(raw_value)
        if not key or not text_value or _excel_header_label(text_value) in _EMPTY_EXCEL_VALUES:
            continue
        if key == "name":
            text_value = _clean_name(text_value) or ""
        elif key == "phone_number":
            text_value = _normalize_phone(text_value) or text_value
        elif key == "email":
            text_value = text_value.casefold()
        elif key == "passport_number":
            text_value = re.sub(
                r"[^A-Z0-9]+",
                "",
                text_value.upper(),
            )
        elif key in {"agent_code", "staff_code"}:
            # These are imported reference values, not identifiers used for
            # authentication. Preserve meaningful separators for staff review.
            text_value = " ".join(text_value.upper().split())
        else:
            text_value = " ".join(text_value.split())
        if not text_value:
            continue
        is_roster_source_field = key in WHATSAPP_ROSTER_SOURCE_FIELDS
        if (
            not is_roster_source_field
            and imported_field_count >= MAX_WHATSAPP_IMPORTED_FIELDS
            and key not in cleaned
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Each WhatsApp recipient can contain at most "
                    f"{MAX_WHATSAPP_IMPORTED_FIELDS} imported fields"
                ),
            )
        text_value = text_value[:MAX_WHATSAPP_IMPORTED_FIELD_VALUE_LENGTH]
        if key in cleaned:
            continue
        total_size += len(key.encode("utf-8")) + len(text_value.encode("utf-8"))
        if total_size > MAX_WHATSAPP_IMPORTED_FIELDS_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A WhatsApp recipient's imported fields are too large",
            )
        cleaned[key] = text_value
        if not is_roster_source_field:
            imported_field_count += 1
    return cleaned


def _is_excel_phone_header(label: str) -> bool:
    tokens = set(label.split())
    if tokens.intersection({"phone", "mobile", "whatsapp", "telephone"}):
        return True
    return "contact" in tokens and (
        len(tokens) == 1 or bool(tokens.intersection({"number", "no", "phone", "mobile"}))
    )


def _is_excel_name_header(label: str) -> bool:
    return _excel_field_key(label) == "name"


def _excel_header_columns(
    row: tuple[Any, ...],
) -> tuple[list[int], list[int], list[int], list[int]]:
    labels = [_excel_header_label(cell) for cell in row]
    field_keys = [_excel_field_key(cell) for cell in row]
    phone_columns = [
        index for index, label in enumerate(labels) if label and _is_excel_phone_header(label)
    ]
    name_columns = [
        index
        for index, label in enumerate(labels)
        if label and _is_excel_name_header(label) and index not in phone_columns
    ]
    given_name_columns = [index for index, key in enumerate(field_keys) if key == "given_names"]
    surname_columns = [index for index, key in enumerate(field_keys) if key == "surname"]
    return (
        phone_columns,
        name_columns,
        given_name_columns,
        surname_columns,
    )


def _find_excel_contact_header(
    rows: list[tuple[Any, ...]],
) -> tuple[int, list[int], list[int], list[int], list[int]] | None:
    best_match: (
        tuple[
            tuple[int, int, int],
            int,
            list[int],
            list[int],
            list[int],
            list[int],
        ]
        | None
    ) = None
    for row_index, row in enumerate(rows[:MAX_WHATSAPP_EXCEL_HEADER_SCAN_ROWS]):
        (
            phone_columns,
            name_columns,
            given_name_columns,
            surname_columns,
        ) = _excel_header_columns(row)
        if not phone_columns:
            continue
        score = (
            1 if name_columns or given_name_columns else 0,
            (
                len(phone_columns)
                + len(name_columns)
                + len(given_name_columns)
                + len(surname_columns)
            ),
            -row_index,
        )
        if best_match is None or score > best_match[0]:
            best_match = (
                score,
                row_index,
                phone_columns,
                name_columns,
                given_name_columns,
                surname_columns,
            )
    if best_match is None:
        return None
    (
        _,
        row_index,
        phone_columns,
        name_columns,
        given_name_columns,
        surname_columns,
    ) = best_match
    return (
        row_index,
        phone_columns,
        name_columns,
        given_name_columns,
        surname_columns,
    )


def _excel_name_from_row(
    row_values: list[Any],
    *,
    name_columns: list[int],
    given_name_columns: list[int],
    surname_columns: list[int],
    phone_columns: list[int],
) -> str | None:
    for index in name_columns:
        if index >= len(row_values):
            continue
        name = _clean_name(row_values[index])
        if name:
            return name
    given_name = next(
        (
            _clean_name(row_values[index])
            for index in given_name_columns
            if index < len(row_values) and _clean_name(row_values[index])
        ),
        None,
    )
    surname = next(
        (
            _clean_name(row_values[index])
            for index in surname_columns
            if index < len(row_values) and _clean_name(row_values[index])
        ),
        None,
    )
    composed = " ".join(part for part in (given_name, surname) if part)
    if composed:
        return composed
    if name_columns or given_name_columns or surname_columns:
        return None
    for index, value in enumerate(row_values):
        if index in phone_columns:
            continue
        name = _clean_name(value)
        if name and any(character.isalpha() for character in name) and not PHONE_RE.search(name):
            return name
    return None


def _excel_raw_name_from_row(
    row_values: list[Any],
    *,
    name_columns: list[int],
    given_name_columns: list[int],
    surname_columns: list[int],
    phone_columns: list[int],
) -> str | None:
    for index in name_columns:
        if index >= len(row_values):
            continue
        if value := _excel_cell_text(row_values[index]):
            return value[:256]
    given_name = next(
        (
            _excel_cell_text(row_values[index])
            for index in given_name_columns
            if index < len(row_values) and _excel_cell_text(row_values[index])
        ),
        None,
    )
    surname = next(
        (
            _excel_cell_text(row_values[index])
            for index in surname_columns
            if index < len(row_values) and _excel_cell_text(row_values[index])
        ),
        None,
    )
    composed = " ".join(part for part in (given_name, surname) if part)
    if composed:
        return composed[:256]
    if name_columns or given_name_columns or surname_columns:
        return None
    for index, value in enumerate(row_values):
        if index in phone_columns:
            continue
        text = _excel_cell_text(value)
        if text and any(character.isalpha() for character in text) and not PHONE_RE.search(text):
            return text[:256]
    return None


def _bounded_excel_raw_value(value: Any, *, max_length: int) -> str | None:
    text = _excel_cell_text(value)
    if not text or _excel_header_label(text) in _EMPTY_EXCEL_VALUES:
        return None
    return text[:max_length]


def _is_repeated_excel_header(
    row_values: list[Any],
    header_row: tuple[Any, ...],
) -> bool:
    identity_keys = {"given_names", "name", "phone_number", "surname"}

    def identity_signature(values: list[Any] | tuple[Any, ...]) -> tuple[tuple[int, str], ...]:
        return tuple(
            (index, key)
            for index, value in enumerate(values)
            if (key := _excel_field_key(value)) in identity_keys
        )

    header_signature = identity_signature(header_row)
    row_signature = identity_signature(row_values)
    header_keys = {key for _, key in header_signature}
    return (
        "phone_number" in header_keys
        and bool(header_keys & {"given_names", "name"})
        and row_signature == header_signature
    )


def _row_has_contact_identity(
    *,
    name: str | None,
    imported_fields: dict[str, str],
) -> bool:
    if name:
        return True
    return bool(
        imported_fields.keys()
        & {
            "agent_code",
            "email",
            "passport_number",
            "staff_code",
        }
    )


_WHATSAPP_CONTACT_REJECTION_REASONS: dict[WhatsAppContactRejectionCode, str] = {
    "missing_phone": "Add a WhatsApp number for this contact.",
    "invalid_phone": (
        "Use a 10-digit Indian mobile number, or an international number of "
        "8 to 15 digits with its country code (prefix shorter numbers with + or 00)."
    ),
    "missing_name": "Add the recipient's name so staff can identify this contact.",
    "duplicate_phone": (
        "This WhatsApp number is already listed; its extra details were merged "
        "into the first accepted contact."
    ),
}


def _excel_fields_from_row(
    *,
    header_row: tuple[Any, ...],
    row_values: list[Any],
    sheet_name: str,
    source_file_name: str,
    row_number: int,
    source_order: int,
) -> dict[str, str]:
    fields: dict[str, str] = {}
    for index, raw_header in enumerate(header_row):
        if index >= len(row_values):
            continue
        key = _excel_field_key(raw_header)
        text_value = _excel_cell_text(row_values[index])
        if not key or not text_value or _excel_header_label(text_value) in _EMPTY_EXCEL_VALUES:
            continue
        fields.setdefault(key, text_value)
    fields.setdefault("source_file", source_file_name)
    fields.setdefault("source_order", str(source_order))
    fields.setdefault("source_sheet", sheet_name)
    fields.setdefault("source_row", str(row_number))
    return _safe_imported_fields(fields)


def _merge_recipient_inputs(
    existing: WhatsAppRecipientInput,
    incoming: WhatsAppRecipientInput,
) -> WhatsAppRecipientInput:
    merged_fields = dict(existing.imported_fields)
    conflicting_keys: set[str] = set()
    for key, value in incoming.imported_fields.items():
        if key in WHATSAPP_ROSTER_SOURCE_FIELDS:
            merged_fields.setdefault(key, value)
            continue
        current = merged_fields.get(key)
        if current is None:
            merged_fields[key] = value
        elif current.casefold() != value.casefold():
            conflicting_keys.add(key)
            suffix = 2
            alternate_key = f"{key}_{suffix}"
            while alternate_key in merged_fields:
                if merged_fields[alternate_key].casefold() == value.casefold():
                    break
                suffix += 1
                alternate_key = f"{key}_{suffix}"
            else:
                merged_fields[alternate_key] = value
    if conflicting_keys:
        merged_fields["duplicate_conflicting_fields"] = ", ".join(sorted(conflicting_keys))
    return WhatsAppRecipientInput(
        name=existing.name or incoming.name,
        phone_number=existing.phone_number,
        imported_fields=_safe_imported_fields(merged_fields),
    )


def _excel_contact_preview_response(
    contacts: list[WhatsAppRecipientInput],
    rejected_rows: list[WhatsAppContactPreviewRejectedRow] | None = None,
    *,
    rejected_count: int | None = None,
) -> WhatsAppContactPreviewResponse:
    rejected_rows = rejected_rows or []
    total_rejected = len(rejected_rows) if rejected_count is None else rejected_count
    if not contacts and total_rejected == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No recipients were found. Include name and phone/WhatsApp "
                "columns with at least one contact."
            ),
        )

    normalized_contacts = _normalized_recipient_inputs(contacts) if contacts else {}
    recipients = [
        WhatsAppContactPreviewRecipient(
            name=_clean_required_name(contact.name, "Recipient name"),
            phone_number=normalized_phone,
            imported_fields=contact.imported_fields,
        )
        for normalized_phone, contact in normalized_contacts.items()
    ]
    return WhatsAppContactPreviewResponse(
        recipient_count=len(recipients),
        accepted_count=len(recipients),
        recipients=recipients,
        rejected_count=total_rejected,
        rejected_rows=rejected_rows,
        rejected_rows_truncated=total_rejected > len(rejected_rows),
        omitted_rejected_count=max(0, total_rejected - len(rejected_rows)),
    )


def _parse_manual_contacts(value: str) -> list[WhatsAppRecipientInput]:
    try:
        parsed = json.loads(value or "[]")
        if not isinstance(parsed, list):
            raise TypeError
        return [WhatsAppRecipientInput(**item) for item in parsed]
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid manual contact list",
        ) from exc


def _rejected_contact_fingerprint(
    contact: WhatsAppRejectedContactInput,
) -> str:
    payload = json.dumps(
        [
            contact.source_file_name,
            contact.sheet_name,
            contact.row_number,
            contact.raw_name,
            contact.raw_phone_number,
            contact.reason_code,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_rejected_contacts(value: str) -> list[WhatsAppRejectedContactInput]:
    try:
        parsed = json.loads(value or "[]")
        if not isinstance(parsed, list):
            raise TypeError
        if len(parsed) > MAX_WHATSAPP_REJECTED_CONTACTS_PER_GROUP:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "A WhatsApp list can contain at most "
                    f"{MAX_WHATSAPP_REJECTED_CONTACTS_PER_GROUP} rejected contacts"
                ),
            )
        contacts: list[WhatsAppRejectedContactInput] = []
        fingerprints: set[str] = set()
        for item in parsed:
            contact = WhatsAppRejectedContactInput(**item)
            source_file_name = (
                contact.source_file_name.replace("\\", "/").rsplit("/", maxsplit=1)[-1].strip()
            )
            sheet_name = contact.sheet_name.strip()
            raw_name = (contact.raw_name or "").strip() or None
            raw_phone_number = (contact.raw_phone_number or "").strip() or None
            if not source_file_name:
                raise ValueError("source_file_name is empty")
            if not sheet_name:
                raise ValueError("sheet_name is empty")
            normalized = WhatsAppRejectedContactInput(
                source_file_name=source_file_name,
                sheet_name=sheet_name,
                row_number=contact.row_number,
                raw_name=raw_name,
                raw_phone_number=raw_phone_number,
                imported_fields=_safe_imported_fields(contact.imported_fields),
                reason_code=contact.reason_code,
            )
            fingerprint = _rejected_contact_fingerprint(normalized)
            if fingerprint in fingerprints:
                continue
            fingerprints.add(fingerprint)
            contacts.append(normalized)
        return contacts
    except HTTPException:
        raise
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid rejected WhatsApp contact list",
        ) from exc


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _roster_source_sort_key(
    imported_fields: dict[str, str],
    *,
    fallback_source_file: str = "",
    fallback_source_sheet: str = "",
    fallback_source_row: int | None = None,
    stable_index: int,
) -> tuple[int, str, int, str, int, int]:
    source_file = (imported_fields.get("source_file") or fallback_source_file or "").casefold()
    source_sheet = (imported_fields.get("source_sheet") or fallback_source_sheet or "").casefold()
    source_row = _positive_int(imported_fields.get("source_row")) or fallback_source_row or 0
    source_order = _positive_int(imported_fields.get("source_order"))
    is_imported = bool(source_file or source_sheet or source_row or source_order)
    return (
        0 if is_imported else 1,
        source_file,
        source_order or source_row,
        source_sheet,
        source_row,
        stable_index,
    )


def _new_roster_display_orders(
    *,
    normalized_contacts: dict[str, WhatsAppRecipientInput],
    rejected_contacts: list[WhatsAppRejectedContactInput],
    existing_by_phone: dict[str, WhatsAppBroadcastRecipientModel],
    existing_by_fingerprint: dict[str, WhatsAppBroadcastRejectedContactModel],
    start_order: int,
) -> tuple[dict[str, int], dict[str, int]]:
    candidates: list[
        tuple[
            tuple[int, str, int, str, int, int],
            Literal["recipient", "rejected"],
            str,
        ]
    ] = []
    stable_index = 0
    for normalized_phone, contact in normalized_contacts.items():
        if normalized_phone not in existing_by_phone:
            candidates.append(
                (
                    _roster_source_sort_key(
                        contact.imported_fields,
                        stable_index=stable_index,
                    ),
                    "recipient",
                    normalized_phone,
                )
            )
        stable_index += 1
    for rejected_contact in rejected_contacts:
        fingerprint = _rejected_contact_fingerprint(rejected_contact)
        if fingerprint not in existing_by_fingerprint:
            candidates.append(
                (
                    _roster_source_sort_key(
                        rejected_contact.imported_fields,
                        fallback_source_file=rejected_contact.source_file_name,
                        fallback_source_sheet=rejected_contact.sheet_name,
                        fallback_source_row=rejected_contact.row_number,
                        stable_index=stable_index,
                    ),
                    "rejected",
                    fingerprint,
                )
            )
        stable_index += 1

    recipient_orders: dict[str, int] = {}
    rejected_orders: dict[str, int] = {}
    for offset, (_, kind, identity) in enumerate(sorted(candidates)):
        display_order = start_order + offset
        if kind == "recipient":
            recipient_orders[identity] = display_order
        else:
            rejected_orders[identity] = display_order
    return recipient_orders, rejected_orders


async def _next_roster_display_order(
    session: AsyncSession,
    group_id: uuid.UUID,
) -> int:
    existing_orders = union_all(
        select(WhatsAppBroadcastRecipientModel.display_order.label("display_order")).where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group_id,
        ),
        select(WhatsAppBroadcastRejectedContactModel.display_order.label("display_order")).where(
            WhatsAppBroadcastRejectedContactModel.broadcast_group_id == group_id,
        ),
    ).subquery()
    result = await session.execute(
        select(func.coalesce(func.max(existing_orders.c.display_order), 0))
    )
    return int(result.scalar_one()) + 1


def _add_rejected_contact_models(
    *,
    session: AsyncSession,
    group: WhatsAppBroadcastGroupModel,
    contacts: list[WhatsAppRejectedContactInput],
    existing_by_fingerprint: dict[
        str,
        WhatsAppBroadcastRejectedContactModel,
    ],
    now: datetime,
    display_orders_by_fingerprint: dict[str, int] | None = None,
) -> int:
    display_orders_by_fingerprint = display_orders_by_fingerprint or {}
    new_contacts: list[WhatsAppRejectedContactInput] = []
    for contact in contacts:
        fingerprint = _rejected_contact_fingerprint(contact)
        existing = existing_by_fingerprint.get(fingerprint)
        if existing is None:
            new_contacts.append(contact)
            continue
        # A repeated import remains one rejected row, but can enrich a record
        # created before imported spreadsheet fields were persisted.
        merged_fields = dict(existing.imported_fields or {})
        merged_fields.update(contact.imported_fields)
        existing.imported_fields = _safe_imported_fields(merged_fields)
    if len(existing_by_fingerprint) + len(new_contacts) > MAX_WHATSAPP_REJECTED_CONTACTS_PER_GROUP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "A WhatsApp list can contain at most "
                f"{MAX_WHATSAPP_REJECTED_CONTACTS_PER_GROUP} rejected contacts"
            ),
        )
    for contact in new_contacts:
        fingerprint = _rejected_contact_fingerprint(contact)
        model = WhatsAppBroadcastRejectedContactModel(
            broadcast_group_id=group.id,
            agency_id=group.agency_id,
            source_file_name=contact.source_file_name,
            sheet_name=contact.sheet_name,
            row_number=contact.row_number,
            raw_name=contact.raw_name,
            raw_phone_number=contact.raw_phone_number,
            imported_fields=_safe_imported_fields(contact.imported_fields),
            display_order=display_orders_by_fingerprint.get(fingerprint),
            reason_code=contact.reason_code,
            reason=_WHATSAPP_CONTACT_REJECTION_REASONS[contact.reason_code],
            fingerprint=fingerprint,
            created_at=now,
        )
        existing_by_fingerprint[fingerprint] = model
        session.add(model)
    return len(new_contacts)


def _normalized_recipient_inputs(
    contacts: list[WhatsAppRecipientInput],
) -> dict[str, WhatsAppRecipientInput]:
    normalized_contacts: dict[str, WhatsAppRecipientInput] = {}
    invalid_numbers: list[str] = []
    for contact in contacts:
        normalized = _normalize_phone(contact.phone_number)
        if not normalized:
            invalid_numbers.append(contact.phone_number)
            continue
        sanitized = WhatsAppRecipientInput(
            name=contact.name,
            phone_number=contact.phone_number,
            imported_fields=_safe_imported_fields(contact.imported_fields),
        )
        existing = normalized_contacts.get(normalized)
        normalized_contacts[normalized] = (
            _merge_recipient_inputs(existing, sanitized) if existing else sanitized
        )
    if invalid_numbers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{len(invalid_numbers)} WhatsApp number(s) are invalid. "
                "Use 8 to 15 digits with an optional country code."
            ),
        )
    if not normalized_contacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add at least one valid WhatsApp number",
        )
    unnamed_numbers = [
        contact.phone_number
        for contact in normalized_contacts.values()
        if not _clean_name(contact.name)
    ]
    if unnamed_numbers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Every recipient needs a name for personalised messages. "
                f"Missing names for {len(unnamed_numbers)} contact(s)."
            ),
        )
    if any(len(_clean_name(contact.name) or "") > 100 for contact in normalized_contacts.values()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recipient names must be 100 characters or fewer",
        )
    return normalized_contacts


def _activate_recipient_models(
    *,
    session: AsyncSession,
    group: WhatsAppBroadcastGroupModel,
    existing_by_phone: dict[str, WhatsAppBroadcastRecipientModel],
    normalized_contacts: dict[str, WhatsAppRecipientInput],
    now: datetime,
    display_orders_by_phone: dict[str, int] | None = None,
) -> None:
    """Reactivate matching rows so their durable message checklist survives."""

    display_orders_by_phone = display_orders_by_phone or {}
    for normalized, contact in normalized_contacts.items():
        existing = existing_by_phone.get(normalized)
        if existing:
            if existing.suppressed_by_roster_resolution_id is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "A recipient in this import is currently marked as "
                        "replaced in a linked passport group. Restore that "
                        "replacement from the group before adding them back."
                    ),
                )
            existing.name = _clean_name(contact.name)
            existing.phone_number = contact.phone_number.strip()
            if contact.imported_fields:
                existing.imported_fields = contact.imported_fields
            existing.removed_at = None
            continue
        session.add(
            WhatsAppBroadcastRecipientModel(
                broadcast_group_id=group.id,
                agency_id=group.agency_id,
                name=_clean_name(contact.name),
                phone_number=contact.phone_number.strip(),
                normalized_phone_number=normalized,
                imported_fields=contact.imported_fields,
                display_order=display_orders_by_phone.get(normalized),
                removed_at=None,
                created_at=now,
            )
        )


def _parse_support_contacts(value: str) -> list[WhatsAppSupportContactInput]:
    try:
        parsed = json.loads(value or "[]")
        if not isinstance(parsed, list):
            raise TypeError
        contacts = [WhatsAppSupportContactInput(**item) for item in parsed]
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid customer support contact list",
        ) from exc
    if not contacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add at least one customer support contact",
        )
    normalized: dict[str, WhatsAppSupportContactInput] = {}
    for contact in contacts:
        phone = _normalize_phone(contact.phone_number)
        if not phone:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid WhatsApp number for support contact {contact.name}",
            )
        normalized.setdefault(phone, contact)
    if len(normalized) > 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add no more than three customer support contacts",
        )
    return list(normalized.values())


def _recipient_response(
    model: WhatsAppBroadcastRecipientModel,
    states: list[WhatsAppRecipientMessageStateModel] | None = None,
    resend_statuses: dict[str, str] | None = None,
) -> WhatsAppRecipientResponse:
    ordered_states = sorted(states or [], key=lambda state: state.message_type)
    latest_resend_statuses = resend_statuses or {}
    return WhatsAppRecipientResponse(
        id=model.id,
        name=model.name,
        phone_number=model.phone_number,
        normalized_phone_number=model.normalized_phone_number,
        imported_fields=dict(getattr(model, "imported_fields", {}) or {}),
        sent_message_types=[
            state.message_type
            for state in ordered_states
            if state.status in WHATSAPP_ACCEPTED_STATUSES
        ],
        message_statuses=[
            WhatsAppRecipientMessageStatusResponse(
                message_type=state.message_type,
                status=state.status,
                already_sent=state.status in WHATSAPP_ACCEPTED_STATUSES,
                send_suppressed=state.status in WHATSAPP_SUPPRESSED_STATUSES,
                latest_resend_status=latest_resend_statuses.get(state.message_type),
                resend_blocked=latest_resend_statuses.get(state.message_type)
                in WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES,
                submitted_at=state.submitted_at,
                status_updated_at=state.status_updated_at,
            )
            for state in ordered_states
        ],
    )


def _rejected_contact_response(
    model: WhatsAppBroadcastRejectedContactModel,
) -> WhatsAppRejectedContactResponse:
    return WhatsAppRejectedContactResponse(
        id=model.id,
        source_file_name=model.source_file_name,
        sheet_name=model.sheet_name,
        row_number=model.row_number,
        raw_name=model.raw_name,
        raw_phone_number=model.raw_phone_number,
        imported_fields=_safe_imported_fields(model.imported_fields),
        reason_code=_validated_rejection_code(model.reason_code),
        reason=model.reason,
        created_at=model.created_at,
    )


def _support_contact_response(
    model: WhatsAppBroadcastSupportContactModel,
) -> WhatsAppSupportContactResponse:
    return WhatsAppSupportContactResponse(
        id=model.id,
        name=model.name,
        phone_number=model.phone_number,
        normalized_phone_number=model.normalized_phone_number,
    )
