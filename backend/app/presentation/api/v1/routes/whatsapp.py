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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from itertools import islice
from typing import Any, Literal
from urllib.parse import urlparse
from zipfile import BadZipFile, ZipFile

import httpx
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
from sqlalchemy import and_, delete, func, or_, select, union_all, update
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
from app.domain.exceptions.exceptions import ImageValidationError
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    DocumentWhatsAppDeliveryModel,
    PassengerQrWhatsAppDeliveryModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
    WhatsAppBroadcastSupportContactModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.passport_roster_resolution_repository import (
    active_replacement_phone_numbers_for_broadcast,
    active_replacement_resolution_id_for_recipient,
    suppress_active_replacement_recipients,
)
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    load_unresolved_passport_whatsapp_match_context,
)
from app.infrastructure.security.upload_validator import UploadValidator
from app.infrastructure.whatsapp.cloud_api_provider import (
    WhatsAppCloudApiError,
    upload_whatsapp_image,
)
from app.infrastructure.whatsapp.document_delivery_runtime import (
    apply_document_provider_status,
)
from app.infrastructure.whatsapp.qr_delivery_runtime import (
    apply_qr_provider_status,
)
from app.presentation.dependencies.auth import (
    WHATSAPP_BROADCAST_ROLES,
    require_role,
)

router = APIRouter()
logger = logging.getLogger(__name__)

WHATSAPP_ROLES = [*WHATSAPP_BROADCAST_ROLES]
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
MAX_WHATSAPP_WELCOME_IMAGE_BYTES = 5 * 1024 * 1024
MAX_WHATSAPP_EXCEL_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_WHATSAPP_EXCEL_ARCHIVE_MEMBERS = 2_000
MAX_WHATSAPP_EXCEL_COMPRESSION_RATIO = 250
MAX_WHATSAPP_EXCEL_HEADER_SCAN_ROWS = 25
MAX_WHATSAPP_EXCEL_SHEETS = 50
MAX_WHATSAPP_EXCEL_ROWS = 2_000
MAX_WHATSAPP_REJECTED_ROWS = 500
MAX_WHATSAPP_REJECTED_CONTACTS_PER_GROUP = 500
MAX_WHATSAPP_IMPORTED_FIELDS = 256
MAX_WHATSAPP_IMPORTED_FIELD_KEY_LENGTH = 64
MAX_WHATSAPP_IMPORTED_FIELD_VALUE_LENGTH = 256
MAX_WHATSAPP_IMPORTED_FIELDS_BYTES = 8 * 1024
WHATSAPP_UPLOAD_READ_CHUNK_BYTES = 1024 * 1024
WHATSAPP_ROSTER_SOURCE_FIELDS = frozenset(
    {"source_file", "source_order", "source_sheet", "source_row"}
)


class WhatsAppRecipientInput(BaseModel):
    name: str | None = None
    phone_number: str = Field(min_length=6, max_length=64)
    imported_fields: dict[str, str] = Field(default_factory=dict)


class WhatsAppContactPreviewRecipient(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    phone_number: str = Field(min_length=9, max_length=16)
    imported_fields: dict[str, str] = Field(default_factory=dict)


WhatsAppContactRejectionCode = Literal[
    "missing_phone",
    "invalid_phone",
    "missing_name",
    "duplicate_phone",
]


class WhatsAppContactPreviewRejectedRow(BaseModel):
    sheet_name: str = Field(min_length=1, max_length=31)
    row_number: int = Field(ge=1)
    raw_name: str | None = Field(default=None, max_length=256)
    raw_phone_number: str | None = Field(default=None, max_length=64)
    imported_fields: dict[str, str] = Field(default_factory=dict)
    reason_code: WhatsAppContactRejectionCode
    reason: str = Field(min_length=1, max_length=256)


class WhatsAppContactPreviewResponse(BaseModel):
    recipient_count: int
    accepted_count: int
    recipients: list[WhatsAppContactPreviewRecipient]
    rejected_count: int
    rejected_rows: list[WhatsAppContactPreviewRejectedRow]
    rejected_rows_truncated: bool
    omitted_rejected_count: int


@dataclass(slots=True)
class _WhatsAppExcelContactParseResult:
    contacts: list[WhatsAppRecipientInput]
    rejected_rows: list[WhatsAppContactPreviewRejectedRow]
    rejected_counts: dict[WhatsAppContactRejectionCode, int]

    @property
    def rejected_count(self) -> int:
        return sum(self.rejected_counts.values())


class WhatsAppRejectedContactInput(BaseModel):
    source_file_name: str = Field(min_length=1, max_length=255)
    sheet_name: str = Field(min_length=1, max_length=31)
    row_number: int = Field(ge=1, le=1_048_576)
    raw_name: str | None = Field(default=None, max_length=256)
    raw_phone_number: str | None = Field(default=None, max_length=64)
    imported_fields: dict[str, str] = Field(default_factory=dict)
    reason_code: WhatsAppContactRejectionCode


class WhatsAppRejectedContactResponse(BaseModel):
    id: uuid.UUID
    source_file_name: str
    sheet_name: str
    row_number: int
    raw_name: str | None
    raw_phone_number: str | None
    imported_fields: dict[str, str] = Field(default_factory=dict)
    reason_code: WhatsAppContactRejectionCode
    reason: str
    created_at: datetime


class WhatsAppRejectedContactListResponse(BaseModel):
    items: list[WhatsAppRejectedContactResponse]
    total: int
    limit: int
    offset: int


class WhatsAppRejectedContactResolveRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    phone_number: str = Field(min_length=1, max_length=64)
    recipient_opt_in_confirmed: bool


class WhatsAppSupportContactInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    phone_number: str = Field(min_length=6, max_length=64)


class WhatsAppRecipientResponse(BaseModel):
    id: uuid.UUID
    name: str | None
    phone_number: str
    normalized_phone_number: str
    imported_fields: dict[str, str] = Field(default_factory=dict)
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


class WhatsAppReplacedRecipientResponse(BaseModel):
    recipient_id: uuid.UUID
    resolution_id: uuid.UUID
    client_group_id: uuid.UUID
    client_group_name: str
    name: str | None
    phone_number: str
    normalized_phone_number: str
    imported_fields: dict[str, str] = Field(default_factory=dict)
    replacement_submission_id: uuid.UUID
    replacement_name: str
    replacement_phone: str | None = None
    replaced_at: datetime


class WhatsAppUnidentifiedUploadResponse(BaseModel):
    submission_id: uuid.UUID
    client_group_id: uuid.UUID
    client_group_name: str
    name: str
    phone_number: str | None = None
    email: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime


class WhatsAppRecipientRosterItemResponse(BaseModel):
    kind: Literal["recipient", "rejected", "replaced", "unidentified"]
    display_order: int
    recipient: WhatsAppRecipientResponse | None = None
    rejected_contact: WhatsAppRejectedContactResponse | None = None
    replaced_recipient: WhatsAppReplacedRecipientResponse | None = None
    unidentified_upload: WhatsAppUnidentifiedUploadResponse | None = None


class WhatsAppRecipientRosterCountsResponse(BaseModel):
    all: int
    sent: int
    failed: int
    rejected: int
    replaced: int
    unidentified: int


class WhatsAppRecipientRosterResponse(BaseModel):
    items: list[WhatsAppRecipientRosterItemResponse]
    counts: WhatsAppRecipientRosterCountsResponse


class WhatsAppSupportContactResponse(BaseModel):
    id: uuid.UUID
    name: str
    phone_number: str
    normalized_phone_number: str


class WhatsAppBroadcastGroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    organizing_company_name: str
    # Delivery actions use active valid recipients. The total is the visible
    # roster size and also includes unresolved rejected spreadsheet rows.
    recipient_count: int
    total_contact_count: int
    recipient_opt_in_confirmed: bool
    created_at: datetime
    updated_at: datetime


class WhatsAppBroadcastGroupDetailResponse(WhatsAppBroadcastGroupResponse):
    recipients: list[WhatsAppRecipientResponse]
    support_contacts: list[WhatsAppSupportContactResponse]
    rejected_contact_count: int


class WhatsAppSendRequest(BaseModel):
    message_type: str = Field(pattern="^(welcome|passport_link|reminder)$")
    passport_intro: str | None = Field(default=None, max_length=600)
    passport_link: str | None = None
    message_content: str | None = Field(default=None, max_length=600)
    header_image_id: str | None = Field(default=None, max_length=255)
    recipient_ids: list[uuid.UUID] | None = Field(
        default=None,
        max_length=MAX_WHATSAPP_RECIPIENTS,
    )
    support_contact_ids: list[uuid.UUID] | None = Field(default=None, max_length=1)


class WhatsAppResendRequest(WhatsAppSendRequest):
    pass


class WhatsAppRecipientPhoneUpdateRequest(BaseModel):
    phone_number: str = Field(min_length=1, max_length=64)


class WhatsAppPreviewRequest(WhatsAppSendRequest):
    recipient_id: uuid.UUID | None = None
    resend_recipient_id: uuid.UUID | None = None


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
    passport_intro: str | None
    passport_link: str | None
    message_content: str
    header_image_id: str | None
    content_source: Literal["default", "latest_group", "latest_recipient"]
    rendered_message: str
    header_parameter_values: list[str]
    parameter_values: list[str]


class WhatsAppWelcomeMediaResponse(BaseModel):
    media_id: str
    file_name: str
    content_type: str


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


@dataclass(frozen=True, slots=True)
class _WhatsAppComposerSnapshot:
    log: WhatsAppMessageLogModel
    passport_intro: str | None
    passport_link: str | None
    message_content: str
    header_image_id: str | None


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
        message_logs = list(result.scalars().all())
        for log in message_logs:
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
        if not message_logs:
            document_result = await session.execute(
                select(DocumentWhatsAppDeliveryModel).where(
                    DocumentWhatsAppDeliveryModel.provider_message_id == provider_id
                )
            )
            document_deliveries = document_result.scalars().all()
            for delivery in document_deliveries:
                if not isinstance(delivery, DocumentWhatsAppDeliveryModel):
                    continue
                apply_document_provider_status(
                    delivery,
                    provider_status=provider_status,
                    error_message=error_message,
                    provider_status_at=provider_status_at,
                    now=datetime.now(tz=UTC),
                )
                processed_statuses += 1
            if not document_deliveries:
                qr_result = await session.execute(
                    select(PassengerQrWhatsAppDeliveryModel).where(
                        PassengerQrWhatsAppDeliveryModel.provider_message_id
                        == provider_id
                    )
                )
                for delivery in qr_result.scalars().all():
                    if not isinstance(delivery, PassengerQrWhatsAppDeliveryModel):
                        continue
                    apply_qr_provider_status(
                        delivery,
                        provider_status=provider_status,
                        error_message=error_message,
                        provider_status_at=provider_status_at,
                        now=datetime.now(tz=UTC),
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
    if value == "welcome":
        return "welcome"
    if value == "reminder":
        return "reminder"
    return "passport_link"


def _configured_template_name(message_type: WhatsAppMessageType) -> str:
    settings = get_settings()
    if message_type == "welcome":
        return settings.whatsapp_welcome_template_name
    if message_type == "reminder":
        return settings.whatsapp_reminder_template_name
    return settings.whatsapp_passport_link_template_name


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


def _resolve_passport_intro(value: str | None, *, group_name: str) -> str:
    if value is None:
        return passport_link_intro(group_name)
    return value.strip()


def _resolve_send_passport_intro(value: str | None, *, group_name: str) -> str:
    intro = _resolve_passport_intro(value, group_name=group_name)
    if not intro:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Enter the passport-link introduction before sending. "
                "Meta requires BODY {{1}} to contain text."
            ),
        )
    return intro


