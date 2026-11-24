"""Approved template composition delegates all HTTP outcome handling."""

from __future__ import annotations

from typing import Any

import httpx

from app.application.use_cases.whatsapp.document_templates import (
    validate_document_template_parameters,
)
from app.application.use_cases.whatsapp.message_templates import (
    WhatsAppMessageType,
    validate_template_parameters,
)
from app.application.use_cases.whatsapp.qr_templates import validate_qr_template_parameters
from app.application.use_cases.whatsapp.template_text import normalize_template_text
from app.core.config.settings import Settings
from app.infrastructure.whatsapp.provider_errors import (
    DOCUMENT_TEMPLATE_DIAGNOSTICS,
    QR_TEMPLATE_DIAGNOSTICS,
    WhatsAppCloudApiError,
)
from app.infrastructure.whatsapp.provider_payloads import (
    _document_parameter,
    _image_parameter,
    _text_parameter,
)
from app.infrastructure.whatsapp.provider_transport import _send_whatsapp_template_payload


async def send_whatsapp_document_template(
    *,
    client: httpx.AsyncClient,
    settings: Settings,
    to_number: str,
    template_name: str,
    media_id: str,
    filename: str,
    parameters: list[str],
) -> str:
    """Send an approved template with a private document header."""

    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        raise WhatsAppCloudApiError(
            "WhatsApp Cloud API credentials are incomplete",
            code="WHATSAPP_PROVIDER_NOT_CONFIGURED",
        )
    try:
        validate_document_template_parameters(parameters)
    except ValueError as exc:
        raise WhatsAppCloudApiError(
            f"Invalid WhatsApp document template payload: {exc}",
            code="WHATSAPP_TEMPLATE_PAYLOAD_INVALID",
        ) from exc

    components: list[dict[str, Any]] = [
        {
            "type": "header",
            "parameters": [_document_parameter(media_id, filename)],
        },
        {
            "type": "body",
            "parameters": [_text_parameter(parameter) for parameter in parameters],
        },
    ]
    return await _send_whatsapp_template_payload(
        client=client,
        settings=settings,
        to_number=to_number,
        template_name=template_name,
        language_code=settings.whatsapp_template_language,
        components=components,
        diagnostics=DOCUMENT_TEMPLATE_DIAGNOSTICS,
    )


async def send_whatsapp_qr_template(
    *,
    client: httpx.AsyncClient,
    settings: Settings,
    to_number: str,
    template_name: str,
    media_id: str,
    parameters: list[str],
) -> str:
    """Send the approved QR template with one passenger-specific image header."""

    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        raise WhatsAppCloudApiError(
            "WhatsApp Cloud API credentials are incomplete",
            code="WHATSAPP_PROVIDER_NOT_CONFIGURED",
        )
    try:
        validate_qr_template_parameters(parameters)
    except ValueError as exc:
        raise WhatsAppCloudApiError(
            f"Invalid WhatsApp QR template payload: {exc}",
            code="WHATSAPP_TEMPLATE_PAYLOAD_INVALID",
        ) from exc

    components: list[dict[str, Any]] = [
        {
            "type": "header",
            "parameters": [_image_parameter(media_id)],
        },
        {
            "type": "body",
            "parameters": [_text_parameter(parameter) for parameter in parameters],
        },
    ]
    return await _send_whatsapp_template_payload(
        client=client,
        settings=settings,
        to_number=to_number,
        template_name=template_name,
        language_code=settings.whatsapp_template_language,
        components=components,
        diagnostics=QR_TEMPLATE_DIAGNOSTICS,
    )


async def send_whatsapp_authentication_template(
    *,
    client: httpx.AsyncClient,
    settings: Settings,
    to_number: str,
    template_name: str,
    language_code: str,
    code: str,
) -> str:
    """Send an approved Meta authentication template with its OTP button value."""

    if not template_name.strip() or not language_code.strip():
        raise WhatsAppCloudApiError(
            "WhatsApp authentication template configuration is incomplete",
            code="WHATSAPP_PROVIDER_NOT_CONFIGURED",
        )
    if len(code) != 6 or not code.isascii() or not code.isdigit():
        raise WhatsAppCloudApiError(
            "Invalid WhatsApp authentication template payload",
            code="WHATSAPP_TEMPLATE_PAYLOAD_INVALID",
        )

    # Meta authentication templates bind the same code to BODY {{1}} and the
    # first OTP button. COPY_CODE, ONE_TAP, and ZERO_TAP templates use this
    # send-time URL-button representation; approval determines the fallback UI.
    components: list[dict[str, Any]] = [
        {
            "type": "body",
            "parameters": [_text_parameter(code)],
        },
        {
            "type": "button",
            "sub_type": "url",
            "index": "0",
            "parameters": [_text_parameter(code)],
        },
    ]
    return await _send_whatsapp_template_payload(
        client=client,
        settings=settings,
        to_number=to_number,
        template_name=template_name,
        language_code=language_code,
        components=components,
    )


async def send_whatsapp_template(
    *,
    client: httpx.AsyncClient,
    settings: Settings,
    to_number: str,
    template_name: str,
    message_type: WhatsAppMessageType,
    parameters: list[str],
    header_parameters: list[str] | None = None,
    language_code: str | None = None,
) -> str:
    if message_type == "reminder":
        # Also protects an explicitly retried historical snapshot. Never creates a retry.
        parameters = [normalize_template_text(value) for value in parameters]
    try:
        validate_template_parameters(
            message_type=message_type,
            header_parameters=header_parameters or [],
            body_parameters=parameters,
        )
    except ValueError as exc:
        raise WhatsAppCloudApiError(
            f"Invalid WhatsApp template payload: {exc}",
            code="WHATSAPP_TEMPLATE_PAYLOAD_INVALID",
        ) from exc

    components: list[dict[str, Any]] = []
    if header_parameters:
        components.append(
            {
                "type": "header",
                "parameters": [_image_parameter(header_parameters[0])],
            }
        )
    if parameters:
        components.append(
            {
                "type": "body",
                "parameters": [_text_parameter(parameter) for parameter in parameters],
            }
        )
    return await _send_whatsapp_template_payload(
        client=client,
        settings=settings,
        to_number=to_number,
        template_name=template_name,
        language_code=(
            language_code
            or (
                settings.whatsapp_group_invite_template_language
                if message_type == "group_invite"
                else settings.whatsapp_template_language
            )
        ),
        components=components,
    )


async def send_whatsapp_document_update_template(
    *,
    client: httpx.AsyncClient,
    settings: Settings,
    to_number: str,
    template_name: str,
    language_code: str,
    message_content: str,
) -> str:
    """The pending update template has one text variable and no document header."""
    message_content = normalize_template_text(message_content)
    if not template_name.strip() or not language_code.strip() or not message_content.strip():
        raise WhatsAppCloudApiError(
            "Document update template requires its frozen name, language and text",
            code="WHATSAPP_TEMPLATE_PAYLOAD_INVALID",
        )
    return await _send_whatsapp_template_payload(
        client=client,
        settings=settings,
        to_number=to_number,
        template_name=template_name,
        language_code=language_code,
        components=[{"type": "body", "parameters": [_text_parameter(message_content)]}],
    )
