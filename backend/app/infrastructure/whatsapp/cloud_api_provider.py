"""Meta WhatsApp Cloud API template-message transport."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.application.use_cases.whatsapp.message_templates import (
    WhatsAppMessageType,
    validate_template_parameters,
)
from app.core.config.settings import Settings

logger = logging.getLogger(__name__)


class WhatsAppCloudApiError(RuntimeError):
    """A safe provider error suitable for per-recipient message logs."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "WHATSAPP_PROVIDER_ERROR",
        transient: bool = False,
        delivery_unknown: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.transient = transient
        self.delivery_unknown = delivery_unknown

    @property
    def persistence_message(self) -> str:
        """Return a bounded diagnostic that is safe to expose to staff clients."""

        return f"{self.code}: {self}"


def _text_parameter(value: str) -> dict[str, str]:
    return {"type": "text", "text": value}


def _image_parameter(media_id: str) -> dict[str, Any]:
    return {"type": "image", "image": {"id": media_id}}


async def upload_whatsapp_image(
    *,
    client: httpx.AsyncClient,
    settings: Settings,
    file_name: str,
    file_content: bytes,
    content_type: str,
) -> str:
    """Upload a validated image to Meta and return its reusable media ID."""

    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        raise WhatsAppCloudApiError(
            "WhatsApp Cloud API credentials are incomplete",
            code="WHATSAPP_PROVIDER_NOT_CONFIGURED",
        )

    try:
        response = await client.post(
            (
                f"https://graph.facebook.com/{settings.whatsapp_api_version}/"
                f"{settings.whatsapp_phone_number_id}/media"
            ),
            data={
                "messaging_product": "whatsapp",
                "type": content_type,
            },
            files={
                "file": (
                    file_name,
                    file_content,
                    content_type,
                ),
            },
            headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
        )
    except (httpx.ConnectTimeout, httpx.ConnectError, httpx.PoolTimeout) as exc:
        raise WhatsAppCloudApiError(
            "The Welcome image could not be uploaded to WhatsApp",
            code="WHATSAPP_MEDIA_UPLOAD_UNREACHABLE",
            transient=True,
        ) from exc
    except httpx.HTTPError as exc:
        raise WhatsAppCloudApiError(
            "The Welcome image upload was interrupted",
            code="WHATSAPP_MEDIA_UPLOAD_INTERRUPTED",
            transient=True,
        ) from exc

    try:
        data = response.json()
    except ValueError:
        data = {}
    media_id = data.get("id") if isinstance(data, dict) else None
    if response.status_code >= 400 or not isinstance(media_id, str) or not media_id.strip():
        logger.warning(
            "whatsapp_media_upload_rejected",
            extra={"status_code": response.status_code},
        )
        raise WhatsAppCloudApiError(
            "Meta rejected the Welcome image; use a clear JPEG or PNG and try again",
            code="WHATSAPP_MEDIA_UPLOAD_REJECTED",
            transient=response.status_code == 429 or response.status_code >= 500,
        )
    return media_id.strip()


async def send_whatsapp_template(
    *,
    client: httpx.AsyncClient,
    settings: Settings,
    to_number: str,
    template_name: str,
    message_type: WhatsAppMessageType,
    parameters: list[str],
    header_parameters: list[str] | None = None,
) -> str:
    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        raise WhatsAppCloudApiError(
            "WhatsApp Cloud API credentials are incomplete",
            code="WHATSAPP_PROVIDER_NOT_CONFIGURED",
        )
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

    template: dict[str, Any] = {
        "name": template_name,
        "language": {"code": settings.whatsapp_template_language},
    }
    components: list[dict[str, Any]] = []
    if header_parameters:
        components.append(
            {
                "type": "header",
                "parameters": (
                    [_image_parameter(header_parameters[0])]
                    if message_type == "welcome"
                    else [_text_parameter(parameter) for parameter in header_parameters]
                ),
            }
        )
    if parameters:
        components.append(
            {
                "type": "body",
                "parameters": [_text_parameter(parameter) for parameter in parameters],
            }
        )
    if components:
        template["components"] = components

    try:
        response = await client.post(
            (
                f"https://graph.facebook.com/{settings.whatsapp_api_version}/"
                f"{settings.whatsapp_phone_number_id}/messages"
            ),
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to_number.lstrip("+"),
                "type": "template",
                "template": template,
            },
            headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
        )
    except (httpx.ConnectTimeout, httpx.ConnectError, httpx.PoolTimeout) as exc:
        raise WhatsAppCloudApiError(
            "WhatsApp Cloud API could not be reached",
            code="WHATSAPP_PROVIDER_UNREACHABLE",
            transient=True,
        ) from exc
    except httpx.HTTPError as exc:
        # Once request bytes may have left this process, retrying without a
        # provider idempotency key can duplicate a message. Preserve an
        # uncertain/suppressed outcome for manual reconciliation.
        raise WhatsAppCloudApiError(
            "WhatsApp delivery outcome is unknown after a provider connection interruption",
            code="WHATSAPP_DELIVERY_UNKNOWN",
            delivery_unknown=True,
        ) from exc
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code >= 400:
        error = data.get("error", {}) if isinstance(data, dict) else {}
        provider_code = error.get("code") if isinstance(error, dict) else None
        provider_subcode = error.get("error_subcode") if isinstance(error, dict) else None
        if response.status_code == 429:
            code = "WHATSAPP_PROVIDER_RATE_LIMITED"
            message = "Meta temporarily rate-limited this template message"
        elif response.status_code in {401, 403}:
            code = "WHATSAPP_PROVIDER_AUTH_FAILED"
            message = "Meta rejected the configured WhatsApp credentials"
        elif response.status_code >= 500:
            code = "WHATSAPP_DELIVERY_UNKNOWN"
            message = "Meta returned a server error and delivery status is unknown"
        else:
            code = "WHATSAPP_PROVIDER_REJECTED"
            message = (
                "Meta rejected this template message; verify the approved template "
                "configuration and recipient details"
            )
        logger.warning(
            "whatsapp_cloud_api_request_rejected",
            extra={
                "status_code": response.status_code,
                "provider_code": (
                    provider_code
                    if isinstance(provider_code, (str, int))
                    else None
                ),
                "provider_subcode": (
                    provider_subcode
                    if isinstance(provider_subcode, (str, int))
                    else None
                ),
            },
        )
        raise WhatsAppCloudApiError(
            message,
            code=code,
            transient=response.status_code == 429,
            delivery_unknown=response.status_code >= 500,
        )
    messages = data.get("messages") if isinstance(data, dict) else None
    if not isinstance(messages, list) or not messages:
        raise WhatsAppCloudApiError(
            "WhatsApp API accepted the request without returning a message ID",
            code="WHATSAPP_PROVIDER_RESPONSE_INVALID",
            delivery_unknown=True,
        )
    provider_id = messages[0].get("id") if isinstance(messages[0], dict) else None
    if not provider_id:
        raise WhatsAppCloudApiError(
            "WhatsApp API accepted the request without returning a message ID",
            code="WHATSAPP_PROVIDER_RESPONSE_INVALID",
            delivery_unknown=True,
        )
    return str(provider_id)