def _resolve_send_header_image(
    message_type: WhatsAppMessageType,
    value: str | None,
    *,
    resend: bool = False,
) -> str | None:
    if message_type == "reminder":
        return None
    media_id = (value or "").strip()
    if media_id:
        return media_id
    action = "resending" if resend else "sending"
    label = "Welcome" if message_type == "welcome" else "Passport Link"
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Upload the required {label} image before {action}",
    )


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


def _append_excel_contact_rejection(
    rejected_rows: list[WhatsAppContactPreviewRejectedRow],
    rejected_counts: dict[WhatsAppContactRejectionCode, int],
    *,
    sheet_name: str,
    row_number: int,
    raw_name: str | None,
    raw_phone_number: str | None,
    imported_fields: dict[str, str],
    reason_code: WhatsAppContactRejectionCode,
) -> None:
    rejected_counts[reason_code] = rejected_counts.get(reason_code, 0) + 1
    if len(rejected_rows) >= MAX_WHATSAPP_REJECTED_ROWS:
        return
    rejected_rows.append(
        WhatsAppContactPreviewRejectedRow(
            sheet_name=sheet_name,
            row_number=row_number,
            raw_name=raw_name,
            raw_phone_number=raw_phone_number,
            imported_fields=_safe_imported_fields(imported_fields),
            reason_code=reason_code,
            reason=_WHATSAPP_CONTACT_REJECTION_REASONS[reason_code],
        )
    )


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


def _parse_excel_contact_bytes(
    payload: bytes,
    *,
    filename: str,
) -> _WhatsAppExcelContactParseResult:
    source_file_name = (
        filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1].strip() or "contacts.xlsx"
    )
    suffix = source_file_name.rsplit(".", maxsplit=1)[-1].lower()
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
        worksheets = workbook.worksheets
        if len(worksheets) > MAX_WHATSAPP_EXCEL_SHEETS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "The Excel contact file contains too many worksheets; "
                    f"use at most {MAX_WHATSAPP_EXCEL_SHEETS}"
                ),
            )
        sheet_rows: list[tuple[str, list[tuple[Any, ...]]]] = []
        total_rows = 0
        for sheet in worksheets:
            remaining_rows = MAX_WHATSAPP_EXCEL_ROWS - total_rows
            rows = list(
                islice(
                    sheet.iter_rows(values_only=True),
                    remaining_rows + 1,
                )
            )
            total_rows += len(rows)
            if total_rows > MAX_WHATSAPP_EXCEL_ROWS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "The Excel contact file can contain at most "
                        f"{MAX_WHATSAPP_EXCEL_ROWS} rows across all worksheets"
                    ),
                )
            sheet_rows.append((sheet.title, rows))
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

    if not any(rows for _, rows in sheet_rows):
        return _WhatsAppExcelContactParseResult(
            contacts=[],
            rejected_rows=[],
            rejected_counts={},
        )

    contacts_by_phone: dict[str, WhatsAppRecipientInput] = {}
    rejected_rows: list[WhatsAppContactPreviewRejectedRow] = []
    rejected_counts: dict[WhatsAppContactRejectionCode, int] = {}
    source_order = 0
    for sheet_index, (sheet_name, rows) in enumerate(sheet_rows):
        if not rows:
            continue
        header_match = _find_excel_contact_header(rows)
        if header_match:
            (
                header_row_index,
                phone_columns,
                name_columns,
                given_name_columns,
                surname_columns,
            ) = header_match
            header_row = rows[header_row_index]
            data_rows = rows[header_row_index + 1 :]
            first_data_row_number = header_row_index + 2
        elif sheet_index == 0:
            header_row = ()
            phone_columns = []
            name_columns = []
            given_name_columns = []
            surname_columns = []
            data_rows = rows
            first_data_row_number = 1
        else:
            # A multi-sheet workbook often contains notes or lookup sheets.
            # Never scan those heuristically for phone-like numbers.
            continue

        for row_number, row in enumerate(
            data_rows,
            start=first_data_row_number,
        ):
            row_values = list(row)
            if header_row and _is_repeated_excel_header(row_values, header_row):
                continue
            source_order += 1
            candidates: list[tuple[str | None, str, dict[str, str]]] = []
            imported_fields = (
                _excel_fields_from_row(
                    header_row=header_row,
                    row_values=row_values,
                    sheet_name=sheet_name,
                    source_file_name=source_file_name,
                    row_number=row_number,
                    source_order=source_order,
                )
                if header_row
                else _safe_imported_fields(
                    {
                        "source_file": source_file_name,
                        "source_order": str(source_order),
                        "source_sheet": sheet_name,
                        "source_row": str(row_number),
                    }
                )
            )
            name = _excel_name_from_row(
                row_values,
                name_columns=name_columns,
                given_name_columns=given_name_columns,
                surname_columns=surname_columns,
                phone_columns=phone_columns,
            )
            raw_name = _excel_raw_name_from_row(
                row_values,
                name_columns=name_columns,
                given_name_columns=given_name_columns,
                surname_columns=surname_columns,
                phone_columns=phone_columns,
            )
            if phone_columns:
                phone_values: list[str] = []
                for index in phone_columns:
                    if index >= len(row_values):
                        continue
                    phone = _bounded_excel_raw_value(
                        row_values[index],
                        max_length=64,
                    )
                    if phone:
                        phone_values.append(phone)
                if not phone_values:
                    if _row_has_contact_identity(
                        name=name,
                        imported_fields=imported_fields,
                    ):
                        _append_excel_contact_rejection(
                            rejected_rows,
                            rejected_counts,
                            sheet_name=sheet_name,
                            row_number=row_number,
                            raw_name=raw_name,
                            raw_phone_number=None,
                            imported_fields=imported_fields,
                            reason_code="missing_phone",
                        )
                    continue
                candidates.extend((name, phone, imported_fields) for phone in phone_values)
            else:
                row_text = " ".join(text for cell in row_values if (text := _excel_cell_text(cell)))
                for match in PHONE_RE.findall(row_text):
                    candidates.append((name, match, imported_fields))

            for name, phone, fields in candidates:
                normalized = _normalize_phone(phone)
                if not normalized:
                    _append_excel_contact_rejection(
                        rejected_rows,
                        rejected_counts,
                        sheet_name=sheet_name,
                        row_number=row_number,
                        raw_name=raw_name,
                        raw_phone_number=phone,
                        imported_fields=fields,
                        reason_code="invalid_phone",
                    )
                    continue
                incoming = WhatsAppRecipientInput(
                    name=name,
                    phone_number=phone,
                    imported_fields=fields,
                )
                existing = contacts_by_phone.get(normalized)
                if not name:
                    if existing:
                        contacts_by_phone[normalized] = _merge_recipient_inputs(
                            existing,
                            incoming,
                        )
                    _append_excel_contact_rejection(
                        rejected_rows,
                        rejected_counts,
                        sheet_name=sheet_name,
                        row_number=row_number,
                        raw_name=raw_name,
                        raw_phone_number=phone,
                        imported_fields=fields,
                        reason_code="missing_name",
                    )
                    continue
                if existing:
                    contacts_by_phone[normalized] = _merge_recipient_inputs(
                        existing,
                        incoming,
                    )
                    _append_excel_contact_rejection(
                        rejected_rows,
                        rejected_counts,
                        sheet_name=sheet_name,
                        row_number=row_number,
                        raw_name=raw_name,
                        raw_phone_number=phone,
                        imported_fields=fields,
                        reason_code="duplicate_phone",
                    )
                    continue
                contacts_by_phone[normalized] = incoming
                if len(contacts_by_phone) > MAX_WHATSAPP_RECIPIENTS:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            "The Excel contact file can contain at most "
                            f"{MAX_WHATSAPP_RECIPIENTS} recipients"
                        ),
                    )
    return _WhatsAppExcelContactParseResult(
        contacts=list(contacts_by_phone.values()),
        rejected_rows=rejected_rows,
        rejected_counts=rejected_counts,
    )


