"""WhatsApp broadcast management routes."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zipfile import BadZipFile

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
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.message_templates import (
    WhatsAppMessageType,
    default_message_content,
    format_support_contacts,
    render_message,
    template_header_parameters,
    template_parameters,
)
from app.core.config.settings import get_settings
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSupportContactModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.dependencies.auth import require_role

router = APIRouter()
logger = logging.getLogger(__name__)

WHATSAPP_ROLES = [UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER, UserRole.AGENCY_STAFF]
PHONE_RE = re.compile(r"(?:\+|00)?\d[\d\s().-]{7,}\d")


class WhatsAppRecipientInput(BaseModel):
    name: str | None = None
    phone_number: str = Field(min_length=6)


class WhatsAppSupportContactInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    phone_number: str = Field(min_length=6, max_length=64)


class WhatsAppRecipientResponse(BaseModel):
    id: uuid.UUID
    name: str | None
    phone_number: str
    normalized_phone_number: str


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


class WhatsAppPreviewRequest(WhatsAppSendRequest):
    recipient_id: uuid.UUID | None = None


class WhatsAppPreviewResponse(BaseModel):
    message_type: str
    template_name: str
    recipient_id: uuid.UUID
    recipient_name: str
    recipient_count: int
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
        for change in entry.get("changes", []) if isinstance(entry, dict) and isinstance(entry.get("changes"), list) else []:
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
    message = first.get("message") or first.get("title") or first.get("details")
    return str(message)[:2000] if message else None


@router.get("/webhook", response_class=PlainTextResponse)
async def verify_whatsapp_webhook(
    mode: str | None = Query(default=None, alias="hub.mode"),
    verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> PlainTextResponse:
    settings = get_settings()
    expected_token = (settings.whatsapp_webhook_verify_token or "").strip()
    if not expected_token:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="WhatsApp webhook verify token is not configured")
    if mode == "subscribe" and challenge and hmac.compare_digest(verify_token or "", expected_token):
        return PlainTextResponse(challenge, status_code=status.HTTP_200_OK)
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="WhatsApp webhook verification failed")


@router.post("/webhook", response_model=WhatsAppWebhookAck)
async def receive_whatsapp_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppWebhookAck:
    raw_body = await request.body()
    if not _verify_meta_signature(raw_body, x_hub_signature_256):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid WhatsApp webhook signature")
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid WhatsApp webhook JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid WhatsApp webhook payload")

    provider_statuses: dict[str, tuple[str, str | None]] = {}
    received_messages = 0
    for value in _iter_webhook_values(payload):
        for status_payload in value.get("statuses", []) if isinstance(value.get("statuses"), list) else []:
            if not isinstance(status_payload, dict):
                continue
            provider_id = status_payload.get("id")
            provider_status = status_payload.get("status")
            if provider_id and provider_status:
                provider_statuses[str(provider_id)] = (str(provider_status)[:32], _extract_status_error(status_payload))
        messages = value.get("messages")
        if isinstance(messages, list):
            received_messages += len(messages)

    processed_statuses = 0
    for provider_id, (provider_status, error_message) in provider_statuses.items():
        result = await session.execute(
            select(WhatsAppMessageLogModel).where(WhatsAppMessageLogModel.provider_message_id == provider_id)
        )
        for log in result.scalars().all():
            log.status = provider_status
            log.status_updated_at = datetime.now(tz=UTC)
            if error_message:
                log.error_message = error_message
            processed_statuses += 1
    if processed_statuses:
        await session.commit()

    if received_messages:
        logger.info("Received %s WhatsApp inbound message webhook event(s)", received_messages)
    return WhatsAppWebhookAck(processed_statuses=processed_statuses, received_messages=received_messages)


def _agency_filter(current_user: User) -> list[Any]:
    if current_user.role == UserRole.SUPER_ADMIN:
        return []
    if not current_user.agency_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User is not assigned to an agency")
    return [WhatsAppBroadcastGroupModel.agency_id == current_user.agency_id]


def _normalize_phone(raw: str) -> str | None:
    value = (raw or "").strip()
    if not value:
        return None
    has_plus = value.startswith("+")
    digits = re.sub(r"\D", "", value)
    if not digits:
        return None
    if value.startswith("00"):
        digits = digits[2:]
    if has_plus or len(digits) > 10:
        normalized = f"+{digits}"
    elif len(digits) == 10:
        normalized = f"+91{digits}"
    else:
        return None
    if len(re.sub(r"\D", "", normalized)) < 8:
        return None
    return normalized


def _clean_name(value: Any) -> str | None:
    if value is None:
        return None
    name = re.sub(r"\s+", " ", str(value)).strip()
    return name[:255] or None


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


def _resolve_message_content(message_type: WhatsAppMessageType, value: str | None) -> str:
    if value is None:
        return default_message_content(message_type)
    return value.strip()


def _resolve_send_message_content(
    message_type: WhatsAppMessageType,
    value: str | None,
) -> str:
    content = _resolve_message_content(message_type, value)
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


def _parse_excel_contacts(upload: UploadFile) -> list[WhatsAppRecipientInput]:
    suffix = Path(upload.filename or "contacts.xlsx").suffix.lower() or ".xlsx"
    if suffix not in {".xlsx", ".xlsm"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload an .xlsx or .xlsm contact file",
        )
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(upload.file.read())
        tmp_path = Path(tmp.name)

    try:
        try:
            workbook = load_workbook(tmp_path, read_only=True, data_only=True)
            sheet = workbook.active
            rows = list(sheet.iter_rows(values_only=True))
            workbook.close()
        except (BadZipFile, InvalidFileException, OSError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The uploaded Excel contact file could not be read",
            ) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    if not rows:
        return []

    header = [str(cell or "").strip().lower() for cell in rows[0]]
    phone_columns = [idx for idx, label in enumerate(header) if any(term in label for term in ("phone", "mobile", "whatsapp", "contact"))]
    name_columns = [idx for idx, label in enumerate(header) if any(term in label for term in ("name", "client", "passenger"))]
    data_rows = rows[1:] if phone_columns else rows

    contacts: list[WhatsAppRecipientInput] = []
    seen: set[str] = set()
    for row in data_rows:
        row_values = list(row)
        candidates: list[tuple[str | None, str]] = []
        if phone_columns:
            name = next((_clean_name(row_values[idx]) for idx in name_columns if idx < len(row_values) and _clean_name(row_values[idx])), None)
            for idx in phone_columns:
                if idx < len(row_values) and row_values[idx] is not None:
                    candidates.append((name, str(row_values[idx])))
        else:
            row_text = " ".join(str(cell) for cell in row_values if cell is not None)
            for match in PHONE_RE.findall(row_text):
                candidates.append((None, match))

        for name, phone in candidates:
            normalized = _normalize_phone(phone)
            if normalized and normalized not in seen:
                seen.add(normalized)
                contacts.append(WhatsAppRecipientInput(name=name, phone_number=phone))
    return contacts


def _recipient_response(model: WhatsAppBroadcastRecipientModel) -> WhatsAppRecipientResponse:
    return WhatsAppRecipientResponse(
        id=model.id,
        name=model.name,
        phone_number=model.phone_number,
        normalized_phone_number=model.normalized_phone_number,
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


async def _group_detail(session: AsyncSession, group: WhatsAppBroadcastGroupModel) -> WhatsAppBroadcastGroupDetailResponse:
    recipients_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id)
        .order_by(WhatsAppBroadcastRecipientModel.name.asc().nullslast(), WhatsAppBroadcastRecipientModel.created_at.asc())
    )
    recipients = list(recipients_result.scalars().all())
    support_contacts = await _support_contacts_for_group(session, group.id)
    return WhatsAppBroadcastGroupDetailResponse(
        id=group.id,
        name=group.name,
        organizing_company_name=group.organizing_company_name,
        recipient_count=len(recipients),
        recipient_opt_in_confirmed=group.recipient_opt_in_confirmed_at is not None,
        created_at=group.created_at,
        updated_at=group.updated_at,
        recipients=[_recipient_response(recipient) for recipient in recipients],
        support_contacts=[_support_contact_response(contact) for contact in support_contacts],
    )


async def _group_recipients(
    session: AsyncSession,
    group_id: uuid.UUID,
) -> list[WhatsAppBroadcastRecipientModel]:
    result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(WhatsAppBroadcastRecipientModel.broadcast_group_id == group_id)
        .order_by(
            WhatsAppBroadcastRecipientModel.name.asc().nullslast(),
            WhatsAppBroadcastRecipientModel.created_at.asc(),
        )
    )
    return list(result.scalars().all())


def _message_values(
    *,
    group: WhatsAppBroadcastGroupModel,
    recipient: WhatsAppBroadcastRecipientModel,
    support_contacts: list[WhatsAppBroadcastSupportContactModel],
    body: WhatsAppSendRequest,
    preview: bool = False,
) -> tuple[WhatsAppMessageType, str, str, str, list[str], list[str]]:
    message_type = _as_message_type(body.message_type)
    message_content = _resolve_message_content(message_type, body.message_content)
    passport_link = (
        _validate_passport_link(body.passport_link, allow_placeholder=preview)
        if message_type == "passport_link"
        else None
    )
    recipient_name = _clean_name(recipient.name) or "Guest"
    company_name = _clean_name(group.organizing_company_name) or "your organisation"
    support_block = format_support_contacts(
        [(contact.name, contact.phone_number) for contact in support_contacts]
    )
    rendered = render_message(
        message_type=message_type,
        recipient_name=recipient_name,
        group_name=group.name,
        organizing_company_name=company_name,
        support_contacts=support_block,
        message_content=message_content,
        passport_link=passport_link,
    )
    header_parameters = template_header_parameters(
        message_type=message_type,
        recipient_name=recipient_name,
    )
    parameters = template_parameters(
        message_type=message_type,
        recipient_name=recipient_name,
        group_name=group.name,
        organizing_company_name=company_name,
        support_contacts=support_block,
        message_content=message_content,
        passport_link=passport_link,
    )
    return message_type, message_content, recipient_name, rendered, header_parameters, parameters


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
            WhatsAppBroadcastRecipientModel.broadcast_group_id == WhatsAppBroadcastGroupModel.id,
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
        select(WhatsAppBroadcastGroupModel).where(WhatsAppBroadcastGroupModel.id == group_id, *_agency_filter(current_user))
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WhatsApp broadcast group not found")
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
    message_type, message_content, recipient_name, rendered, header_parameters, parameters = _message_values(
        group=group,
        recipient=recipient,
        support_contacts=support_contacts,
        body=body,
        preview=True,
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
        message_content=message_content,
        rendered_message=rendered,
        header_parameter_values=header_parameters,
        parameter_values=parameters,
    )


@router.post("/groups", response_model=WhatsAppBroadcastGroupDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_broadcast_group(
    name: str = Form(...),
    organizing_company_name: str = Form(...),
    contacts_json: str = Form("[]"),
    support_contacts_json: str = Form("[]"),
    recipient_opt_in_confirmed: bool = Form(...),
    contacts_file: UploadFile | None = File(None),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBroadcastGroupDetailResponse:
    if not current_user.agency_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User is not assigned to an agency")
    group_name = name.strip()
    if not group_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Group name is required")
    if len(group_name) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Group name must be 100 characters or fewer",
        )
    company_name = _clean_required_name(organizing_company_name, "Organising company name")
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
        manual_contacts = [WhatsAppRecipientInput(**item) for item in json.loads(contacts_json or "[]")]
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid manual contact list") from exc

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

    excel_contacts = _parse_excel_contacts(contacts_file) if contacts_file else []
    contacts = manual_contacts + excel_contacts
    normalized_contacts: dict[str, WhatsAppRecipientInput] = {}
    for contact in contacts:
        normalized = _normalize_phone(contact.phone_number)
        if normalized and normalized not in normalized_contacts:
            normalized_contacts[normalized] = contact
    if not normalized_contacts:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Add at least one valid WhatsApp number")
    if len(normalized_contacts) > 500:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A WhatsApp list can contain at most 500 recipients",
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


@router.delete("/groups/{group_id}", status_code=status.HTTP_200_OK)
async def delete_broadcast_group(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, bool]:
    result = await session.execute(
        select(WhatsAppBroadcastGroupModel).where(WhatsAppBroadcastGroupModel.id == group_id, *_agency_filter(current_user))
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WhatsApp broadcast group not found")
    await session.execute(delete(WhatsAppBroadcastGroupModel).where(WhatsAppBroadcastGroupModel.id == group.id))
    return {"deleted": True}


@router.post("/groups/{group_id}/send", response_model=WhatsAppSendResponse)
async def send_broadcast_message(
    group_id: uuid.UUID,
    body: WhatsAppSendRequest,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppSendResponse:
    result = await session.execute(
        select(WhatsAppBroadcastGroupModel).where(WhatsAppBroadcastGroupModel.id == group_id, *_agency_filter(current_user))
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WhatsApp broadcast group not found")
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
    message_content = _resolve_send_message_content(message_type, body.message_content)
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
        _validate_passport_link(body.passport_link)
        if message_type == "passport_link"
        else None
    )
    resolved_body = WhatsAppSendRequest(
        message_type=message_type,
        passport_link=passport_link,
        message_content=message_content,
    )
    batch_id = uuid.uuid4()
    results: list[WhatsAppSendResult] = []
    for recipient in recipients:
        _, _, _, rendered, _, _ = _message_values(
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
                status_updated_at=datetime.now(tz=UTC),
                provider_message_id=None,
                error_message=None,
                template_name=template_name,
                rendered_message=rendered,
                created_at=datetime.now(tz=UTC),
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
        error_message = f"WhatsApp worker queue is unavailable: {exc}"[:2000]
        logs_result = await session.execute(
            select(WhatsAppMessageLogModel).where(
                WhatsAppMessageLogModel.batch_id == batch_id
            )
        )
        for log in logs_result.scalars().all():
            log.status = "failed"
            log.status_updated_at = datetime.now(tz=UTC)
            log.error_message = error_message
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
            if item.status not in queued_statuses | successful_statuses
        ),
        results=results,
    )
