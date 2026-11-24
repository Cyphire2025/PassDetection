"""Current message fields, template links and required-input validation."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException, status

from app.application.use_cases.whatsapp.message_templates import (
    WhatsAppMessageType,
    default_message_content,
    passport_link_intro,
    validate_group_invite_link,
)
from app.application.use_cases.whatsapp.template_text import normalize_template_text
from app.core.config.settings import Settings
from app.infrastructure.database.models import WhatsAppMessageLogModel
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppSendRequest


def _as_message_type(value: str) -> WhatsAppMessageType:
    if value == "update":
        return "update"
    if value == "group_invite":
        return "group_invite"
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
    return normalize_template_text(value) if message_type == "reminder" else value.strip()


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
    if message_type in {"reminder", "update"}:
        return None
    media_id = (value or "").strip()
    if media_id:
        return media_id
    action = "resending" if resend else "sending"
    label = {
        "welcome": "Welcome",
        "passport_link": "Passport Link",
        "group_invite": "Group Invite",
    }[message_type]
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


def _validate_group_invite_link(value: str | None, *, allow_placeholder: bool = False) -> str:
    link = (value or "").strip()
    if not link and allow_placeholder:
        return "[WhatsApp group invite link]"
    try:
        return validate_group_invite_link(link)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _resolve_message_links(
    body: WhatsAppSendRequest,
    *,
    preview: bool = False,
) -> tuple[str | None, str | None]:
    """Validate only the link belonging to the selected template."""
    if body.message_type == "passport_link":
        return _validate_passport_link(body.passport_link, allow_placeholder=preview), None
    if body.message_type == "group_invite":
        return None, _validate_group_invite_link(body.group_invite_link, allow_placeholder=preview)
    return None, None


def _preview_message_metadata(
    body: WhatsAppSendRequest,
    header_parameters: list[str],
) -> dict[str, Any]:
    """Expose editable links and the actual template header without placeholders."""
    return {
        "passport_link": (body.passport_link or "").strip() or None,
        "group_invite_link": (
            (body.group_invite_link or "").strip() or None
            if body.message_type == "group_invite"
            else None
        ),
        "header_image_id": header_parameters[0] if header_parameters else None,
    }


def _snapshot_template_language(
    settings: Settings,
    message_type: str,
    source: WhatsAppMessageLogModel | None = None,
) -> str | None:
    """Keep saved languages stable and freeze the invite's independent locale."""
    saved_language: str | None = getattr(source, "template_language", None)
    if saved_language:
        return saved_language
    if message_type == "group_invite":
        return settings.whatsapp_group_invite_template_language
    return None


# Keep existing public imports and pickle identities.
_as_message_type.__module__ = "app.presentation.api.v1.routes.whatsapp_composer_support"
_resolve_message_content.__module__ = "app.presentation.api.v1.routes.whatsapp_composer_support"
_resolve_send_message_content.__module__ = (
    "app.presentation.api.v1.routes.whatsapp_composer_support"
)
_resolve_passport_intro.__module__ = "app.presentation.api.v1.routes.whatsapp_composer_support"
_resolve_send_passport_intro.__module__ = "app.presentation.api.v1.routes.whatsapp_composer_support"
_resolve_send_header_image.__module__ = "app.presentation.api.v1.routes.whatsapp_composer_support"
_validate_passport_link.__module__ = "app.presentation.api.v1.routes.whatsapp_composer_support"
_validate_group_invite_link.__module__ = "app.presentation.api.v1.routes.whatsapp_composer_support"
_resolve_message_links.__module__ = "app.presentation.api.v1.routes.whatsapp_composer_support"
_preview_message_metadata.__module__ = "app.presentation.api.v1.routes.whatsapp_composer_support"
_snapshot_template_language.__module__ = "app.presentation.api.v1.routes.whatsapp_composer_support"