async def _parse_excel_contact_preview(
    upload: UploadFile,
) -> _WhatsAppExcelContactParseResult:
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


async def _parse_excel_contacts(
    upload: UploadFile,
) -> list[WhatsAppRecipientInput]:
    result = await _parse_excel_contact_preview(upload)
    blocking_rejection_count = sum(
        count
        for reason_code, count in result.rejected_counts.items()
        if reason_code != "duplicate_phone"
    )
    if blocking_rejection_count:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"The Excel contact file contains {blocking_rejection_count} "
                "invalid contact row(s). Preview the file, correct the rejected "
                "rows, and upload it again."
            ),
        )
    return result.contacts


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
    for contact in rejected_contacts:
        fingerprint = _rejected_contact_fingerprint(contact)
        if fingerprint not in existing_by_fingerprint:
            candidates.append(
                (
                    _roster_source_sort_key(
                        contact.imported_fields,
                        fallback_source_file=contact.source_file_name,
                        fallback_source_sheet=contact.sheet_name,
                        fallback_source_row=contact.row_number,
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
        reason_code=model.reason_code,
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


async def _recipient_delivery_state_maps(
    session: AsyncSession,
    recipients: list[WhatsAppBroadcastRecipientModel],
) -> tuple[
    dict[uuid.UUID, list[WhatsAppRecipientMessageStateModel]],
    dict[uuid.UUID, dict[str, str]],
]:
    states_by_recipient: dict[uuid.UUID, list[WhatsAppRecipientMessageStateModel]] = {}
    resend_statuses_by_recipient: dict[uuid.UUID, dict[str, str]] = {}
    if not recipients:
        return states_by_recipient, resend_statuses_by_recipient

    recipient_ids = [recipient.id for recipient in recipients]
    states_result = await session.execute(
        select(WhatsAppRecipientMessageStateModel)
        .where(WhatsAppRecipientMessageStateModel.recipient_id.in_(recipient_ids))
        .order_by(WhatsAppRecipientMessageStateModel.message_type.asc())
    )
    for state_model in states_result.scalars().all():
        states_by_recipient.setdefault(state_model.recipient_id, []).append(state_model)

    resend_result = await session.execute(
        select(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.recipient_id.in_(recipient_ids),
            WhatsAppMessageLogModel.is_explicit_resend.is_(True),
        )
        .order_by(WhatsAppMessageLogModel.created_at.desc())
    )
    for resend_log in resend_result.scalars().all():
        current_state = next(
            (
                state
                for state in states_by_recipient.get(resend_log.recipient_id, [])
                if state.message_type == resend_log.message_type
            ),
            None,
        )
        if (
            current_state
            and current_state.status == "failed"
            and resend_log.created_at <= current_state.status_updated_at
        ):
            continue
        recipient_statuses = resend_statuses_by_recipient.setdefault(
            resend_log.recipient_id,
            {},
        )
        recipient_statuses.setdefault(resend_log.message_type, resend_log.status)
    return states_by_recipient, resend_statuses_by_recipient


async def _group_detail(
    session: AsyncSession, group: WhatsAppBroadcastGroupModel
) -> WhatsAppBroadcastGroupDetailResponse:
    recipients = await _group_recipients(session, group.id)
    states_by_recipient, resend_statuses_by_recipient = await _recipient_delivery_state_maps(
        session, recipients
    )
    support_contacts = await _support_contacts_for_group(session, group.id)
    rejected_count_result = await session.execute(
        select(func.count())
        .select_from(WhatsAppBroadcastRejectedContactModel)
        .where(
            WhatsAppBroadcastRejectedContactModel.broadcast_group_id == group.id,
        )
    )
    rejected_contact_count = int(rejected_count_result.scalar_one())
    return WhatsAppBroadcastGroupDetailResponse(
        id=group.id,
        name=group.name,
        organizing_company_name=group.organizing_company_name,
        recipient_count=len(recipients),
        total_contact_count=len(recipients) + rejected_contact_count,
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
        rejected_contact_count=rejected_contact_count,
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
    recipients = list(result.scalars().all())
    if not recipients:
        return []
    suppressed_phones = await active_replacement_phone_numbers_for_broadcast(
        session,
        broadcast_group_id=group_id,
        agency_id=recipients[0].agency_id,
    )
    return [
        recipient
        for recipient in recipients
        if recipient.normalized_phone_number not in suppressed_phones
    ]


def _select_group_recipients(
    recipients: list[WhatsAppBroadcastRecipientModel],
    requested_ids: list[uuid.UUID] | None,
) -> list[WhatsAppBroadcastRecipientModel]:
    """Apply an optional custom-recipient selection without widening scope."""
    if requested_ids is None:
        return recipients
    requested_id_set = set(requested_ids)
    if not requested_id_set:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select at least one WhatsApp recipient",
        )
    selected = [recipient for recipient in recipients if recipient.id in requested_id_set]
    if len(selected) != len(requested_id_set):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more selected WhatsApp recipients were not found in this list",
        )
    return selected


def _select_support_contacts(
    support_contacts: list[WhatsAppBroadcastSupportContactModel],
    requested_ids: list[uuid.UUID] | None,
    *,
    message_type: WhatsAppMessageType,
) -> list[WhatsAppBroadcastSupportContactModel]:
    """Apply optional support-contact selection for Passport Link messages."""
    if message_type != "passport_link" or requested_ids is None:
        return support_contacts
    requested_id_set = set(requested_ids)
    if not requested_id_set:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select at least one customer support contact",
        )
    selected = [contact for contact in support_contacts if contact.id in requested_id_set]
    if len(selected) != len(requested_id_set):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "One or more selected customer support contacts were not found "
                "in this WhatsApp list"
            ),
        )
    return selected


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
) -> tuple[
    WhatsAppMessageType,
    str | None,
    str | None,
    str,
    str,
    str,
    list[str],
    list[str],
]:
    message_type = _as_message_type(body.message_type)
    message_content = _resolve_message_content(
        message_type,
        body.message_content,
        group_name=group.name,
    )
    passport_intro = (
        _resolve_passport_intro(body.passport_intro, group_name=group.name)
        if message_type == "passport_link"
        else None
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
        passport_intro=passport_intro,
    )
    header_parameters = template_header_parameters(
        message_type=message_type,
        header_image_id=body.header_image_id,
    )
    parameters = template_parameters(
        message_type=message_type,
        group_name=group.name,
        support_contacts=support_block,
        message_content=message_content,
        passport_link=passport_link,
        passport_intro=passport_intro,
    )
    return (
        message_type,
        passport_intro,
        passport_link,
        message_content,
        recipient_name,
        rendered,
        header_parameters,
        parameters,
    )


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
        reconstructed = (
            f"{STATIC_TEMPLATE_HEADER}\n\n"
            f"{GREETING}\n\n"
            f"{message_content}\n\n"
            f"{AUTOMATED_NOTICE}\n\n"
            "For assistance, please contact:\n"
            f"{support_contacts}\n\n"
            "Regards,\n"
            "Team Global Connect Travels"
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
    if log.message_type not in {"welcome", "passport_link", "reminder"}:
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


def _composer_snapshot_from_log(
    log: WhatsAppMessageLogModel,
) -> _WhatsAppComposerSnapshot:
    header_parameters, parameters = _template_snapshot_from_log(log)
    header_image_id = header_parameters[0] if header_parameters else None
    if log.message_type in {"welcome", "reminder"}:
        return _WhatsAppComposerSnapshot(
            log=log,
            passport_intro=None,
            passport_link=None,
            message_content=parameters[0],
            header_image_id=header_image_id,
        )
    return _WhatsAppComposerSnapshot(
        log=log,
        passport_intro=parameters[0],
        passport_link=parameters[1],
        message_content=parameters[2],
        header_image_id=header_image_id,
    )


async def _latest_composer_snapshot(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    message_type: WhatsAppMessageType,
    recipient_id: uuid.UUID | None = None,
    accepted_only: bool = True,
    include_failed: bool = False,
    include_explicit_resends: bool = False,
) -> _WhatsAppComposerSnapshot | None:
    reusable_statuses = (
        WHATSAPP_ACCEPTED_STATUSES
        if accepted_only
        else WHATSAPP_ACCEPTED_STATUSES | WHATSAPP_IN_PROGRESS_STATUSES
    )
    if include_failed:
        reusable_statuses = reusable_statuses | {"failed"}
    predicates: list[Any] = [
        WhatsAppMessageLogModel.broadcast_group_id == group_id,
        WhatsAppMessageLogModel.message_type == message_type,
        WhatsAppMessageLogModel.status.in_(reusable_statuses),
    ]
    if recipient_id is not None:
        predicates.append(WhatsAppMessageLogModel.recipient_id == recipient_id)
    if not include_explicit_resends:
        predicates.append(WhatsAppMessageLogModel.is_explicit_resend.is_(False))
    result = await session.execute(
        select(WhatsAppMessageLogModel)
        .where(*predicates)
        .order_by(
            WhatsAppMessageLogModel.created_at.desc(),
            WhatsAppMessageLogModel.status_updated_at.desc(),
        )
        .limit(20)
    )
    for log in result.scalars().all():
        try:
            return _composer_snapshot_from_log(log)
        except ValueError:
            logger.warning(
                "whatsapp_composer_snapshot_ignored",
                extra={
                    "message_log_id": str(log.id),
                    "message_type": message_type,
                },
            )
    return None


def _merge_composer_snapshot(
    body: WhatsAppSendRequest,
    snapshot: _WhatsAppComposerSnapshot | None,
) -> WhatsAppSendRequest:
    message_type = _as_message_type(body.message_type)
    return WhatsAppSendRequest(
        message_type=message_type,
        passport_intro=(
            body.passport_intro
            if body.passport_intro is not None
            else snapshot.passport_intro
            if snapshot
            else None
        ),
        passport_link=(
            body.passport_link
            if body.passport_link is not None
            else snapshot.passport_link
            if snapshot
            else None
        ),
        message_content=(
            body.message_content
            if body.message_content is not None
            else snapshot.message_content
            if snapshot
            else None
        ),
        header_image_id=(
            body.header_image_id
            if body.header_image_id is not None
            else snapshot.header_image_id
            if snapshot
            else None
        ),
        recipient_ids=body.recipient_ids,
        support_contact_ids=body.support_contact_ids,
    )


@router.post(
    "/contacts/preview",
    response_model=WhatsAppContactPreviewResponse,
)
async def preview_excel_contacts(
    contacts_file: UploadFile = File(...),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
) -> WhatsAppContactPreviewResponse:
    del current_user
    result = await _parse_excel_contact_preview(contacts_file)
    return _excel_contact_preview_response(
        result.contacts,
        result.rejected_rows,
        rejected_count=result.rejected_count,
    )


@router.get("/groups", response_model=list[WhatsAppBroadcastGroupResponse])
async def list_broadcast_groups(
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[WhatsAppBroadcastGroupResponse]:
    rejected_contact_count = (
        select(func.count(WhatsAppBroadcastRejectedContactModel.id))
        .where(
            WhatsAppBroadcastRejectedContactModel.broadcast_group_id
            == WhatsAppBroadcastGroupModel.id,
        )
        .correlate(WhatsAppBroadcastGroupModel)
        .scalar_subquery()
    )
    result = await session.execute(
        select(
            WhatsAppBroadcastGroupModel,
            func.count(WhatsAppBroadcastRecipientModel.id).label("recipient_count"),
            rejected_contact_count.label("rejected_contact_count"),
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
            recipient_count=int(recipient_count or 0),
            total_contact_count=(int(recipient_count or 0) + int(rejected_count or 0)),
            recipient_opt_in_confirmed=group.recipient_opt_in_confirmed_at is not None,
            created_at=group.created_at,
            updated_at=group.updated_at,
        )
        for group, recipient_count, rejected_count in result.all()
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


def _unidentified_submission_details(
    submission: PassportSubmissionModel,
) -> dict[str, Any]:
    details: dict[str, Any] = {
        "family_head_name": submission.family_head_name,
        "family_head_phone": submission.family_head_phone,
        "family_head_email": submission.family_head_email,
        "family_relation": submission.family_relation,
        "family_gender": submission.family_gender,
        "departure_city": submission.departure_city,
        "nearest_domestic_airport": submission.nearest_domestic_airport,
    }
    for fields in (
        submission.staff_metadata,
        submission.extracted_fields,
        submission.confirmed_fields,
    ):
        details.update(dict(fields or {}))
    return {
        str(key): value
        for key, value in details.items()
        if value is not None and value != ""
    }


async def _unidentified_uploads_for_broadcast(
    session: AsyncSession,
    *,
    broadcast_group_id: uuid.UUID,
    agency_id: uuid.UUID,
) -> list[WhatsAppUnidentifiedUploadResponse]:
    linked_group_result = await session.execute(
        select(ClientGroupModel)
        .join(
            ClientGroupWhatsAppBroadcastLinkModel,
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id
            == ClientGroupModel.id,
        )
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id
            == broadcast_group_id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
            ClientGroupModel.agency_id == agency_id,
            ClientGroupModel.deleted_at.is_(None),
        )
        .order_by(ClientGroupModel.name.asc(), ClientGroupModel.id.asc())
    )
    linked_client_groups = list(linked_group_result.scalars().all())
    unidentified: list[WhatsAppUnidentifiedUploadResponse] = []
    seen_submission_ids: set[uuid.UUID] = set()

    for client_group in linked_client_groups:
        (
            _linked_broadcasts,
            _recipients,
            submissions,
            rows,
        ) = await load_unresolved_passport_whatsapp_match_context(
            session,
            group_id=client_group.id,
            agency_id=agency_id,
            broadcast_group_ids=[broadcast_group_id],
        )
        submission_by_id = {submission.id: submission for submission in submissions}
        unmatched_submission_ids = {
            submission_id
            for row in rows
            if row.status == "unmatched_submission"
            for submission_id in row.submission_ids
        }
        for submission_id in unmatched_submission_ids:
            if submission_id in seen_submission_ids:
                continue
            submission = submission_by_id.get(submission_id)
            if submission is None:
                continue
            seen_submission_ids.add(submission_id)
            unidentified.append(
                WhatsAppUnidentifiedUploadResponse(
                    submission_id=submission.id,
                    client_group_id=client_group.id,
                    client_group_name=client_group.name,
                    name=submission.client_name,
                    phone_number=(
                        submission.client_phone or submission.family_head_phone
                    ),
                    email=submission.client_email or submission.family_head_email,
                    details=_unidentified_submission_details(submission),
                    updated_at=submission.updated_at,
                )
            )

    unidentified.sort(
        key=lambda upload: (
            upload.client_group_name.casefold(),
            upload.name.casefold(),
            upload.updated_at,
            str(upload.submission_id),
        )
    )
    return unidentified


@router.get(
    "/groups/{group_id}/recipient-roster",
    response_model=WhatsAppRecipientRosterResponse,
)
async def get_broadcast_recipient_roster(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppRecipientRosterResponse:
    group_result = await session.execute(
        select(WhatsAppBroadcastGroupModel).where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
    )
    group = group_result.scalar_one_or_none()
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )

    recipients_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group_id,
            WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        )
        .order_by(
            WhatsAppBroadcastRecipientModel.display_order.asc().nullslast(),
            WhatsAppBroadcastRecipientModel.created_at.asc(),
            WhatsAppBroadcastRecipientModel.id.asc(),
        )
    )
    recipients = list(recipients_result.scalars().all())
    rejected_result = await session.execute(
        select(WhatsAppBroadcastRejectedContactModel)
        .where(
            WhatsAppBroadcastRejectedContactModel.broadcast_group_id == group_id,
            WhatsAppBroadcastRejectedContactModel.agency_id == group.agency_id,
        )
        .order_by(
            WhatsAppBroadcastRejectedContactModel.display_order.asc().nullslast(),
            WhatsAppBroadcastRejectedContactModel.created_at.asc(),
            WhatsAppBroadcastRejectedContactModel.id.asc(),
        )
    )
    rejected_contacts = list(rejected_result.scalars().all())
    replaced_result = await session.execute(
        select(
            WhatsAppBroadcastRecipientModel,
            PassportRosterResolutionModel,
            ClientGroupModel,
            PassportSubmissionModel,
        )
        .join(
            PassportRosterResolutionModel,
            WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id
            == PassportRosterResolutionModel.id,
        )
        .join(
            ClientGroupModel,
            PassportRosterResolutionModel.client_group_id
            == ClientGroupModel.id,
        )
        .join(
            PassportSubmissionModel,
            PassportRosterResolutionModel.submission_id
            == PassportSubmissionModel.id,
        )
        .where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group_id,
            WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
            WhatsAppBroadcastRecipientModel.removed_at.is_not(None),
            WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id.is_not(
                None
            ),
            PassportRosterResolutionModel.agency_id == group.agency_id,
            PassportRosterResolutionModel.status == "active",
            PassportRosterResolutionModel.resolution_type == "replacement",
            ClientGroupModel.agency_id == group.agency_id,
            PassportSubmissionModel.agency_id == group.agency_id,
        )
        .order_by(
            WhatsAppBroadcastRecipientModel.display_order.asc().nullslast(),
            PassportRosterResolutionModel.created_at.asc(),
            WhatsAppBroadcastRecipientModel.id.asc(),
        )
    )
    replaced_rows = list(replaced_result.all())
    states_by_recipient, resend_statuses_by_recipient = await _recipient_delivery_state_maps(
        session, recipients
    )
    unidentified_uploads = await _unidentified_uploads_for_broadcast(
        session,
        broadcast_group_id=group_id,
        agency_id=group.agency_id,
    )

    roster_models: list[
        tuple[
            Literal["recipient", "rejected", "replaced"],
            WhatsAppBroadcastRecipientModel | WhatsAppBroadcastRejectedContactModel,
        ]
    ] = [("recipient", recipient) for recipient in recipients] + [
        ("rejected", rejected_contact) for rejected_contact in rejected_contacts
    ] + [
        ("replaced", recipient)
        for recipient, _resolution, _client_group, _submission in replaced_rows
    ]
    replaced_by_recipient_id = {
        recipient.id: (resolution, client_group, submission)
        for recipient, resolution, client_group, submission in replaced_rows
    }
    roster_models.sort(
        key=lambda item: (
            item[1].display_order is None,
            item[1].display_order or 0,
            item[1].created_at,
            item[0],
            str(item[1].id),
        )
    )
    next_fallback_order = (
        max(
            (model.display_order or 0 for _, model in roster_models),
            default=0,
        )
        + 1
    )
    items: list[WhatsAppRecipientRosterItemResponse] = []
    for kind, model in roster_models:
        display_order = model.display_order
        if display_order is None:
            display_order = next_fallback_order
            next_fallback_order += 1
        if kind == "recipient":
            recipient = model
            assert isinstance(recipient, WhatsAppBroadcastRecipientModel)
            items.append(
                WhatsAppRecipientRosterItemResponse(
                    kind="recipient",
                    display_order=display_order,
                    recipient=_recipient_response(
                        recipient,
                        states_by_recipient.get(recipient.id, []),
                        resend_statuses_by_recipient.get(recipient.id, {}),
                    ),
                )
            )
        elif kind == "rejected":
            rejected_contact = model
            assert isinstance(
                rejected_contact,
                WhatsAppBroadcastRejectedContactModel,
            )
            items.append(
                WhatsAppRecipientRosterItemResponse(
                    kind="rejected",
                    display_order=display_order,
                    rejected_contact=_rejected_contact_response(rejected_contact),
                )
            )
        else:
            recipient = model
            assert isinstance(recipient, WhatsAppBroadcastRecipientModel)
            resolution, client_group, submission = replaced_by_recipient_id[
                recipient.id
            ]
            items.append(
                WhatsAppRecipientRosterItemResponse(
                    kind="replaced",
                    display_order=display_order,
                    replaced_recipient=WhatsAppReplacedRecipientResponse(
                        recipient_id=recipient.id,
                        resolution_id=resolution.id,
                        client_group_id=client_group.id,
                        client_group_name=client_group.name,
                        name=resolution.original_recipient_name,
                        phone_number=resolution.original_recipient_phone,
                        normalized_phone_number=(
                            resolution.replaced_recipient_normalized_phone
                        ),
                        imported_fields=dict(
                            resolution.original_recipient_imported_fields
                        ),
                        replacement_submission_id=submission.id,
                        replacement_name=submission.client_name,
                        replacement_phone=submission.client_phone,
                        replaced_at=resolution.created_at,
                    ),
                )
            )

    for upload in unidentified_uploads:
        items.append(
            WhatsAppRecipientRosterItemResponse(
                kind="unidentified",
                display_order=next_fallback_order,
                unidentified_upload=upload,
            )
        )
        next_fallback_order += 1

    sent_count = 0
    failed_count = 0
    for recipient in recipients:
        recipient_states = states_by_recipient.get(recipient.id, [])
        resend_statuses = resend_statuses_by_recipient.get(recipient.id, {})
        if any(state.status in WHATSAPP_ACCEPTED_STATUSES for state in recipient_states):
            sent_count += 1
        if (
            any(state.status == "failed" for state in recipient_states)
            or "failed" in resend_statuses.values()
        ):
            failed_count += 1

    return WhatsAppRecipientRosterResponse(
        items=items,
        counts=WhatsAppRecipientRosterCountsResponse(
            all=len(recipients) + len(rejected_contacts),
            sent=sent_count,
            failed=failed_count,
            rejected=len(rejected_contacts),
            replaced=len(replaced_rows),
            unidentified=len(unidentified_uploads),
        ),
    )


