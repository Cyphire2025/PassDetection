"""WhatsApp broadcast management routes."""

from __future__ import annotations

import json
import hashlib
import hmac
import logging
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import PlainTextResponse
from openpyxl import load_workbook
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
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


class WhatsAppRecipientResponse(BaseModel):
    id: uuid.UUID
    name: str | None
    phone_number: str
    normalized_phone_number: str


class WhatsAppBroadcastGroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    recipient_count: int
    created_at: datetime
    updated_at: datetime


class WhatsAppBroadcastGroupDetailResponse(WhatsAppBroadcastGroupResponse):
    recipients: list[WhatsAppRecipientResponse]


class WhatsAppSendRequest(BaseModel):
    message_type: str = Field(pattern="^(welcome|passport_link)$")
    passport_link: str | None = None


class WhatsAppSendResult(BaseModel):
    recipient_id: uuid.UUID
    phone_number: str
    status: str
    provider_message_id: str | None = None
    error_message: str | None = None


class WhatsAppSendResponse(BaseModel):
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


def _parse_excel_contacts(upload: UploadFile) -> list[WhatsAppRecipientInput]:
    suffix = Path(upload.filename or "contacts.xlsx").suffix or ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(upload.file.read())
        tmp_path = Path(tmp.name)

    try:
        workbook = load_workbook(tmp_path, read_only=True, data_only=True)
        sheet = workbook.active
        rows = list(sheet.iter_rows(values_only=True))
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


async def _post_whatsapp_message(payload: dict[str, Any]) -> str | None:
    settings = get_settings()
    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="WhatsApp is not configured. Set WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID.",
        )

    url = f"https://graph.facebook.com/{settings.whatsapp_api_version}/{settings.whatsapp_phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(url, json=payload, headers=headers)
    data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    if response.status_code >= 400:
        message = data.get("error", {}).get("message") if isinstance(data, dict) else None
        raise RuntimeError(message or f"WhatsApp API returned {response.status_code}")
    messages = data.get("messages") if isinstance(data, dict) else None
    return messages[0].get("id") if messages and isinstance(messages, list) else None


async def _send_whatsapp_text(to_number: str, body: str) -> tuple[str, str | None]:
    api_to_number = to_number.lstrip("+")
    provider_id = await _post_whatsapp_message(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": api_to_number,
            "type": "text",
            "text": {"preview_url": True, "body": body},
        }
    )
    return "submitted", provider_id


def _text_parameter(value: str) -> dict[str, str]:
    return {"type": "text", "text": value}


async def _send_whatsapp_template(to_number: str, template_name: str, parameters: list[str] | None = None) -> tuple[str, str | None]:
    settings = get_settings()
    api_to_number = to_number.lstrip("+")
    template: dict[str, Any] = {
        "name": template_name,
        "language": {"code": settings.whatsapp_template_language},
    }
    if parameters:
        template["components"] = [
            {
                "type": "body",
                "parameters": [_text_parameter(parameter) for parameter in parameters],
            }
        ]
    provider_id = await _post_whatsapp_message(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": api_to_number,
            "type": "template",
            "template": template,
        }
    )
    return "submitted", provider_id


def _recipient_response(model: WhatsAppBroadcastRecipientModel) -> WhatsAppRecipientResponse:
    return WhatsAppRecipientResponse(
        id=model.id,
        name=model.name,
        phone_number=model.phone_number,
        normalized_phone_number=model.normalized_phone_number,
    )


async def _group_detail(session: AsyncSession, group: WhatsAppBroadcastGroupModel) -> WhatsAppBroadcastGroupDetailResponse:
    recipients_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id)
        .order_by(WhatsAppBroadcastRecipientModel.name.asc().nullslast(), WhatsAppBroadcastRecipientModel.created_at.asc())
    )
    recipients = list(recipients_result.scalars().all())
    return WhatsAppBroadcastGroupDetailResponse(
        id=group.id,
        name=group.name,
        recipient_count=len(recipients),
        created_at=group.created_at,
        updated_at=group.updated_at,
        recipients=[_recipient_response(recipient) for recipient in recipients],
    )


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
            recipient_count=count,
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


@router.post("/groups", response_model=WhatsAppBroadcastGroupDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_broadcast_group(
    name: str = Form(...),
    contacts_json: str = Form("[]"),
    contacts_file: UploadFile | None = File(None),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBroadcastGroupDetailResponse:
    if not current_user.agency_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User is not assigned to an agency")
    group_name = name.strip()
    if not group_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Group name is required")

    try:
        manual_contacts = [WhatsAppRecipientInput(**item) for item in json.loads(contacts_json or "[]")]
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid manual contact list") from exc

    excel_contacts = _parse_excel_contacts(contacts_file) if contacts_file else []
    contacts = manual_contacts + excel_contacts
    normalized_contacts: dict[str, WhatsAppRecipientInput] = {}
    for contact in contacts:
        normalized = _normalize_phone(contact.phone_number)
        if normalized and normalized not in normalized_contacts:
            normalized_contacts[normalized] = contact
    if not normalized_contacts:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Add at least one valid WhatsApp number")

    group = WhatsAppBroadcastGroupModel(
        agency_id=current_user.agency_id,
        name=group_name,
        created_by_user_id=current_user.id,
        created_at=datetime.now(tz=timezone.utc),
        updated_at=datetime.now(tz=timezone.utc),
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
                created_at=datetime.now(tz=timezone.utc),
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
    if body.message_type == "passport_link" and not body.passport_link:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Passport link is required")

    recipients_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel).where(WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id)
    )
    recipients = list(recipients_result.scalars().all())
    results: list[WhatsAppSendResult] = []
    settings = get_settings()
    for recipient in recipients:
        display_name = recipient.name or "Guest"
        provider_message_id = None
        error_message = None
        send_status = "submitted"
        try:
            if body.message_type == "welcome":
                send_status, provider_message_id = await _send_whatsapp_template(
                    recipient.normalized_phone_number,
                    settings.whatsapp_welcome_template_name,
                    [display_name],
                )
            else:
                send_status, provider_message_id = await _send_whatsapp_template(
                    recipient.normalized_phone_number,
                    settings.whatsapp_passport_link_template_name,
                    [display_name, body.passport_link or ""],
                )
        except Exception as exc:  # noqa: BLE001 - log per-recipient provider errors without stopping the batch.
            send_status = "failed"
            error_message = str(exc)

        session.add(
            WhatsAppMessageLogModel(
                broadcast_group_id=group.id,
                recipient_id=recipient.id,
                agency_id=recipient.agency_id,
                message_type=body.message_type,
                status=send_status,
                provider_message_id=provider_message_id,
                error_message=error_message,
                created_at=datetime.now(tz=timezone.utc),
            )
        )
        results.append(
            WhatsAppSendResult(
                recipient_id=recipient.id,
                phone_number=recipient.normalized_phone_number,
                status=send_status,
                provider_message_id=provider_message_id,
                error_message=error_message,
            )
        )
    await session.flush()
    return WhatsAppSendResponse(
        sent=sum(1 for item in results if item.status == "submitted"),
        failed=sum(1 for item in results if item.status != "submitted"),
        results=results,
    )
