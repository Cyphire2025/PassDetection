"""WhatsApp broadcast management routes."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import math
import re
import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO
from itertools import islice
from typing import Any
from urllib.parse import urlparse
from zipfile import BadZipFile, ZipFile

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import PlainTextResponse
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.contact_normalization import (
    clean_whatsapp_name,
    normalize_whatsapp_phone,
)
from app.application.use_cases.whatsapp.message_templates import (
    AUTOMATED_NOTICE,
    GREETING,
    PASSPORT_INFORMATION_NOTICE,
    STATIC_TEMPLATE_HEADER,
    WhatsAppMessageType,
    default_message_content,
    format_support_contacts,
    passport_link_intro,
    render_message,
    template_header_parameters,
    template_parameters,
    validate_template_parameters,
)
from app.core.config.settings import get_settings
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSupportContactModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.dependencies.auth import require_role

router = APIRouter()
logger = logging.getLogger(__name__)

WHATSAPP_ROLES = [
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
    UserRole.AGENCY_STAFF,
]
PHONE_RE = re.compile(r"(?:\+|00)?\d[\d\s().-]{7,}\d")
WHATSAPP_ACCEPTED_STATUSES = frozenset({"submitted", "sent", "delivered", "read"})
WHATSAPP_ACCEPTED_STATUS_RANK = {
    "submitted": 0,
    "sent": 1,
    "delivered": 2,
    "read": 3,
}
WHATSAPP_WEBHOOK_STATUSES = frozenset({"sent", "delivered", "read", "failed"})
WHATSAPP_IN_PROGRESS_STATUSES = frozenset({"queued", "processing"})
WHATSAPP_UNCERTAIN_STATUSES = frozenset({"delivery_unknown"})
WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES = (
    WHATSAPP_IN_PROGRESS_STATUSES | WHATSAPP_UNCERTAIN_STATUSES
)
WHATSAPP_SUPPRESSED_STATUSES = (
    WHATSAPP_ACCEPTED_STATUSES | WHATSAPP_IN_PROGRESS_STATUSES | WHATSAPP_UNCERTAIN_STATUSES
)
WHATSAPP_STALE_CLAIM_AGE = timedelta(minutes=30)
MAX_WHATSAPP_RECIPIENTS = 500
MAX_WHATSAPP_CONTACT_FILE_BYTES = 5 * 1024 * 1024
MAX_WHATSAPP_EXCEL_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_WHATSAPP_EXCEL_ARCHIVE_MEMBERS = 2_000
MAX_WHATSAPP_EXCEL_COMPRESSION_RATIO = 250
MAX_WHATSAPP_EXCEL_HEADER_SCAN_ROWS = 25
WHATSAPP_UPLOAD_READ_CHUNK_BYTES = 1024 * 1024


class WhatsAppRecipientInput(BaseModel):
    name: str | None = None
    phone_number: str = Field(min_length=6, max_length=64)


class WhatsAppContactPreviewRecipient(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    phone_number: str = Field(min_length=9, max_length=16)


class WhatsAppContactPreviewResponse(BaseModel):
    recipient_count: int
    recipients: list[WhatsAppContactPreviewRecipient]


class WhatsAppSupportContactInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    phone_number: str = Field(min_length=6, max_length=64)


class WhatsAppRecipientResponse(BaseModel):
    id: uuid.UUID
    name: str | None
    phone_number: str
    normalized_phone_number: str
    sent_message_types: list[str] = Field(default_factory=list)
    message_statuses: list["WhatsAppRecipientMessageStatusResponse"] = Field(default_factory=list)


class WhatsAppRecipientMessageStatusResponse(BaseModel):
    message_type: str
    status: str
    already_sent: bool
    send_suppressed: bool
    latest_resend_status: str | None = None
    resend_blocked: bool = False
    submitted_at: datetime | None
    status_updated_at: datetime


class WhatsAppSupportContactResponse(BaseModel):
    id: uuid.UUID
    name: str
    phone_number: str
    normalized_phone_number: str


class WhatsAppBroadcastGroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    organizing_company_name: str
    recipient_count: int
    recipient_opt_in_confirmed: bool
    created_at: datetime
    updated_at: datetime


class WhatsAppBroadcastGroupDetailResponse(WhatsAppBroadcastGroupResponse):
    recipients: list[WhatsAppRecipientResponse]
    support_contacts: list[WhatsAppSupportContactResponse]


class WhatsAppSendRequest(BaseModel):
    message_type: str = Field(pattern="^(welcome|passport_link)$")
    passport_link: str | None = None
    message_content: str | None = Field(default=None, max_length=600)


class WhatsAppResendRequest(BaseModel):
    message_type: str = Field(pattern="^(welcome|passport_link)$")


class WhatsAppPreviewRequest(WhatsAppSendRequest):
    recipient_id: uuid.UUID | None = None


class WhatsAppPreviewResponse(BaseModel):
    message_type: str
    template_name: str
    recipient_id: uuid.UUID
    recipient_name: str
    recipient_count: int
    eligible_recipient_count: int
    already_sent_count: int
    in_progress_count: int
    uncertain_recipient_count: int
    message_content: str
    rendered_message: str
    header_parameter_values: list[str]
    parameter_values: list[str]


class WhatsAppSendResult(BaseModel):
    recipient_id: uuid.UUID
    phone_number: str
    status: str
    provider_message_id: str | None = None
    error_message: str | None = None


class WhatsAppSendResponse(BaseModel):
    batch_id: uuid.UUID | None = None
    queued: int = 0
    sent: int
    failed: int
    delivery_unknown: int = 0
    skipped_already_sent: int = 0
    skipped_in_progress: int = 0
    skipped_delivery_unknown: int = 0
    results: list[WhatsAppSendResult]


class WhatsAppWebhookAck(BaseModel):
    ok: bool = True
    processed_statuses: int = 0
    received_messages: int = 0


def _verify_meta_signature(raw_body: bytes, signature_header: str | None) -> bool:
    settings = get_settings()
    app_secret = (settings.whatsapp_app_secret or "").strip()
    if not app_secret:
        return not settings.is_production
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    received_signature = signature_header.removeprefix("sha256=").strip()
    expected_signature = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(received_signature, expected_signature)


def _iter_webhook_values(payload: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for entry in payload.get("entry", []) if isinstance(payload.get("entry"), list) else []:
        for change in (
            entry.get("changes", [])
            if isinstance(entry, dict) and isinstance(entry.get("changes"), list)
            else []
        ):
            value = change.get("value") if isinstance(change, dict) else None
            if isinstance(value, dict):
                values.append(value)
    return values


def _extract_status_error(status_payload: dict[str, Any]) -> str | None:
    errors = status_payload.get("errors")
    if not isinstance(errors, list) or not errors:
        return None
    first = errors[0]
    if not isinstance(first, dict):
        return None
    provider_code = first.get("code")
    code_suffix = (
        f" ({provider_code})"
        if isinstance(provider_code, (str, int)) and not isinstance(provider_code, bool)
        else ""
    )
    return (
        "WHATSAPP_PROVIDER_DELIVERY_FAILED: "
        f"Meta reported that this message was not delivered{code_suffix}"
    )


def _parse_provider_status_at(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(str(value)), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _is_stale_provider_status(
    current: datetime | None,
    incoming: datetime | None,
) -> bool:
    return bool(current and incoming and incoming < current)


def _apply_provider_status_to_delivery_state(
    delivery_state: WhatsAppRecipientMessageStateModel,
    *,
    provider_status: str,
    provider_status_at: datetime | None,
    now: datetime,
) -> None:
    """Apply Meta receipts without letting late events enable duplicate sends."""

    if _is_stale_provider_status(
        delivery_state.provider_status_at,
        provider_status_at,
    ):
        return
    if provider_status in WHATSAPP_ACCEPTED_STATUSES:
        current_rank = WHATSAPP_ACCEPTED_STATUS_RANK.get(delivery_state.status, -1)
        incoming_rank = WHATSAPP_ACCEPTED_STATUS_RANK[provider_status]
        if incoming_rank >= current_rank:
            delivery_state.status = provider_status
        delivery_state.submitted_at = delivery_state.submitted_at or now
        delivery_state.status_updated_at = now
        delivery_state.provider_status_at = provider_status_at or delivery_state.provider_status_at
        delivery_state.updated_at = now
    elif provider_status == "failed" and delivery_state.status not in {
        "delivered",
        "read",
    }:
        # A current-batch definitive failure is retryable until Meta reports
        # delivery. Delivered/read are monotonic and never move backwards.
        delivery_state.status = "failed"
        delivery_state.status_updated_at = now
        delivery_state.provider_status_at = provider_status_at or delivery_state.provider_status_at
        delivery_state.updated_at = now


def _apply_provider_status_to_message_log(
    log: WhatsAppMessageLogModel,
    *,
    provider_status: str,
    error_message: str | None,
    provider_status_at: datetime | None,
    now: datetime,
) -> None:
    """Keep message-log status consistent with the monotonic delivery ledger."""

    if _is_stale_provider_status(log.provider_status_at, provider_status_at):
        return
    if provider_status in WHATSAPP_ACCEPTED_STATUSES:
        current_rank = WHATSAPP_ACCEPTED_STATUS_RANK.get(log.status, -1)
        incoming_rank = WHATSAPP_ACCEPTED_STATUS_RANK[provider_status]
        if incoming_rank >= current_rank:
            log.status = provider_status
            log.status_updated_at = now
            log.provider_status_at = provider_status_at or log.provider_status_at
    elif provider_status == "failed" and log.status not in {"delivered", "read"}:
        log.status = "failed"
        log.status_updated_at = now
        log.provider_status_at = provider_status_at or log.provider_status_at
    if error_message:
        log.error_message = error_message


def _provider_status_state_predicates(
    log: WhatsAppMessageLogModel,
    *,
    provider_status: str,
) -> list[Any]:
    predicates = [
        WhatsAppRecipientMessageStateModel.recipient_id == log.recipient_id,
        WhatsAppRecipientMessageStateModel.message_type == log.message_type,
    ]
    if provider_status == "failed":
        # A failed receipt is only authoritative for the matching attempt. A
        # delayed failure from an older provider message must never release a
        # newer claim for retry.
        predicates.append(WhatsAppRecipientMessageStateModel.batch_id == log.batch_id)
    # Provider acceptance is authoritative for this recipient and message
    # type even if a later retry has already claimed the ledger. Omitting the
    # batch predicate promotes the ledger and suppresses that duplicate send
    # whenever the retry worker has not yet contacted Meta.
    return predicates


@router.get("/webhook", response_class=PlainTextResponse)
async def verify_whatsapp_webhook(
    mode: str | None = Query(default=None, alias="hub.mode"),
    verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> PlainTextResponse:
    settings = get_settings()
    expected_token = (settings.whatsapp_webhook_verify_token or "").strip()
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp webhook verify token is not configured",
        )
    if (
        mode == "subscribe"
        and challenge
        and hmac.compare_digest(verify_token or "", expected_token)
    ):
        return PlainTextResponse(challenge, status_code=status.HTTP_200_OK)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="WhatsApp webhook verification failed"
    )


@router.post("/webhook", response_model=WhatsAppWebhookAck)
async def receive_whatsapp_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppWebhookAck:
    raw_body = await request.body()
    if not _verify_meta_signature(raw_body, x_hub_signature_256):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid WhatsApp webhook signature"
        )
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid WhatsApp webhook JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid WhatsApp webhook payload"
        )

    provider_statuses: list[tuple[str, str, str | None, datetime | None]] = []
    received_messages = 0
    for value in _iter_webhook_values(payload):
        for status_payload in (
            value.get("statuses", []) if isinstance(value.get("statuses"), list) else []
        ):
            if not isinstance(status_payload, dict):
                continue
            provider_id = status_payload.get("id")
            provider_status = status_payload.get("status")
            if provider_id and provider_status:
                normalized_status = str(provider_status)[:32]
                if normalized_status not in WHATSAPP_WEBHOOK_STATUSES:
                    logger.warning(
                        "Ignoring unknown WhatsApp provider status %s",
                        normalized_status,
                    )
                    continue
                provider_statuses.append(
                    (
                        str(provider_id),
                        normalized_status,
                        _extract_status_error(status_payload),
                        _parse_provider_status_at(status_payload.get("timestamp")),
                    )
                )
        messages = value.get("messages")
        if isinstance(messages, list):
            received_messages += len(messages)

    processed_statuses = 0
    provider_statuses.sort(key=lambda item: item[3] or datetime.min.replace(tzinfo=UTC))
    for (
        provider_id,
        provider_status,
        error_message,
        provider_status_at,
    ) in provider_statuses:
        result = await session.execute(
            select(WhatsAppMessageLogModel).where(
                WhatsAppMessageLogModel.provider_message_id == provider_id
            )
        )
        for log in result.scalars().all():
            now = datetime.now(tz=UTC)
            _apply_provider_status_to_message_log(
                log,
                provider_status=provider_status,
                error_message=error_message,
                provider_status_at=provider_status_at,
                now=now,
            )
            if not getattr(log, "is_explicit_resend", False):
                state_result = await session.execute(
                    select(WhatsAppRecipientMessageStateModel)
                    .where(
                        *_provider_status_state_predicates(
                            log,
                            provider_status=provider_status,
                        )
                    )
                    .with_for_update()
                )
                delivery_state = state_result.scalar_one_or_none()
                if delivery_state:
                    _apply_provider_status_to_delivery_state(
                        delivery_state,
                        provider_status=provider_status,
                        provider_status_at=provider_status_at,
                        now=now,
                    )
            processed_statuses += 1
    if processed_statuses:
        await session.commit()

    if received_messages:
        logger.info("Received %s WhatsApp inbound message webhook event(s)", received_messages)
    return WhatsAppWebhookAck(
        processed_statuses=processed_statuses, received_messages=received_messages
    )


def _agency_filter(current_user: User) -> list[Any]:
    if current_user.role == UserRole.SUPER_ADMIN:
        return []
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="User is not assigned to an agency"
        )
    return [WhatsAppBroadcastGroupModel.agency_id == current_user.agency_id]


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


def _as_message_type(value: str) -> WhatsAppMessageType:
    return "welcome" if value == "welcome" else "passport_link"


def _resolve_message_content(
    message_type: WhatsAppMessageType,
    value: str | None,
    *,
    group_name: str,
) -> str:
    if value is None:
        return default_message_content(message_type, group_name=group_name)
    return value.strip()


def _resolve_send_message_content(
    message_type: WhatsAppMessageType,
    value: str | None,
    *,
    group_name: str,
) -> str:
    content = _resolve_message_content(message_type, value, group_name=group_name)
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Enter the editable message section before sending. "
                "Meta requires this template field to contain text."
            ),
        )
    return content


def _validate_passport_link(value: str | None, *, allow_placeholder: bool = False) -> str:
    link = (value or "").strip()
    if not link and allow_placeholder:
        return "[passport upload link]"
    parsed = urlparse(link)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Enter a valid passport upload link starting with http:// or https://",
        )
    return link


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


def _is_excel_phone_header(label: str) -> bool:
    tokens = set(label.split())
    if tokens.intersection({"phone", "mobile", "whatsapp", "telephone"}):
        return True
    return "contact" in tokens and (
        len(tokens) == 1 or bool(tokens.intersection({"number", "no", "phone", "mobile"}))
    )


def _is_excel_name_header(label: str) -> bool:
    tokens = set(label.split())
    if "name" in tokens:
        return True
    return label in {"client", "passenger", "recipient", "employee", "staff"}


def _excel_header_columns(
    row: tuple[Any, ...],
) -> tuple[list[int], list[int]]:
    labels = [_excel_header_label(cell) for cell in row]
    phone_columns = [
        index for index, label in enumerate(labels) if label and _is_excel_phone_header(label)
    ]
    name_columns = [
        index
        for index, label in enumerate(labels)
        if label and _is_excel_name_header(label) and index not in phone_columns
    ]
    return phone_columns, name_columns


def _find_excel_contact_header(
    rows: list[tuple[Any, ...]],
) -> tuple[int, list[int], list[int]] | None:
    best_match: tuple[tuple[int, int, int], int, list[int], list[int]] | None = None
    for row_index, row in enumerate(rows[:MAX_WHATSAPP_EXCEL_HEADER_SCAN_ROWS]):
        phone_columns, name_columns = _excel_header_columns(row)
        if not phone_columns:
            continue
        score = (
            1 if name_columns else 0,
            len(phone_columns) + len(name_columns),
            -row_index,
        )
        if best_match is None or score > best_match[0]:
            best_match = (
                score,
                row_index,
                phone_columns,
                name_columns,
            )
    if best_match is None:
        return None
    _, row_index, phone_columns, name_columns = best_match
    return row_index, phone_columns, name_columns


def _excel_name_from_row(
    row_values: list[Any],
    *,
    name_columns: list[int],
    phone_columns: list[int],
) -> str | None:
    for index in name_columns:
        if index >= len(row_values):
            continue
        name = _clean_name(row_values[index])
        if name:
            return name
    for index, value in enumerate(row_values):
        if index in phone_columns:
            continue
        name = _clean_name(value)
        if name and any(character.isalpha() for character in name) and not PHONE_RE.search(name):
            return name
    return None


def _parse_excel_contact_bytes(
    payload: bytes,
    *,
    filename: str,
) -> list[WhatsAppRecipientInput]:
    suffix = filename.rsplit(".", maxsplit=1)[-1].lower()
    suffix = f".{suffix}" if "." in filename else ".xlsx"
    if suffix not in {".xlsx", ".xlsm"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload an .xlsx or .xlsm contact file",
        )

    workbook = None
    try:
        _validate_excel_archive(payload)
        workbook = load_workbook(
            BytesIO(payload),
            read_only=True,
            data_only=True,
        )
        sheet = workbook.active
        rows = list(
            islice(
                sheet.iter_rows(values_only=True),
                (MAX_WHATSAPP_RECIPIENTS + MAX_WHATSAPP_EXCEL_HEADER_SCAN_ROWS + 1),
            )
        )
    except HTTPException:
        raise
    except (BadZipFile, InvalidFileException, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded Excel contact file could not be read",
        ) from exc
    except Exception as exc:
        logger.error(
            "whatsapp_excel_contact_file_read_failed",
            extra={"error_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded Excel contact file could not be read",
        ) from exc
    finally:
        if workbook is not None:
            workbook.close()

    if not rows:
        return []

    header_match = _find_excel_contact_header(rows)
    if header_match:
        header_row_index, phone_columns, name_columns = header_match
        data_rows = rows[header_row_index + 1 :]
    else:
        phone_columns = []
        name_columns = []
        data_rows = rows
    if len(data_rows) > MAX_WHATSAPP_RECIPIENTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"The Excel contact file can contain at most {MAX_WHATSAPP_RECIPIENTS} data rows"
            ),
        )

    contacts: list[WhatsAppRecipientInput] = []
    seen: set[str] = set()
    invalid_phone_count = 0
    for row in data_rows:
        row_values = list(row)
        candidates: list[tuple[str | None, str]] = []
        if phone_columns:
            name = _excel_name_from_row(
                row_values,
                name_columns=name_columns,
                phone_columns=phone_columns,
            )
            for index in phone_columns:
                if index >= len(row_values):
                    continue
                phone = _excel_cell_text(row_values[index])
                if phone:
                    candidates.append((name, phone))
        else:
            row_text = " ".join(text for cell in row_values if (text := _excel_cell_text(cell)))
            name = _excel_name_from_row(
                row_values,
                name_columns=[],
                phone_columns=[],
            )
            for match in PHONE_RE.findall(row_text):
                candidates.append((name, match))

        for name, phone in candidates:
            normalized = _normalize_phone(phone)
            if not normalized:
                invalid_phone_count += 1
            elif normalized not in seen:
                seen.add(normalized)
                contacts.append(WhatsAppRecipientInput(name=name, phone_number=phone))
    if invalid_phone_count:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{invalid_phone_count} WhatsApp number(s) in the Excel file "
                "are invalid. Use 8 to 15 digits with an optional country code."
            ),
        )
    return contacts


async def _parse_excel_contacts(
    upload: UploadFile,
) -> list[WhatsAppRecipientInput]:
    payload = bytearray()
    while chunk := await upload.read(WHATSAPP_UPLOAD_READ_CHUNK_BYTES):
        payload.extend(chunk)
        if len(payload) > MAX_WHATSAPP_CONTACT_FILE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    "The Excel contact file must be "
                    f"{MAX_WHATSAPP_CONTACT_FILE_BYTES // (1024 * 1024)} MB or smaller"
                ),
            )
    filename = upload.filename or "contacts.xlsx"
    return await asyncio.to_thread(
        _parse_excel_contact_bytes,
        bytes(payload),
        filename=filename,
    )


def _excel_contact_preview_response(
    contacts: list[WhatsAppRecipientInput],
) -> WhatsAppContactPreviewResponse:
    if not contacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No recipients were found. Include name and phone/WhatsApp "
                "columns with at least one contact."
            ),
        )

    normalized_contacts = _normalized_recipient_inputs(contacts)
    recipients = [
        WhatsAppContactPreviewRecipient(
            name=_clean_required_name(contact.name, "Recipient name"),
            phone_number=normalized_phone,
        )
        for normalized_phone, contact in normalized_contacts.items()
    ]
    return WhatsAppContactPreviewResponse(
        recipient_count=len(recipients),
        recipients=recipients,
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


def _normalized_recipient_inputs(
    contacts: list[WhatsAppRecipientInput],
) -> dict[str, WhatsAppRecipientInput]:
    normalized_contacts: dict[str, WhatsAppRecipientInput] = {}
    invalid_numbers: list[str] = []
    for contact in contacts:
        normalized = _normalize_phone(contact.phone_number)
        if not normalized:
            invalid_numbers.append(contact.phone_number)
        elif normalized not in normalized_contacts:
            normalized_contacts[normalized] = contact
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
) -> None:
    """Reactivate matching rows so their durable message checklist survives."""

    for normalized, contact in normalized_contacts.items():
        existing = existing_by_phone.get(normalized)
        if existing:
            existing.name = _clean_name(contact.name)
            existing.phone_number = contact.phone_number.strip()
            existing.removed_at = None
            continue
        session.add(
            WhatsAppBroadcastRecipientModel(
                broadcast_group_id=group.id,
                agency_id=group.agency_id,
                name=_clean_name(contact.name),
                phone_number=contact.phone_number.strip(),
                normalized_phone_number=normalized,
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


def _support_contact_response(
    model: WhatsAppBroadcastSupportContactModel,
) -> WhatsAppSupportContactResponse:
    return WhatsAppSupportContactResponse(
        id=model.id,
        name=model.name,
        phone_number=model.phone_number,
        normalized_phone_number=model.normalized_phone_number,
    )


async def _support_contacts_for_group(
    session: AsyncSession,
    group_id: uuid.UUID,
) -> list[WhatsAppBroadcastSupportContactModel]:
    result = await session.execute(
        select(WhatsAppBroadcastSupportContactModel)
        .where(WhatsAppBroadcastSupportContactModel.broadcast_group_id == group_id)
        .order_by(
            WhatsAppBroadcastSupportContactModel.sort_order.asc(),
            WhatsAppBroadcastSupportContactModel.created_at.asc(),
        )
    )
    return list(result.scalars().all())


async def _group_detail(
    session: AsyncSession, group: WhatsAppBroadcastGroupModel
) -> WhatsAppBroadcastGroupDetailResponse:
    recipients_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id,
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        )
        .order_by(
            WhatsAppBroadcastRecipientModel.name.asc().nullslast(),
            WhatsAppBroadcastRecipientModel.created_at.asc(),
        )
    )
    recipients = list(recipients_result.scalars().all())
    states_by_recipient: dict[uuid.UUID, list[WhatsAppRecipientMessageStateModel]] = {}
    resend_statuses_by_recipient: dict[uuid.UUID, dict[str, str]] = {}
    if recipients:
        states_result = await session.execute(
            select(WhatsAppRecipientMessageStateModel)
            .where(
                WhatsAppRecipientMessageStateModel.recipient_id.in_(
                    [recipient.id for recipient in recipients]
                )
            )
            .order_by(WhatsAppRecipientMessageStateModel.message_type.asc())
        )
        for state_model in states_result.scalars().all():
            states_by_recipient.setdefault(state_model.recipient_id, []).append(state_model)
        resend_result = await session.execute(
            select(WhatsAppMessageLogModel)
            .where(
                WhatsAppMessageLogModel.recipient_id.in_(
                    [recipient.id for recipient in recipients]
                ),
                WhatsAppMessageLogModel.is_explicit_resend.is_(True),
            )
            .order_by(WhatsAppMessageLogModel.created_at.desc())
        )
        for resend_log in resend_result.scalars().all():
            recipient_statuses = resend_statuses_by_recipient.setdefault(
                resend_log.recipient_id,
                {},
            )
            recipient_statuses.setdefault(resend_log.message_type, resend_log.status)
    support_contacts = await _support_contacts_for_group(session, group.id)
    return WhatsAppBroadcastGroupDetailResponse(
        id=group.id,
        name=group.name,
        organizing_company_name=group.organizing_company_name,
        recipient_count=len(recipients),
        recipient_opt_in_confirmed=group.recipient_opt_in_confirmed_at is not None,
        created_at=group.created_at,
        updated_at=group.updated_at,
        recipients=[
            _recipient_response(
                recipient,
                states_by_recipient.get(recipient.id, []),
                resend_statuses_by_recipient.get(recipient.id, {}),
            )
            for recipient in recipients
        ],
        support_contacts=[_support_contact_response(contact) for contact in support_contacts],
    )


async def _group_recipients(
    session: AsyncSession,
    group_id: uuid.UUID,
) -> list[WhatsAppBroadcastRecipientModel]:
    result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group_id,
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        )
        .order_by(
            WhatsAppBroadcastRecipientModel.name.asc().nullslast(),
            WhatsAppBroadcastRecipientModel.created_at.asc(),
        )
    )
    return list(result.scalars().all())


async def _recipient_delivery_counts(
    session: AsyncSession,
    *,
    recipients: list[WhatsAppBroadcastRecipientModel],
    message_type: str,
) -> tuple[int, int, int, int]:
    if not recipients:
        return 0, 0, 0, 0
    states_result = await session.execute(
        select(
            WhatsAppRecipientMessageStateModel.recipient_id,
            WhatsAppRecipientMessageStateModel.status,
        ).where(
            WhatsAppRecipientMessageStateModel.recipient_id.in_(
                [recipient.id for recipient in recipients]
            ),
            WhatsAppRecipientMessageStateModel.message_type == message_type,
        )
    )
    statuses = {recipient_id: state_status for recipient_id, state_status in states_result.all()}
    already_sent = sum(
        1 for state_status in statuses.values() if state_status in WHATSAPP_ACCEPTED_STATUSES
    )
    in_progress = sum(
        1 for state_status in statuses.values() if state_status in WHATSAPP_IN_PROGRESS_STATUSES
    )
    uncertain = sum(
        1 for state_status in statuses.values() if state_status in WHATSAPP_UNCERTAIN_STATUSES
    )
    return (
        len(recipients) - already_sent - in_progress - uncertain,
        already_sent,
        in_progress,
        uncertain,
    )


def _message_values(
    *,
    group: WhatsAppBroadcastGroupModel,
    recipient: WhatsAppBroadcastRecipientModel,
    support_contacts: list[WhatsAppBroadcastSupportContactModel],
    body: WhatsAppSendRequest,
    preview: bool = False,
) -> tuple[WhatsAppMessageType, str, str, str, list[str], list[str]]:
    message_type = _as_message_type(body.message_type)
    message_content = _resolve_message_content(
        message_type,
        body.message_content,
        group_name=group.name,
    )
    passport_link = (
        _validate_passport_link(body.passport_link, allow_placeholder=preview)
        if message_type == "passport_link"
        else None
    )
    recipient_name = _clean_name(recipient.name) or "Guest"
    support_block = format_support_contacts(
        [(contact.name, contact.phone_number) for contact in support_contacts]
    )
    rendered = render_message(
        message_type=message_type,
        group_name=group.name,
        support_contacts=support_block,
        message_content=message_content,
        passport_link=passport_link,
    )
    header_parameters = template_header_parameters(
        message_type=message_type,
    )
    parameters = template_parameters(
        message_type=message_type,
        group_name=group.name,
        support_contacts=support_block,
        message_content=message_content,
        passport_link=passport_link,
    )
    return message_type, message_content, recipient_name, rendered, header_parameters, parameters


def _split_rendered_support_block(rendered_body: str) -> tuple[str, str]:
    assistance_marker = "\n\nFor assistance, please contact:\n"
    footer = "\n\nRegards,\nTeam Global Connect Travels"
    before_support, marker, support_and_footer = rendered_body.rpartition(assistance_marker)
    if not marker:
        raise ValueError("The saved WhatsApp message has an unknown assistance layout")
    support_contacts, footer_marker, trailing = support_and_footer.rpartition(footer)
    if not footer_marker or trailing or not support_contacts.strip():
        raise ValueError("The saved WhatsApp message has an unknown footer layout")
    return before_support, support_contacts


def _decode_legacy_template_snapshot(
    *,
    message_type: WhatsAppMessageType,
    rendered_message: str | None,
) -> tuple[list[str], list[str]]:
    """Decode only messages that exactly match our deterministic approved layout."""

    if not rendered_message:
        raise ValueError("The saved WhatsApp message has no reusable content")
    prefix = f"{STATIC_TEMPLATE_HEADER}\n\n{GREETING}\n\n"
    if not rendered_message.startswith(prefix):
        raise ValueError("The saved WhatsApp message has an unknown header layout")
    before_support, support_contacts = _split_rendered_support_block(
        rendered_message[len(prefix) :]
    )

    if message_type == "welcome":
        notice_suffix = f"\n\n{AUTOMATED_NOTICE}"
        if not before_support.endswith(notice_suffix):
            raise ValueError("The saved welcome message has an unknown notice layout")
        message_content = before_support[: -len(notice_suffix)]
        header_parameters: list[str] = []
        parameters = [message_content, support_contacts]
        reconstructed = render_message(
            message_type=message_type,
            group_name="",
            support_contacts=support_contacts,
            message_content=message_content,
        )
    else:
        notice_suffix = f"\n\n{PASSPORT_INFORMATION_NOTICE}"
        if not before_support.endswith(notice_suffix):
            raise ValueError("The saved passport message has an unknown notice layout")
        variable_area = before_support[: -len(notice_suffix)]
        try:
            intro, passport_link, message_content = variable_area.split("\n\n", 2)
        except ValueError as exc:
            raise ValueError(
                "The saved passport message does not contain the approved variables"
            ) from exc
        intro_prefix = (
            "Please use the secure link below to submit your travel documents required for "
            "your trip to "
        )
        if (
            not intro.startswith(intro_prefix)
            or not intro.endswith(".")
            or not intro[len(intro_prefix) : -1].strip()
        ):
            raise ValueError("The saved passport message has an unknown trip introduction")
        original_group_name = intro[len(intro_prefix) : -1]
        parsed_link = urlparse(passport_link)
        if parsed_link.scheme not in {"http", "https"} or not parsed_link.netloc:
            raise ValueError("The saved passport message has an invalid upload link")
        if intro != passport_link_intro(original_group_name):
            raise ValueError("The saved passport message trip introduction is inconsistent")
        header_parameters = []
        parameters = [
            intro,
            passport_link,
            message_content,
            support_contacts,
        ]
        reconstructed = render_message(
            message_type=message_type,
            group_name=original_group_name,
            support_contacts=support_contacts,
            message_content=message_content,
            passport_link=passport_link,
        )

    validate_template_parameters(
        message_type=message_type,
        header_parameters=header_parameters,
        body_parameters=parameters,
    )
    if reconstructed != rendered_message:
        raise ValueError("The saved WhatsApp message could not be verified exactly")
    return header_parameters, parameters


def _template_snapshot_from_log(
    log: WhatsAppMessageLogModel,
) -> tuple[list[str], list[str]]:
    if log.message_type not in {"welcome", "passport_link"}:
        raise ValueError("The saved WhatsApp message type cannot be resent")
    message_type = _as_message_type(log.message_type)
    saved_header = log.header_parameter_values
    saved_body = log.template_parameter_values
    if saved_header is None and saved_body is None:
        return _decode_legacy_template_snapshot(
            message_type=message_type,
            rendered_message=log.rendered_message,
        )
    if not isinstance(saved_header, list) or not isinstance(saved_body, list):
        raise ValueError("The saved WhatsApp message parameters are incomplete")
    if any(not isinstance(value, str) for value in [*saved_header, *saved_body]):
        raise ValueError("The saved WhatsApp message parameters are invalid")
    header_parameters = list(saved_header)
    parameters = list(saved_body)
    validate_template_parameters(
        message_type=message_type,
        header_parameters=header_parameters,
        body_parameters=parameters,
    )
    return header_parameters, parameters


@router.post(
    "/contacts/preview",
    response_model=WhatsAppContactPreviewResponse,
)
async def preview_excel_contacts(
    contacts_file: UploadFile = File(...),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
) -> WhatsAppContactPreviewResponse:
    del current_user
    contacts = await _parse_excel_contacts(contacts_file)
    return _excel_contact_preview_response(contacts)


@router.get("/groups", response_model=list[WhatsAppBroadcastGroupResponse])
async def list_broadcast_groups(
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[WhatsAppBroadcastGroupResponse]:
    result = await session.execute(
        select(
            WhatsAppBroadcastGroupModel,
            func.count(WhatsAppBroadcastRecipientModel.id).label("recipient_count"),
        )
        .outerjoin(
            WhatsAppBroadcastRecipientModel,
            and_(
                WhatsAppBroadcastRecipientModel.broadcast_group_id
                == WhatsAppBroadcastGroupModel.id,
                WhatsAppBroadcastRecipientModel.removed_at.is_(None),
            ),
        )
        .where(*_agency_filter(current_user))
        .group_by(WhatsAppBroadcastGroupModel.id)
        .order_by(WhatsAppBroadcastGroupModel.created_at.desc())
    )
    return [
        WhatsAppBroadcastGroupResponse(
            id=group.id,
            name=group.name,
            organizing_company_name=group.organizing_company_name,
            recipient_count=count,
            recipient_opt_in_confirmed=group.recipient_opt_in_confirmed_at is not None,
            created_at=group.created_at,
            updated_at=group.updated_at,
        )
        for group, count in result.all()
    ]


@router.get("/groups/{group_id}", response_model=WhatsAppBroadcastGroupDetailResponse)
async def get_broadcast_group(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBroadcastGroupDetailResponse:
    result = await session.execute(
        select(WhatsAppBroadcastGroupModel).where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="WhatsApp broadcast group not found"
        )
    return await _group_detail(session, group)


@router.post("/groups/{group_id}/preview", response_model=WhatsAppPreviewResponse)
async def preview_broadcast_message(
    group_id: uuid.UUID,
    body: WhatsAppPreviewRequest,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppPreviewResponse:
    result = await session.execute(
        select(WhatsAppBroadcastGroupModel).where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )

    recipients = await _group_recipients(session, group.id)
    if not recipients:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This WhatsApp list has no recipients",
        )
    recipient = recipients[0]
    if body.recipient_id:
        selected = next((item for item in recipients if item.id == body.recipient_id), None)
        if not selected:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Preview recipient not found in this WhatsApp list",
            )
        recipient = selected

    support_contacts = await _support_contacts_for_group(session, group.id)
    message_type, message_content, recipient_name, rendered, header_parameters, parameters = (
        _message_values(
            group=group,
            recipient=recipient,
            support_contacts=support_contacts,
            body=body,
            preview=True,
        )
    )
    (
        eligible_count,
        already_sent_count,
        in_progress_count,
        uncertain_count,
    ) = await _recipient_delivery_counts(
        session,
        recipients=recipients,
        message_type=message_type,
    )
    settings = get_settings()
    template_name = (
        settings.whatsapp_welcome_template_name
        if message_type == "welcome"
        else settings.whatsapp_passport_link_template_name
    )
    return WhatsAppPreviewResponse(
        message_type=message_type,
        template_name=template_name,
        recipient_id=recipient.id,
        recipient_name=recipient_name,
        recipient_count=len(recipients),
        eligible_recipient_count=eligible_count,
        already_sent_count=already_sent_count,
        in_progress_count=in_progress_count,
        uncertain_recipient_count=uncertain_count,
        message_content=message_content,
        rendered_message=rendered,
        header_parameter_values=header_parameters,
        parameter_values=parameters,
    )


@router.post(
    "/groups",
    response_model=WhatsAppBroadcastGroupDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_broadcast_group(
    name: str = Form(...),
    organizing_company_name: str | None = Form(None),
    contacts_json: str = Form("[]"),
    support_contacts_json: str = Form("[]"),
    recipient_opt_in_confirmed: bool = Form(...),
    contacts_file: UploadFile | None = File(None),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBroadcastGroupDetailResponse:
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="User is not assigned to an agency"
        )
    group_name = name.strip()
    if not group_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Group name is required"
        )
    if len(group_name) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Group name must be 100 characters or fewer",
        )
    company_name = _clean_name(organizing_company_name) or ""
    if len(company_name) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organising company name must be 100 characters or fewer",
        )
    if not recipient_opt_in_confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirm recipient WhatsApp opt-in before saving this list",
        )

    try:
        manual_contacts = [
            WhatsAppRecipientInput(**item) for item in json.loads(contacts_json or "[]")
        ]
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid manual contact list"
        ) from exc

    try:
        support_contacts = [
            WhatsAppSupportContactInput(**item)
            for item in json.loads(support_contacts_json or "[]")
        ]
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid customer support contact list",
        ) from exc
    if not support_contacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add at least one customer support contact",
        )

    excel_contacts = await _parse_excel_contacts(contacts_file) if contacts_file else []
    contacts = manual_contacts + excel_contacts
    normalized_contacts = _normalized_recipient_inputs(contacts)
    if len(normalized_contacts) > MAX_WHATSAPP_RECIPIENTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"A WhatsApp list can contain at most {MAX_WHATSAPP_RECIPIENTS} recipients"),
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
    long_names = [
        contact.phone_number
        for contact in normalized_contacts.values()
        if len(_clean_name(contact.name) or "") > 100
    ]
    if long_names:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recipient names must be 100 characters or fewer",
        )

    normalized_support_contacts: dict[str, WhatsAppSupportContactInput] = {}
    for support_contact in support_contacts:
        normalized = _normalize_phone(support_contact.phone_number)
        if not normalized:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid WhatsApp number for support contact {support_contact.name}",
            )
        if normalized not in normalized_support_contacts:
            normalized_support_contacts[normalized] = support_contact
    if len(normalized_support_contacts) > 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add no more than three customer support contacts",
        )

    group = WhatsAppBroadcastGroupModel(
        agency_id=current_user.agency_id,
        name=group_name,
        organizing_company_name=company_name,
        recipient_opt_in_confirmed_at=datetime.now(tz=UTC),
        created_by_user_id=current_user.id,
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )
    session.add(group)
    await session.flush()
    for normalized, contact in normalized_contacts.items():
        session.add(
            WhatsAppBroadcastRecipientModel(
                broadcast_group_id=group.id,
                agency_id=current_user.agency_id,
                name=_clean_name(contact.name),
                phone_number=contact.phone_number.strip(),
                normalized_phone_number=normalized,
                created_at=datetime.now(tz=UTC),
            )
        )
    for sort_order, (normalized, support_contact) in enumerate(normalized_support_contacts.items()):
        session.add(
            WhatsAppBroadcastSupportContactModel(
                broadcast_group_id=group.id,
                agency_id=current_user.agency_id,
                name=_clean_required_name(support_contact.name, "Customer support name"),
                phone_number=support_contact.phone_number.strip(),
                normalized_phone_number=normalized,
                sort_order=sort_order,
                created_at=datetime.now(tz=UTC),
            )
        )
    await session.flush()
    return await _group_detail(session, group)


@router.patch("/groups/{group_id}", response_model=WhatsAppBroadcastGroupDetailResponse)
async def update_broadcast_group(
    group_id: uuid.UUID,
    name: str | None = Form(None),
    organizing_company_name: str | None = Form(None),
    support_contacts_json: str | None = Form(None),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBroadcastGroupDetailResponse:
    result = await session.execute(
        select(WhatsAppBroadcastGroupModel)
        .where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
        .with_for_update()
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )

    if name is not None:
        group_name = name.strip()
        if not group_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Group name is required",
            )
        if len(group_name) > 100:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Group name must be 100 characters or fewer",
            )
        group.name = group_name

    if organizing_company_name is not None:
        company_name = _clean_required_name(
            organizing_company_name,
            "Organising company name",
        )
        if len(company_name) > 100:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Organising company name must be 100 characters or fewer",
            )
        group.organizing_company_name = company_name

    if support_contacts_json is not None:
        support_contacts = _parse_support_contacts(support_contacts_json)
        await session.execute(
            delete(WhatsAppBroadcastSupportContactModel).where(
                WhatsAppBroadcastSupportContactModel.broadcast_group_id == group.id
            )
        )
        await session.flush()
        for sort_order, support_contact in enumerate(support_contacts):
            normalized = _normalize_phone(support_contact.phone_number)
            if not normalized:  # Defensive; _parse_support_contacts already validates.
                continue
            session.add(
                WhatsAppBroadcastSupportContactModel(
                    broadcast_group_id=group.id,
                    agency_id=group.agency_id,
                    name=_clean_required_name(
                        support_contact.name,
                        "Customer support name",
                    ),
                    phone_number=support_contact.phone_number.strip(),
                    normalized_phone_number=normalized,
                    sort_order=sort_order,
                    created_at=datetime.now(tz=UTC),
                )
            )

    group.updated_at = datetime.now(tz=UTC)
    await session.flush()
    return await _group_detail(session, group)


@router.post(
    "/groups/{group_id}/recipients",
    response_model=WhatsAppBroadcastGroupDetailResponse,
)
async def add_broadcast_recipients(
    group_id: uuid.UUID,
    contacts_json: str = Form("[]"),
    recipient_opt_in_confirmed: bool = Form(...),
    contacts_file: UploadFile | None = File(None),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBroadcastGroupDetailResponse:
    if not recipient_opt_in_confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirm recipient WhatsApp opt-in before adding contacts",
        )
    group_result = await session.execute(
        select(WhatsAppBroadcastGroupModel)
        .where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
        .with_for_update()
    )
    group = group_result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )

    manual_contacts = _parse_manual_contacts(contacts_json)
    excel_contacts = await _parse_excel_contacts(contacts_file) if contacts_file else []
    normalized_contacts = _normalized_recipient_inputs(manual_contacts + excel_contacts)

    existing_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel).where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id
        )
    )
    existing_by_phone = {
        recipient.normalized_phone_number: recipient
        for recipient in existing_result.scalars().all()
    }
    active_count = sum(
        1 for recipient in existing_by_phone.values() if recipient.removed_at is None
    )
    activating_count = sum(
        1
        for normalized in normalized_contacts
        if normalized not in existing_by_phone
        or existing_by_phone[normalized].removed_at is not None
    )
    if active_count + activating_count > MAX_WHATSAPP_RECIPIENTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A WhatsApp list can contain at most {MAX_WHATSAPP_RECIPIENTS} recipients",
        )

    now = datetime.now(tz=UTC)
    _activate_recipient_models(
        session=session,
        group=group,
        existing_by_phone=existing_by_phone,
        normalized_contacts=normalized_contacts,
        now=now,
    )

    group.recipient_opt_in_confirmed_at = group.recipient_opt_in_confirmed_at or now
    group.updated_at = now
    await session.flush()
    return await _group_detail(session, group)


@router.delete(
    "/groups/{group_id}/recipients/{recipient_id}",
    status_code=status.HTTP_200_OK,
)
async def remove_broadcast_recipient(
    group_id: uuid.UUID,
    recipient_id: uuid.UUID,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, bool]:
    result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .join(
            WhatsAppBroadcastGroupModel,
            WhatsAppBroadcastGroupModel.id == WhatsAppBroadcastRecipientModel.broadcast_group_id,
        )
        .where(
            WhatsAppBroadcastRecipientModel.id == recipient_id,
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group_id,
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
            *_agency_filter(current_user),
        )
        .with_for_update()
    )
    recipient = result.scalar_one_or_none()
    if not recipient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp recipient not found",
        )

    now = datetime.now(tz=UTC)
    recipient.removed_at = now
    await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.recipient_id == recipient.id,
            WhatsAppMessageLogModel.status == "queued",
        )
        .values(
            status="failed",
            status_updated_at=now,
            error_message="Recipient removed from WhatsApp broadcast before delivery",
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(WhatsAppRecipientMessageStateModel)
        .where(
            WhatsAppRecipientMessageStateModel.recipient_id == recipient.id,
            WhatsAppRecipientMessageStateModel.status == "queued",
        )
        .values(
            status="failed",
            batch_id=None,
            status_updated_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(WhatsAppBroadcastGroupModel)
        .where(WhatsAppBroadcastGroupModel.id == group_id)
        .values(updated_at=now)
    )
    return {"deleted": True}


@router.post(
    "/groups/{group_id}/recipients/{recipient_id}/resend",
    response_model=WhatsAppSendResponse,
)
async def resend_recipient_message(
    group_id: uuid.UUID,
    recipient_id: uuid.UUID,
    body: WhatsAppResendRequest,
    request: Request,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppSendResponse:
    group_result = await session.execute(
        select(WhatsAppBroadcastGroupModel)
        .where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
        .with_for_update()
    )
    group = group_result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )
    if group.recipient_opt_in_confirmed_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recipient WhatsApp opt-in has not been confirmed for this list",
        )

    recipient_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(
            WhatsAppBroadcastRecipientModel.id == recipient_id,
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id,
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        )
        .with_for_update()
    )
    recipient = recipient_result.scalar_one_or_none()
    if not recipient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp recipient not found",
        )

    message_type = _as_message_type(body.message_type)
    state_result = await session.execute(
        select(WhatsAppRecipientMessageStateModel)
        .where(
            WhatsAppRecipientMessageStateModel.recipient_id == recipient.id,
            WhatsAppRecipientMessageStateModel.message_type == message_type,
        )
        .with_for_update()
    )
    delivery_state = state_result.scalar_one_or_none()
    if not delivery_state or delivery_state.status not in WHATSAPP_ACCEPTED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Only a successfully submitted WhatsApp message can be resent. "
                "Use the normal send action for an unsent or failed message."
            ),
        )

    now = datetime.now(tz=UTC)
    stale_cutoff = now - WHATSAPP_STALE_CLAIM_AGE
    await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.recipient_id == recipient.id,
            WhatsAppMessageLogModel.message_type == message_type,
            WhatsAppMessageLogModel.is_explicit_resend.is_(True),
            WhatsAppMessageLogModel.status == "queued",
            WhatsAppMessageLogModel.status_updated_at < stale_cutoff,
        )
        .values(
            status="failed",
            status_updated_at=now,
            error_message="Explicit resend claim expired before provider submission",
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.recipient_id == recipient.id,
            WhatsAppMessageLogModel.message_type == message_type,
            WhatsAppMessageLogModel.is_explicit_resend.is_(True),
            WhatsAppMessageLogModel.status == "processing",
            WhatsAppMessageLogModel.status_updated_at < stale_cutoff,
        )
        .values(
            status="delivery_unknown",
            status_updated_at=now,
            error_message=(
                "Explicit resend outcome is unknown after a worker interruption; "
                "another resend is blocked"
            ),
        )
        .execution_options(synchronize_session=False)
    )
    active_resend_result = await session.execute(
        select(WhatsAppMessageLogModel).where(
            WhatsAppMessageLogModel.recipient_id == recipient.id,
            WhatsAppMessageLogModel.message_type == message_type,
            WhatsAppMessageLogModel.is_explicit_resend.is_(True),
            WhatsAppMessageLogModel.status.in_(
                WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES
            ),
        )
    )
    active_resend = active_resend_result.scalar_one_or_none()
    if active_resend:
        detail = (
            "The previous resend has an unknown delivery outcome. "
            "Verify it with the recipient before attempting another resend."
            if active_resend.status == "delivery_unknown"
            else "A resend of this message is already in progress for this recipient."
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        )

    source_result = await session.execute(
        select(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.broadcast_group_id == group.id,
            WhatsAppMessageLogModel.recipient_id == recipient.id,
            WhatsAppMessageLogModel.message_type == message_type,
            WhatsAppMessageLogModel.status.in_(WHATSAPP_ACCEPTED_STATUSES),
        )
        .order_by(
            WhatsAppMessageLogModel.status_updated_at.desc(),
            WhatsAppMessageLogModel.created_at.desc(),
        )
        .limit(1)
    )
    source_log = source_result.scalar_one_or_none()
    if not source_log:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The previously submitted WhatsApp message could not be found",
        )
    try:
        header_parameters, parameters = _template_snapshot_from_log(source_log)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This older WhatsApp message cannot be safely reconstructed for resend. "
                "Send a fresh message from the normal preview instead."
            ),
        ) from exc

    settings = get_settings()
    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp Cloud API credentials are incomplete",
        )
    configured_template_name = (
        settings.whatsapp_welcome_template_name
        if message_type == "welcome"
        else settings.whatsapp_passport_link_template_name
    )
    template_name = (source_log.template_name or configured_template_name).strip()
    if not template_name:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"WhatsApp {message_type} template name is not configured",
        )

    batch_id = uuid.uuid4()
    resend_log = WhatsAppMessageLogModel(
        batch_id=batch_id,
        broadcast_group_id=group.id,
        recipient_id=recipient.id,
        agency_id=recipient.agency_id,
        message_type=message_type,
        status="queued",
        status_updated_at=now,
        provider_message_id=None,
        error_message=None,
        template_name=template_name,
        rendered_message=source_log.rendered_message,
        header_parameter_values=header_parameters,
        template_parameter_values=parameters,
        is_explicit_resend=True,
        created_at=now,
    )
    session.add(resend_log)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A resend of this message is already active for this recipient.",
        ) from exc

    await AuditLogRepository(session).record(
        action="whatsapp_recipient_message_resend_requested",
        entity_type="whatsapp_broadcast_recipient",
        entity_id=str(recipient.id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=request.client.host if request.client else None,
        metadata={
            "broadcast_group_id": str(group.id),
            "message_type": message_type,
            "source_message_log_id": str(source_log.id),
            "resend_batch_id": str(batch_id),
            "source_status": source_log.status,
        },
    )
    await session.commit()

    from app.infrastructure.whatsapp.tasks import process_whatsapp_broadcast

    try:
        process_whatsapp_broadcast.apply_async(
            kwargs={
                "batch_id": str(batch_id),
                "message_type": message_type,
                "message_content": parameters[0] if message_type == "welcome" else parameters[2],
                "passport_link": parameters[1] if message_type == "passport_link" else None,
            },
            queue="whatsapp",
        )
    except Exception as exc:  # noqa: BLE001 - broker failure is surfaced and persisted.
        logger.error(
            "whatsapp_resend_queue_unavailable",
            extra={
                "batch_id": str(batch_id),
                "recipient_id": str(recipient.id),
                "error_type": type(exc).__name__,
            },
        )
        resend_log.status = "failed"
        resend_log.status_updated_at = datetime.now(tz=UTC)
        resend_log.error_message = (
            "WHATSAPP_QUEUE_UNAVAILABLE: WhatsApp delivery queue is temporarily unavailable"
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp delivery queue is unavailable",
        ) from exc

    return WhatsAppSendResponse(
        batch_id=batch_id,
        queued=1,
        sent=0,
        failed=0,
        results=[
            WhatsAppSendResult(
                recipient_id=recipient.id,
                phone_number=recipient.normalized_phone_number,
                status="queued",
            )
        ],
    )


@router.delete("/groups/{group_id}", status_code=status.HTTP_200_OK)
async def delete_broadcast_group(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, bool]:
    result = await session.execute(
        select(WhatsAppBroadcastGroupModel)
        .where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
        .with_for_update()
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="WhatsApp broadcast group not found"
        )
    processing_result = await session.execute(
        select(func.count())
        .select_from(WhatsAppRecipientMessageStateModel)
        .where(
            WhatsAppRecipientMessageStateModel.broadcast_group_id == group.id,
            WhatsAppRecipientMessageStateModel.status == "processing",
        )
    )
    explicit_processing_result = await session.execute(
        select(func.count())
        .select_from(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.broadcast_group_id == group.id,
            WhatsAppMessageLogModel.is_explicit_resend.is_(True),
            WhatsAppMessageLogModel.status == "processing",
        )
    )
    if (
        int(processing_result.scalar_one()) > 0
        or int(explicit_processing_result.scalar_one()) > 0
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A WhatsApp provider request is currently in progress. "
                "Wait for it to finish before deleting this broadcast."
            ),
        )
    now = datetime.now(tz=UTC)
    await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.broadcast_group_id == group.id,
            WhatsAppMessageLogModel.status == "queued",
        )
        .values(
            status="failed",
            status_updated_at=now,
            error_message="WhatsApp broadcast deleted before delivery",
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(WhatsAppRecipientMessageStateModel)
        .where(
            WhatsAppRecipientMessageStateModel.broadcast_group_id == group.id,
            WhatsAppRecipientMessageStateModel.status == "queued",
        )
        .values(
            status="failed",
            batch_id=None,
            status_updated_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        delete(WhatsAppBroadcastGroupModel).where(WhatsAppBroadcastGroupModel.id == group.id)
    )
    return {"deleted": True}


@router.post("/groups/{group_id}/send", response_model=WhatsAppSendResponse)
async def send_broadcast_message(
    group_id: uuid.UUID,
    body: WhatsAppSendRequest,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppSendResponse:
    result = await session.execute(
        select(WhatsAppBroadcastGroupModel)
        .where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
        .with_for_update()
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="WhatsApp broadcast group not found"
        )
    if group.recipient_opt_in_confirmed_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recipient WhatsApp opt-in has not been confirmed for this list",
        )

    recipients = await _group_recipients(session, group.id)
    if not recipients:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This WhatsApp list has no recipients",
        )
    support_contacts = await _support_contacts_for_group(session, group.id)
    if not support_contacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add customer support contacts before sending this message",
        )

    message_type = _as_message_type(body.message_type)
    message_content = _resolve_send_message_content(
        message_type,
        body.message_content,
        group_name=group.name,
    )
    settings = get_settings()
    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp Cloud API credentials are incomplete",
        )
    template_name = (
        settings.whatsapp_welcome_template_name
        if message_type == "welcome"
        else settings.whatsapp_passport_link_template_name
    )
    if not template_name.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"WhatsApp {message_type} template name is not configured",
        )

    passport_link = (
        _validate_passport_link(body.passport_link) if message_type == "passport_link" else None
    )
    resolved_body = WhatsAppSendRequest(
        message_type=message_type,
        passport_link=passport_link,
        message_content=message_content,
    )
    batch_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    stale_cutoff = now - WHATSAPP_STALE_CLAIM_AGE

    # A queued task has not contacted Meta and is safe to reclaim. A stale
    # processing task may have submitted bytes before a worker interruption,
    # so it becomes delivery_unknown and remains suppressed.
    await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.broadcast_group_id == group.id,
            WhatsAppMessageLogModel.message_type == message_type,
            WhatsAppMessageLogModel.status == "queued",
            WhatsAppMessageLogModel.status_updated_at < stale_cutoff,
        )
        .values(
            status="failed",
            status_updated_at=now,
            error_message="Delivery claim expired before provider submission",
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.broadcast_group_id == group.id,
            WhatsAppMessageLogModel.message_type == message_type,
            WhatsAppMessageLogModel.status == "processing",
            WhatsAppMessageLogModel.status_updated_at < stale_cutoff,
        )
        .values(
            status="delivery_unknown",
            status_updated_at=now,
            error_message=(
                "Delivery outcome is unknown after a worker interruption; "
                "automatic resend is suppressed"
            ),
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(WhatsAppRecipientMessageStateModel)
        .where(
            WhatsAppRecipientMessageStateModel.broadcast_group_id == group.id,
            WhatsAppRecipientMessageStateModel.message_type == message_type,
            WhatsAppRecipientMessageStateModel.status == "processing",
            WhatsAppRecipientMessageStateModel.status_updated_at < stale_cutoff,
        )
        .values(
            status="delivery_unknown",
            status_updated_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )

    claim_values = [
        {
            "id": uuid.uuid4(),
            "broadcast_group_id": group.id,
            "recipient_id": recipient.id,
            "agency_id": recipient.agency_id,
            "message_type": message_type,
            "status": "queued",
            "batch_id": batch_id,
            "submitted_at": None,
            "status_updated_at": now,
            "created_at": now,
            "updated_at": now,
        }
        for recipient in recipients
    ]
    claim_insert = pg_insert(WhatsAppRecipientMessageStateModel).values(claim_values)
    claim_statement = (
        claim_insert.on_conflict_do_update(
            constraint="uq_whatsapp_recipient_message_state",
            set_={
                "status": "queued",
                "batch_id": batch_id,
                "submitted_at": None,
                "status_updated_at": now,
                "updated_at": now,
            },
            where=or_(
                ~WhatsAppRecipientMessageStateModel.status.in_(WHATSAPP_SUPPRESSED_STATUSES),
                and_(
                    WhatsAppRecipientMessageStateModel.status == "queued",
                    WhatsAppRecipientMessageStateModel.status_updated_at < stale_cutoff,
                ),
            ),
        )
        .returning(WhatsAppRecipientMessageStateModel.recipient_id)
        .execution_options(synchronize_session=False)
    )
    claimed_result = await session.execute(claim_statement)
    claimed_recipient_ids = set(claimed_result.scalars().all())
    claimed_recipients = [
        recipient for recipient in recipients if recipient.id in claimed_recipient_ids
    ]
    unclaimed_recipient_ids = [
        recipient.id for recipient in recipients if recipient.id not in claimed_recipient_ids
    ]
    skipped_already_sent = 0
    skipped_in_progress = 0
    skipped_delivery_unknown = 0
    if unclaimed_recipient_ids:
        skipped_result = await session.execute(
            select(WhatsAppRecipientMessageStateModel.status).where(
                WhatsAppRecipientMessageStateModel.recipient_id.in_(unclaimed_recipient_ids),
                WhatsAppRecipientMessageStateModel.message_type == message_type,
            )
        )
        skipped_statuses = list(skipped_result.scalars().all())
        skipped_already_sent = sum(
            1
            for delivery_status in skipped_statuses
            if delivery_status in WHATSAPP_ACCEPTED_STATUSES
        )
        skipped_in_progress = sum(
            1
            for delivery_status in skipped_statuses
            if delivery_status in WHATSAPP_IN_PROGRESS_STATUSES
        )
        skipped_delivery_unknown = sum(
            1
            for delivery_status in skipped_statuses
            if delivery_status in WHATSAPP_UNCERTAIN_STATUSES
        )

    if not claimed_recipients:
        await session.commit()
        return WhatsAppSendResponse(
            batch_id=None,
            queued=0,
            sent=0,
            failed=0,
            skipped_already_sent=skipped_already_sent,
            skipped_in_progress=skipped_in_progress,
            skipped_delivery_unknown=skipped_delivery_unknown,
            results=[],
        )

    results: list[WhatsAppSendResult] = []
    for recipient in claimed_recipients:
        _, _, _, rendered, header_parameters, parameters = _message_values(
            group=group,
            recipient=recipient,
            support_contacts=support_contacts,
            body=resolved_body,
        )
        session.add(
            WhatsAppMessageLogModel(
                batch_id=batch_id,
                broadcast_group_id=group.id,
                recipient_id=recipient.id,
                agency_id=recipient.agency_id,
                message_type=message_type,
                status="queued",
                status_updated_at=now,
                provider_message_id=None,
                error_message=None,
                template_name=template_name,
                rendered_message=rendered,
                header_parameter_values=header_parameters,
                template_parameter_values=parameters,
                is_explicit_resend=False,
                created_at=now,
            )
        )
        results.append(
            WhatsAppSendResult(
                recipient_id=recipient.id,
                phone_number=recipient.normalized_phone_number,
                status="queued",
            )
        )
    await session.commit()

    from app.infrastructure.whatsapp.tasks import process_whatsapp_broadcast

    try:
        process_whatsapp_broadcast.apply_async(
            kwargs={
                "batch_id": str(batch_id),
                "message_type": message_type,
                "message_content": message_content,
                "passport_link": passport_link,
            },
            queue="whatsapp",
        )
    except Exception as exc:  # noqa: BLE001 - convert broker failures into a visible batch failure.
        logger.error(
            "whatsapp_worker_queue_unavailable",
            extra={
                "batch_id": str(batch_id),
                "error_type": type(exc).__name__,
            },
        )
        error_message = (
            "WHATSAPP_QUEUE_UNAVAILABLE: WhatsApp delivery queue is temporarily unavailable"
        )
        logs_result = await session.execute(
            select(WhatsAppMessageLogModel).where(WhatsAppMessageLogModel.batch_id == batch_id)
        )
        for log in logs_result.scalars().all():
            log.status = "failed"
            log.status_updated_at = datetime.now(tz=UTC)
            log.error_message = error_message
        failure_time = datetime.now(tz=UTC)
        await session.execute(
            update(WhatsAppRecipientMessageStateModel)
            .where(
                WhatsAppRecipientMessageStateModel.batch_id == batch_id,
                WhatsAppRecipientMessageStateModel.status.in_(WHATSAPP_IN_PROGRESS_STATUSES),
            )
            .values(
                status="failed",
                batch_id=None,
                status_updated_at=failure_time,
                updated_at=failure_time,
            )
            .execution_options(synchronize_session=False)
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp delivery queue is unavailable",
        ) from exc

    return WhatsAppSendResponse(
        batch_id=batch_id,
        queued=len(results),
        sent=0,
        failed=0,
        skipped_already_sent=skipped_already_sent,
        skipped_in_progress=skipped_in_progress,
        skipped_delivery_unknown=skipped_delivery_unknown,
        results=results,
    )


@router.get("/batches/{batch_id}", response_model=WhatsAppSendResponse)
async def get_broadcast_batch_status(
    batch_id: uuid.UUID,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppSendResponse:
    result = await session.execute(
        select(WhatsAppMessageLogModel, WhatsAppBroadcastRecipientModel)
        .join(
            WhatsAppBroadcastRecipientModel,
            WhatsAppBroadcastRecipientModel.id == WhatsAppMessageLogModel.recipient_id,
        )
        .join(
            WhatsAppBroadcastGroupModel,
            WhatsAppBroadcastGroupModel.id == WhatsAppMessageLogModel.broadcast_group_id,
        )
        .where(
            WhatsAppMessageLogModel.batch_id == batch_id,
            *_agency_filter(current_user),
        )
        .order_by(WhatsAppMessageLogModel.created_at.asc())
    )
    rows = list(result.all())
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast batch not found",
        )

    queued_statuses = {"queued", "processing"}
    successful_statuses = {"submitted", "sent", "delivered", "read"}
    uncertain_statuses = {"delivery_unknown", "stalled"}
    stale_cutoff = datetime.now(tz=UTC) - timedelta(minutes=30)
    results: list[WhatsAppSendResult] = []
    for log, recipient in rows:
        is_stalled = log.status in queued_statuses and log.status_updated_at < stale_cutoff
        results.append(
            WhatsAppSendResult(
                recipient_id=recipient.id,
                phone_number=recipient.normalized_phone_number,
                status="stalled" if is_stalled else log.status,
                provider_message_id=log.provider_message_id,
                error_message=(
                    log.error_message
                    or (
                        "Delivery status is unknown after a worker interruption; verify before resending"
                        if is_stalled
                        else None
                    )
                ),
            )
        )
    return WhatsAppSendResponse(
        batch_id=batch_id,
        queued=sum(1 for item in results if item.status in queued_statuses),
        sent=sum(1 for item in results if item.status in successful_statuses),
        failed=sum(
            1
            for item in results
            if item.status not in queued_statuses | successful_statuses | uncertain_statuses
        ),
        delivery_unknown=sum(1 for item in results if item.status in uncertain_statuses),
        results=results,
    )