@router.get(
    "/groups/{group_id}/rejected-contacts",
    response_model=WhatsAppRejectedContactListResponse,
)
async def list_broadcast_rejected_contacts(
    group_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppRejectedContactListResponse:
    group_result = await session.execute(
        select(WhatsAppBroadcastGroupModel.id).where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
    )
    if group_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )

    total_result = await session.execute(
        select(func.count())
        .select_from(WhatsAppBroadcastRejectedContactModel)
        .where(
            WhatsAppBroadcastRejectedContactModel.broadcast_group_id == group_id,
        )
    )
    total = int(total_result.scalar_one())
    items_result = await session.execute(
        select(WhatsAppBroadcastRejectedContactModel)
        .where(
            WhatsAppBroadcastRejectedContactModel.broadcast_group_id == group_id,
        )
        .order_by(
            WhatsAppBroadcastRejectedContactModel.created_at.desc(),
            WhatsAppBroadcastRejectedContactModel.source_file_name.asc(),
            WhatsAppBroadcastRejectedContactModel.sheet_name.asc(),
            WhatsAppBroadcastRejectedContactModel.row_number.asc(),
            WhatsAppBroadcastRejectedContactModel.id.asc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return WhatsAppRejectedContactListResponse(
        items=[_rejected_contact_response(model) for model in items_result.scalars().all()],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/groups/{group_id}/rejected-contacts/{rejected_contact_id}/resolve",
    response_model=WhatsAppBroadcastGroupDetailResponse,
)
async def resolve_broadcast_rejected_contact(
    group_id: uuid.UUID,
    rejected_contact_id: uuid.UUID,
    body: WhatsAppRejectedContactResolveRequest,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBroadcastGroupDetailResponse:
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

    rejected_result = await session.execute(
        select(WhatsAppBroadcastRejectedContactModel)
        .where(
            WhatsAppBroadcastRejectedContactModel.id == rejected_contact_id,
            WhatsAppBroadcastRejectedContactModel.broadcast_group_id == group.id,
        )
        .with_for_update()
    )
    rejected_contact = rejected_result.scalar_one_or_none()
    if not rejected_contact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rejected WhatsApp contact not found",
        )

    name = _clean_name(body.name)
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recipient name is required",
        )
    normalized_phone = _normalize_phone(body.phone_number)
    if not normalized_phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Use a 10-digit Indian mobile number, or an international number "
                "of 8 to 15 digits with its country code"
            ),
        )
    if not body.recipient_opt_in_confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirm this recipient agreed to receive WhatsApp updates",
        )

    existing_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id,
            WhatsAppBroadcastRecipientModel.normalized_phone_number == normalized_phone,
        )
        .with_for_update()
    )
    existing_recipient = existing_result.scalar_one_or_none()
    if existing_recipient and existing_recipient.removed_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That WhatsApp number is already in the valid recipient list",
        )

    if not existing_recipient:
        active_count_result = await session.execute(
            select(func.count())
            .select_from(WhatsAppBroadcastRecipientModel)
            .where(
                WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id,
                WhatsAppBroadcastRecipientModel.removed_at.is_(None),
            )
        )
        if int(active_count_result.scalar_one()) >= MAX_WHATSAPP_RECIPIENTS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "This WhatsApp list already contains the maximum of "
                    f"{MAX_WHATSAPP_RECIPIENTS} valid recipients"
                ),
            )

    now = datetime.now(tz=UTC)
    imported_fields = dict(rejected_contact.imported_fields or {})
    imported_fields.setdefault("source_file", rejected_contact.source_file_name)
    imported_fields.setdefault("source_sheet", rejected_contact.sheet_name)
    imported_fields.setdefault("source_row", str(rejected_contact.row_number))
    imported_fields = _safe_imported_fields(imported_fields)
    resolved_display_order = rejected_contact.display_order
    if resolved_display_order is None:
        resolved_display_order = await _next_roster_display_order(session, group.id)
    if existing_recipient:
        if existing_recipient.suppressed_by_roster_resolution_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This recipient is currently marked as replaced in a "
                    "linked passport group. Restore that replacement from "
                    "the group before adding them back."
                ),
            )
        existing_recipient.name = name
        existing_recipient.phone_number = body.phone_number.strip()
        existing_recipient.imported_fields = imported_fields
        if existing_recipient.display_order is None:
            existing_recipient.display_order = resolved_display_order
        existing_recipient.removed_at = None
        await session.execute(
            delete(WhatsAppRecipientMessageStateModel).where(
                WhatsAppRecipientMessageStateModel.recipient_id == existing_recipient.id,
            )
        )
    else:
        session.add(
            WhatsAppBroadcastRecipientModel(
                broadcast_group_id=group.id,
                agency_id=group.agency_id,
                name=name,
                phone_number=body.phone_number.strip(),
                normalized_phone_number=normalized_phone,
                imported_fields=imported_fields,
                display_order=resolved_display_order,
                created_at=now,
            )
        )

    await session.execute(
        delete(WhatsAppBroadcastRejectedContactModel).where(
            WhatsAppBroadcastRejectedContactModel.id == rejected_contact.id,
        )
    )
    group.recipient_opt_in_confirmed_at = group.recipient_opt_in_confirmed_at or now
    group.updated_at = now
    await session.flush()
    await suppress_active_replacement_recipients(
        session,
        agency_id=group.agency_id,
        broadcast_group_ids=[group.id],
        now=now,
    )
    await session.flush()
    return await _group_detail(session, group)


