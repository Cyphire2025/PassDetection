"""Meta WhatsApp Cloud API template-message transport."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.application.use_cases.whatsapp.document_templates import (
    validate_document_template_parameters,
)
from app.application.use_cases.whatsapp.message_templates import (
    WhatsAppMessageType,
    validate_template_parameters,
)
from app.application.use_cases.whatsapp.qr_templates import (
    validate_qr_template_parameters,
)
from app.core.config.settings import Settings

logger = logging.getLogger(__name__)

WHATSAPP_PDF_CONTENT_TYPE = "application/pdf"
WHATSAPP_MAX_DOCUMENT_BYTES = 100 * 1024 * 1024


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


def _document_parameter(media_id: str, filename: str) -> dict[str, Any]:
    return {
        "type": "document",
        "document": {"id": media_id, "filename": filename},
    }


def _meta_error_reference(data: Any) -> tuple[str | None, str | None, str]:
    """Return non-sensitive Meta error identifiers for staff diagnostics."""

    error = data.get("error") if isinstance(data, dict) else None
    if not isinstance(error, dict):
        return None, None, ""
    raw_code = error.get("code")
    raw_subcode = error.get("error_subcode")
    meta_code = str(raw_code).strip() if isinstance(raw_code, (int, str)) else None
    meta_subcode = str(raw_subcode).strip() if isinstance(raw_subcode, (int, str)) else None
    parts = []
    if meta_code:
        parts.append(f"Meta code {meta_code}")
    if meta_subcode:
        parts.append(f"subcode {meta_subcode}")
    return meta_code, meta_subcode, f" ({', '.join(parts)})" if parts else ""


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
            "The image could not be uploaded to WhatsApp",
            code="WHATSAPP_MEDIA_UPLOAD_UNREACHABLE",
            transient=True,
        ) from exc
    except httpx.HTTPError as exc:
        raise WhatsAppCloudApiError(
            "The image upload was interrupted",
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
            "Meta rejected the image; use a clear JPEG or PNG and try again",
            code="WHATSAPP_MEDIA_UPLOAD_REJECTED",
            transient=response.status_code == 429 or response.status_code >= 500,
        )
    return media_id.strip()


async def upload_whatsapp_document(
    *,
    client: httpx.AsyncClient,
    settings: Settings,
    file_name: str,
    file_content: bytes,
    content_type: str,
) -> str:
    """Upload one private travel document to Meta for a template header."""

    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        raise WhatsAppCloudApiError(
            "WhatsApp Cloud API credentials are incomplete",
            code="WHATSAPP_PROVIDER_NOT_CONFIGURED",
        )
    if not file_content.startswith(b"%PDF-") or len(file_content) > WHATSAPP_MAX_DOCUMENT_BYTES:
        raise WhatsAppCloudApiError(
            "The saved travel document is not a valid supported PDF",
            code="WHATSAPP_DOCUMENT_INVALID",
        )
    normalized_filename = file_name.strip() or "travel-document.pdf"
    if not normalized_filename.lower().endswith(".pdf"):
        normalized_filename = f"{normalized_filename}.pdf"
    try:
        response = await client.post(
            (
                f"https://graph.facebook.com/{settings.whatsapp_api_version}/"
                f"{settings.whatsapp_phone_number_id}/media"
            ),
            data={"messaging_product": "whatsapp"},
            files={
                "file": (
                    normalized_filename,
                    file_content,
                    WHATSAPP_PDF_CONTENT_TYPE,
                )
            },
            headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
        )
    except (httpx.ConnectTimeout, httpx.ConnectError, httpx.PoolTimeout) as exc:
        raise WhatsAppCloudApiError(
            "The travel document could not be uploaded to WhatsApp",
            code="WHATSAPP_DOCUMENT_UPLOAD_UNREACHABLE",
            transient=True,
        ) from exc
    except httpx.HTTPError as exc:
        raise WhatsAppCloudApiError(
            "The travel document upload was interrupted",
            code="WHATSAPP_DOCUMENT_UPLOAD_INTERRUPTED",
            transient=True,
        ) from exc

    try:
        data = response.json()
    except ValueError:
        data = {}
    media_id = data.get("id") if isinstance(data, dict) else None
    if response.status_code >= 400 or not isinstance(media_id, str) or not media_id.strip():
        meta_code, meta_subcode, meta_reference = _meta_error_reference(data)
        logger.warning(
            "whatsapp_document_upload_rejected",
            extra={
                "status_code": response.status_code,
                "meta_code": meta_code,
                "meta_subcode": meta_subcode,
            },
        )
        raise WhatsAppCloudApiError(
            "Meta rejected the travel document upload"
            f"{meta_reference}; verify the PDF and try again",
            code="WHATSAPP_DOCUMENT_UPLOAD_REJECTED",
            transient=response.status_code == 429 or response.status_code >= 500,
        )
    return media_id.strip()


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

    template = {
        "name": template_name,
        "language": {"code": settings.whatsapp_template_language},
        "components": [
            {
                "type": "header",
                "parameters": [_document_parameter(media_id, filename)],
            },
            {
                "type": "body",
                "parameters": [_text_parameter(parameter) for parameter in parameters],
            },
        ],
    }
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
        raise WhatsAppCloudApiError(
            "WhatsApp document delivery outcome is unknown after a provider interruption",
            code="WHATSAPP_DELIVERY_UNKNOWN",
            delivery_unknown=True,
        ) from exc

    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code >= 400:
        meta_code, meta_subcode, meta_reference = _meta_error_reference(data)
        logger.warning(
            "whatsapp_document_template_rejected",
            extra={
                "status_code": response.status_code,
                "meta_error_code": meta_code,
                "meta_error_subcode": meta_subcode,
            },
        )
        if response.status_code == 429:
            code = "WHATSAPP_PROVIDER_RATE_LIMITED"
            message = f"Meta temporarily rate-limited this document message{meta_reference}"
        elif response.status_code in {401, 403}:
            code = "WHATSAPP_PROVIDER_AUTH_FAILED"
            message = f"Meta rejected the configured WhatsApp credentials{meta_reference}"
        elif response.status_code >= 500:
            code = "WHATSAPP_DELIVERY_UNKNOWN"
            message = f"Meta returned a server error and delivery status is unknown{meta_reference}"
        else:
            code = "WHATSAPP_PROVIDER_REJECTED"
            message = (
                "Meta rejected this document template; verify the approved template "
                f"and recipient details{meta_reference}"
            )
        raise WhatsAppCloudApiError(
            message,
            code=code,
            transient=response.status_code == 429,
            delivery_unknown=response.status_code >= 500,
        )
    messages = data.get("messages") if isinstance(data, dict) else None
    provider_id = (
        messages[0].get("id")
        if isinstance(messages, list) and messages and isinstance(messages[0], dict)
        else None
    )
    if not provider_id:
        raise WhatsAppCloudApiError(
            "WhatsApp API accepted the document without returning a message ID",
            code="WHATSAPP_PROVIDER_RESPONSE_INVALID",
            delivery_unknown=True,
        )
    return str(provider_id)


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

    template = {
        "name": template_name,
        "language": {"code": settings.whatsapp_template_language},
        "components": [
            {
                "type": "header",
                "parameters": [_image_parameter(media_id)],
            },
            {
                "type": "body",
                "parameters": [_text_parameter(parameter) for parameter in parameters],
            },
        ],
    }
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
        raise WhatsAppCloudApiError(
            "WhatsApp QR delivery outcome is unknown after a provider interruption",
            code="WHATSAPP_DELIVERY_UNKNOWN",
            delivery_unknown=True,
        ) from exc

    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code >= 400:
        meta_code, meta_subcode, meta_reference = _meta_error_reference(data)
        logger.warning(
            "whatsapp_qr_template_rejected",
            extra={
                "status_code": response.status_code,
                "meta_error_code": meta_code,
                "meta_error_subcode": meta_subcode,
            },
        )
        if response.status_code == 429:
            code = "WHATSAPP_PROVIDER_RATE_LIMITED"
            message = f"Meta temporarily rate-limited this QR message{meta_reference}"
        elif response.status_code in {401, 403}:
            code = "WHATSAPP_PROVIDER_AUTH_FAILED"
            message = f"Meta rejected the configured WhatsApp credentials{meta_reference}"
        elif response.status_code >= 500:
            code = "WHATSAPP_DELIVERY_UNKNOWN"
            message = f"Meta returned a server error and delivery status is unknown{meta_reference}"
        else:
            code = "WHATSAPP_PROVIDER_REJECTED"
            message = (
                "Meta rejected this QR template; verify the approved template "
                f"and recipient details{meta_reference}"
            )
        raise WhatsAppCloudApiError(
            message,
            code=code,
            transient=response.status_code == 429,
            delivery_unknown=response.status_code >= 500,
        )
    messages = data.get("messages") if isinstance(data, dict) else None
    provider_id = (
        messages[0].get("id")
        if isinstance(messages, list) and messages and isinstance(messages[0], dict)
        else None
    )
    if not provider_id:
        raise WhatsAppCloudApiError(
            "WhatsApp API accepted the QR message without returning a message ID",
            code="WHATSAPP_PROVIDER_RESPONSE_INVALID",
            delivery_unknown=True,
        )
    return str(provider_id)


async def _send_whatsapp_template_payload(
    *,
    client: httpx.AsyncClient,
    settings: Settings,
    to_number: str,
    template_name: str,
    language_code: str,
    components: list[dict[str, Any]],
) -> str:
    """Send one prevalidated template payload through the shared Meta transport."""

    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        raise WhatsAppCloudApiError(
            "WhatsApp Cloud API credentials are incomplete",
            code="WHATSAPP_PROVIDER_NOT_CONFIGURED",
        )
    template: dict[str, Any] = {
        "name": template_name,
        "language": {"code": language_code},
    }
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
        provider_code, provider_subcode, meta_reference = _meta_error_reference(data)
        if response.status_code == 429:
            code = "WHATSAPP_PROVIDER_RATE_LIMITED"
            message = f"Meta temporarily rate-limited this template message{meta_reference}"
        elif response.status_code in {401, 403}:
            code = "WHATSAPP_PROVIDER_AUTH_FAILED"
            message = f"Meta rejected the configured WhatsApp credentials{meta_reference}"
        elif response.status_code >= 500:
            code = "WHATSAPP_DELIVERY_UNKNOWN"
            message = f"Meta returned a server error and delivery status is unknown{meta_reference}"
        else:
            code = "WHATSAPP_PROVIDER_REJECTED"
            message = (
                "Meta rejected this template message; verify the approved template "
                f"configuration and recipient details{meta_reference}"
            )
        logger.warning(
            "whatsapp_cloud_api_request_rejected",
            extra={
                "status_code": response.status_code,
                "provider_code": provider_code,
                "provider_subcode": provider_subcode,
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
) -> str:
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
        language_code=settings.whatsapp_template_language,
        components=components,
    )
