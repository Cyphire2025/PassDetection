"""Message composition and reusable snapshot helpers for WhatsApp routes."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSupportContactModel,
    WhatsAppMessageLogModel,
)
from app.presentation.api.v1.routes.whatsapp_contact_support import _clean_name
from app.presentation.api.v1.routes.whatsapp_delivery_support import (
    WHATSAPP_ACCEPTED_STATUSES,
    WHATSAPP_IN_PROGRESS_STATUSES,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppSendRequest

logger = logging.getLogger("app.presentation.api.v1.routes.whatsapp")


@dataclass(frozen=True, slots=True)
class _WhatsAppComposerSnapshot:
    log: WhatsAppMessageLogModel
    passport_intro: str | None
    passport_link: str | None
    message_content: str
    header_image_id: str | None


def _as_message_type(value: str) -> WhatsAppMessageType:
    if value == "welcome":
        return "welcome"
    if value == "reminder":
        return "reminder"
    return "passport_link"


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