@router.post(
    "/groups/{group_id}/welcome-media",
    response_model=WhatsAppWelcomeMediaResponse,
)
async def upload_welcome_media(
    group_id: uuid.UUID,
    image: UploadFile = File(...),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppWelcomeMediaResponse:
    result = await session.execute(
        select(WhatsAppBroadcastGroupModel.id).where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )
    if image.content_type not in {"image/jpeg", "image/png"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use a JPEG or PNG image for the Welcome message",
        )

    payload = bytearray()
    while chunk := await image.read(WHATSAPP_UPLOAD_READ_CHUNK_BYTES):
        payload.extend(chunk)
        if len(payload) > MAX_WHATSAPP_WELCOME_IMAGE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="The Welcome image must be 5 MB or smaller",
            )
    try:
        validated = await asyncio.to_thread(
            UploadValidator().validate,
            content=bytes(payload),
            filename=image.filename,
            declared_content_type=image.content_type,
        )
    except ImageValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
            media_id = await upload_whatsapp_image(
                client=client,
                settings=settings,
                file_name=validated.filename,
                file_content=validated.content,
                content_type=validated.content_type,
            )
    except WhatsAppCloudApiError as exc:
        response_status = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if exc.transient or exc.code == "WHATSAPP_PROVIDER_NOT_CONFIGURED"
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=response_status,
            detail=str(exc),
        ) from exc

    return WhatsAppWelcomeMediaResponse(
        media_id=media_id,
        file_name=validated.filename,
        content_type=validated.content_type,
    )


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

    all_recipients = await _group_recipients(session, group.id)
    if not all_recipients:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This WhatsApp list has no recipients",
        )
    if body.recipient_id and body.resend_recipient_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose either a preview recipient or a resend recipient, not both",
        )
    recipients = _select_group_recipients(all_recipients, body.recipient_ids)
    if (
        body.resend_recipient_id
        and body.recipient_ids is not None
        and (len(recipients) != 1 or recipients[0].id != body.resend_recipient_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A resend preview can only target its selected recipient",
        )
    recipient = recipients[0]
    selected_recipient_id = body.resend_recipient_id or body.recipient_id
    if selected_recipient_id:
        selected = next(
            (item for item in recipients if item.id == selected_recipient_id),
            None,
        )
        if not selected:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Preview recipient not found in this WhatsApp list",
            )
        recipient = selected

    message_type = _as_message_type(body.message_type)
    snapshot: _WhatsAppComposerSnapshot | None = None
    content_source: Literal["default", "latest_group", "latest_recipient"] = "default"
    if body.resend_recipient_id:
        state_result = await session.execute(
            select(WhatsAppRecipientMessageStateModel).where(
                WhatsAppRecipientMessageStateModel.recipient_id == body.resend_recipient_id,
                WhatsAppRecipientMessageStateModel.message_type == message_type,
            )
        )
        target_state = state_result.scalar_one_or_none()
        if not target_state or (
            target_state.status not in WHATSAPP_ACCEPTED_STATUSES
            and target_state.status != "failed"
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only a sent or failed WhatsApp message can be opened here",
            )
        snapshot = await _latest_composer_snapshot(
            session,
            group_id=group.id,
            recipient_id=body.resend_recipient_id,
            message_type=message_type,
            accepted_only=target_state.status in WHATSAPP_ACCEPTED_STATUSES,
            include_failed=target_state.status == "failed",
            include_explicit_resends=True,
        )
        if snapshot:
            content_source = "latest_recipient"
    if snapshot is None and body.resend_recipient_id is None:
        snapshot = await _latest_composer_snapshot(
            session,
            group_id=group.id,
            message_type=message_type,
            accepted_only=True,
        )
        if snapshot:
            content_source = "latest_group"
    if body.resend_recipient_id is not None and snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No saved message is available to resend or retry for this recipient",
        )
    resolved_body = _merge_composer_snapshot(body, snapshot)
    support_contacts = _select_support_contacts(
        await _support_contacts_for_group(session, group.id),
        resolved_body.support_contact_ids,
        message_type=message_type,
    )
    (
        message_type,
        passport_intro,
        passport_link,
        message_content,
        recipient_name,
        rendered,
        header_parameters,
        parameters,
    ) = _message_values(
        group=group,
        recipient=recipient,
        support_contacts=support_contacts,
        body=resolved_body,
        preview=True,
    )
    if body.resend_recipient_id is not None:
        recipient_count = 1
        eligible_count = 1
        already_sent_count = 1 if target_state.status in WHATSAPP_ACCEPTED_STATUSES else 0
        in_progress_count = 0
        uncertain_count = 0
    else:
        recipient_count = len(recipients)
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
    template_name = _configured_template_name(message_type)
    return WhatsAppPreviewResponse(
        message_type=message_type,
        template_name=template_name,
        recipient_id=recipient.id,
        recipient_name=recipient_name,
        recipient_count=recipient_count,
        eligible_recipient_count=eligible_count,
        already_sent_count=already_sent_count,
        in_progress_count=in_progress_count,
        uncertain_recipient_count=uncertain_count,
        passport_intro=passport_intro,
        passport_link=(resolved_body.passport_link or "").strip() or None,
        message_content=message_content,
        header_image_id=(resolved_body.header_image_id or "").strip() or None,
        content_source=content_source,
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
    rejected_contacts_json: str = Form("[]"),
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
    try:
        manual_contacts = [
            WhatsAppRecipientInput(**item) for item in json.loads(contacts_json or "[]")
        ]
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid manual contact list"
        ) from exc
    rejected_contacts = _parse_rejected_contacts(rejected_contacts_json)

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
    normalized_contacts = _normalized_recipient_inputs(contacts) if contacts else {}
    if not normalized_contacts and not rejected_contacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add at least one valid or rejected WhatsApp contact",
        )
    if normalized_contacts and not recipient_opt_in_confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirm recipient WhatsApp opt-in before saving this list",
        )
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

    now = datetime.now(tz=UTC)
    group = WhatsAppBroadcastGroupModel(
        agency_id=current_user.agency_id,
        name=group_name,
        organizing_company_name=company_name,
        recipient_opt_in_confirmed_at=now if normalized_contacts else None,
        created_by_user_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    session.add(group)
    await session.flush()
    recipient_display_orders, rejected_display_orders = _new_roster_display_orders(
        normalized_contacts=normalized_contacts,
        rejected_contacts=rejected_contacts,
        existing_by_phone={},
        existing_by_fingerprint={},
        start_order=1,
    )
    for normalized, contact in normalized_contacts.items():
        session.add(
            WhatsAppBroadcastRecipientModel(
                broadcast_group_id=group.id,
                agency_id=current_user.agency_id,
                name=_clean_name(contact.name),
                phone_number=contact.phone_number.strip(),
                normalized_phone_number=normalized,
                imported_fields=contact.imported_fields,
                display_order=recipient_display_orders[normalized],
                created_at=now,
            )
        )
    _add_rejected_contact_models(
        session=session,
        group=group,
        contacts=rejected_contacts,
        existing_by_fingerprint={},
        now=now,
        display_orders_by_fingerprint=rejected_display_orders,
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
                created_at=now,
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
    rejected_contacts_json: str = Form("[]"),
    recipient_opt_in_confirmed: bool = Form(...),
    contacts_file: UploadFile | None = File(None),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBroadcastGroupDetailResponse:
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
    rejected_contacts = _parse_rejected_contacts(rejected_contacts_json)
    excel_contacts = await _parse_excel_contacts(contacts_file) if contacts_file else []
    contacts = manual_contacts + excel_contacts
    normalized_contacts = _normalized_recipient_inputs(contacts) if contacts else {}
    if not normalized_contacts and not rejected_contacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add at least one valid or rejected WhatsApp contact",
        )
    if normalized_contacts and not recipient_opt_in_confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirm recipient WhatsApp opt-in before adding contacts",
        )

    existing_by_phone: dict[str, WhatsAppBroadcastRecipientModel] = {}
    if normalized_contacts:
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
                detail=(
                    f"A WhatsApp list can contain at most {MAX_WHATSAPP_RECIPIENTS} recipients"
                ),
            )

    existing_rejected_by_fingerprint: dict[
        str,
        WhatsAppBroadcastRejectedContactModel,
    ] = {}
    if rejected_contacts:
        existing_rejected_result = await session.execute(
            select(WhatsAppBroadcastRejectedContactModel).where(
                WhatsAppBroadcastRejectedContactModel.broadcast_group_id == group.id,
            )
        )
        existing_rejected_contacts = list(existing_rejected_result.scalars().all())
        existing_rejected_by_fingerprint = {
            contact.fingerprint: contact for contact in existing_rejected_contacts
        }

    new_roster_count = sum(
        1 for normalized in normalized_contacts if normalized not in existing_by_phone
    ) + sum(
        1
        for contact in rejected_contacts
        if _rejected_contact_fingerprint(contact) not in existing_rejected_by_fingerprint
    )
    start_order = await _next_roster_display_order(session, group.id) if new_roster_count else 1
    recipient_display_orders, rejected_display_orders = _new_roster_display_orders(
        normalized_contacts=normalized_contacts,
        rejected_contacts=rejected_contacts,
        existing_by_phone=existing_by_phone,
        existing_by_fingerprint=existing_rejected_by_fingerprint,
        start_order=start_order,
    )

    now = datetime.now(tz=UTC)
    _activate_recipient_models(
        session=session,
        group=group,
        existing_by_phone=existing_by_phone,
        normalized_contacts=normalized_contacts,
        now=now,
        display_orders_by_phone=recipient_display_orders,
    )
    if rejected_contacts:
        _add_rejected_contact_models(
            session=session,
            group=group,
            contacts=rejected_contacts,
            existing_by_fingerprint=existing_rejected_by_fingerprint,
            now=now,
            display_orders_by_fingerprint=rejected_display_orders,
        )

    if normalized_contacts:
        group.recipient_opt_in_confirmed_at = group.recipient_opt_in_confirmed_at or now
    group.updated_at = now
    await session.flush()
    if normalized_contacts:
        await suppress_active_replacement_recipients(
            session,
            agency_id=group.agency_id,
            broadcast_group_ids=[group.id],
            now=now,
        )
        await session.flush()
    return await _group_detail(session, group)


@router.patch(
    "/groups/{group_id}/recipients/{recipient_id}",
    response_model=WhatsAppBroadcastGroupDetailResponse,
)
async def update_broadcast_recipient_phone(
    group_id: uuid.UUID,
    recipient_id: uuid.UUID,
    body: WhatsAppRecipientPhoneUpdateRequest,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBroadcastGroupDetailResponse:
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
    normalized_phone = _normalize_phone(body.phone_number)
    if not normalized_phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use 8 to 15 digits with an optional country code",
        )
    duplicate_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel.id).where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id,
            WhatsAppBroadcastRecipientModel.normalized_phone_number == normalized_phone,
            WhatsAppBroadcastRecipientModel.id != recipient.id,
        )
    )
    if duplicate_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That WhatsApp number already belongs to another recipient in this list",
        )
    active_state_result = await session.execute(
        select(WhatsAppRecipientMessageStateModel.id).where(
            WhatsAppRecipientMessageStateModel.recipient_id == recipient.id,
            WhatsAppRecipientMessageStateModel.status.in_(
                WHATSAPP_IN_PROGRESS_STATUSES | WHATSAPP_UNCERTAIN_STATUSES
            ),
        )
    )
    if active_state_result.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Wait until the current delivery finishes, or review its unknown "
                "outcome, before changing this number"
            ),
        )
    active_resend_result = await session.execute(
        select(WhatsAppMessageLogModel.id).where(
            WhatsAppMessageLogModel.recipient_id == recipient.id,
            WhatsAppMessageLogModel.is_explicit_resend.is_(True),
            WhatsAppMessageLogModel.status.in_(WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES),
        )
    )
    if active_resend_result.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Wait until the current resend finishes, or review its unknown "
                "outcome, before changing this number"
            ),
        )
    if normalized_phone == recipient.normalized_phone_number:
        return await _group_detail(session, group)

    now = datetime.now(tz=UTC)
    recipient.phone_number = body.phone_number.strip()
    recipient.normalized_phone_number = normalized_phone
    await session.execute(
        update(WhatsAppRecipientMessageStateModel)
        .where(WhatsAppRecipientMessageStateModel.recipient_id == recipient.id)
        .values(
            status="failed",
            batch_id=None,
            submitted_at=None,
            provider_status_at=None,
            status_updated_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    group.updated_at = now
    await session.flush()
    await suppress_active_replacement_recipients(
        session,
        agency_id=group.agency_id,
        broadcast_group_ids=[group.id],
        now=now,
    )
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
    if await active_replacement_resolution_id_for_recipient(
        session,
        recipient=recipient,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This recipient is marked as replaced in a linked passport "
                "group. Restore that replacement before sending to them."
            ),
        )
    if body.recipient_ids is not None and set(body.recipient_ids) != {recipient.id}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A resend can only target its selected recipient",
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
    is_retry = bool(delivery_state and delivery_state.status == "failed")
    if not delivery_state or (
        delivery_state.status not in WHATSAPP_ACCEPTED_STATUSES and not is_retry
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Only a successfully submitted message can be resent, and only a "
                "failed message can be retried."
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
            WhatsAppMessageLogModel.status.in_(WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES),
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
            WhatsAppMessageLogModel.status.in_(
                WHATSAPP_ACCEPTED_STATUSES | ({"failed"} if is_retry else set())
            ),
        )
        .order_by(
            WhatsAppMessageLogModel.created_at.desc(),
            WhatsAppMessageLogModel.status_updated_at.desc(),
        )
        .limit(1)
    )
    source_log = source_result.scalar_one_or_none()
    if not source_log:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The previously saved WhatsApp message could not be found",
        )
    try:
        source_snapshot = _composer_snapshot_from_log(source_log)
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
    configured_template_name = _configured_template_name(message_type)
    merged_body = _merge_composer_snapshot(body, source_snapshot)
    header_image_id = _resolve_send_header_image(
        message_type,
        merged_body.header_image_id,
        resend=True,
    )
    support_contacts = _select_support_contacts(
        await _support_contacts_for_group(session, group.id),
        merged_body.support_contact_ids,
        message_type=message_type,
    )
    if message_type == "passport_link" and not support_contacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add customer support contacts before resending this message",
        )
    message_content = _resolve_send_message_content(
        message_type,
        merged_body.message_content,
        group_name=group.name,
    )
    passport_intro = (
        _resolve_send_passport_intro(
            merged_body.passport_intro,
            group_name=group.name,
        )
        if message_type == "passport_link"
        else None
    )
    passport_link = (
        _validate_passport_link(merged_body.passport_link)
        if message_type == "passport_link"
        else None
    )
    resolved_body = WhatsAppSendRequest(
        message_type=message_type,
        passport_intro=passport_intro,
        passport_link=passport_link,
        message_content=message_content,
        header_image_id=header_image_id,
        recipient_ids=merged_body.recipient_ids,
        support_contact_ids=merged_body.support_contact_ids,
    )
    (
        _,
        _,
        _,
        _,
        _,
        rendered_message,
        header_parameters,
        parameters,
    ) = _message_values(
        group=group,
        recipient=recipient,
        support_contacts=support_contacts,
        body=resolved_body,
    )
    template_name = configured_template_name.strip()
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
        rendered_message=rendered_message,
        header_parameter_values=header_parameters,
        template_parameter_values=parameters,
        is_explicit_resend=not is_retry,
        created_at=now,
    )
    session.add(resend_log)
    if is_retry:
        delivery_state.status = "queued"
        delivery_state.batch_id = batch_id
        delivery_state.submitted_at = None
        delivery_state.provider_status_at = None
        delivery_state.status_updated_at = now
        delivery_state.updated_at = now
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A resend of this message is already active for this recipient.",
        ) from exc

    await AuditLogRepository(session).record(
        action=(
            "whatsapp_recipient_message_retry_requested"
            if is_retry
            else "whatsapp_recipient_message_resend_requested"
        ),
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
                "message_content": (
                    parameters[0]
                    if message_type in {"welcome", "reminder"}
                    else parameters[2]
                ),
                "passport_intro": parameters[0] if message_type == "passport_link" else None,
                "passport_link": parameters[1] if message_type == "passport_link" else None,
                "header_image_id": (header_parameters[0] if header_parameters else None),
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
        if is_retry:
            delivery_state.status = "failed"
            delivery_state.batch_id = None
            delivery_state.status_updated_at = resend_log.status_updated_at
            delivery_state.updated_at = resend_log.status_updated_at
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
    active_replacement_result = await session.execute(
        select(PassportRosterResolutionModel.id)
        .join(
            WhatsAppBroadcastRecipientModel,
            WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id
            == PassportRosterResolutionModel.id,
        )
        .where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id,
            PassportRosterResolutionModel.status == "active",
            PassportRosterResolutionModel.resolution_type == "replacement",
        )
        .limit(1)
    )
    if active_replacement_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This broadcast contains a person marked as replaced in a "
                "linked passport group. Restore that replacement before "
                "deleting the broadcast."
            ),
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
    if int(processing_result.scalar_one()) > 0 or int(explicit_processing_result.scalar_one()) > 0:
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

    all_recipients = await _group_recipients(session, group.id)
    if not all_recipients:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This WhatsApp list has no recipients",
        )
    message_type = _as_message_type(body.message_type)
    recipients = _select_group_recipients(all_recipients, body.recipient_ids)
    support_contacts = await _support_contacts_for_group(session, group.id)
    snapshot = await _latest_composer_snapshot(
        session,
        group_id=group.id,
        message_type=message_type,
        accepted_only=True,
    )
    merged_body = _merge_composer_snapshot(body, snapshot)
    support_contacts = _select_support_contacts(
        support_contacts,
        merged_body.support_contact_ids,
        message_type=message_type,
    )
    if message_type == "passport_link" and not support_contacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add customer support contacts before sending this message",
        )
    header_image_id = _resolve_send_header_image(
        message_type,
        merged_body.header_image_id,
    )
    message_content = _resolve_send_message_content(
        message_type,
        merged_body.message_content,
        group_name=group.name,
    )
    passport_intro = (
        _resolve_send_passport_intro(
            merged_body.passport_intro,
            group_name=group.name,
        )
        if message_type == "passport_link"
        else None
    )
    settings = get_settings()
    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp Cloud API credentials are incomplete",
        )
    template_name = _configured_template_name(message_type)
    if not template_name.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"WhatsApp {message_type} template name is not configured",
        )

    passport_link = (
        _validate_passport_link(merged_body.passport_link)
        if message_type == "passport_link"
        else None
    )
    resolved_body = WhatsAppSendRequest(
        message_type=message_type,
        passport_intro=passport_intro,
        passport_link=passport_link,
        message_content=message_content,
        header_image_id=header_image_id,
        recipient_ids=merged_body.recipient_ids,
        support_contact_ids=merged_body.support_contact_ids,
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
        (
            _,
            _,
            _,
            _,
            _,
            rendered,
            header_parameters,
            parameters,
        ) = _message_values(
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
                "passport_intro": passport_intro,
                "passport_link": passport_link,
                "header_image_id": resolved_body.header_image_id,
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
