"""One template-message HTTP and outcome boundary for every header type."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config.settings import Settings
from app.infrastructure.whatsapp.provider_errors import (
    STANDARD_TEMPLATE_DIAGNOSTICS,
    TemplateDeliveryDiagnostics,
    WhatsAppCloudApiError,
    _meta_error_reference,
)

logger = logging.getLogger("app.infrastructure.whatsapp.cloud_api_provider")


async def _send_whatsapp_template_payload(
    *,
    client: httpx.AsyncClient,
    settings: Settings,
    to_number: str,
    template_name: str,
    language_code: str,
    components: list[dict[str, Any]],
    diagnostics: TemplateDeliveryDiagnostics = STANDARD_TEMPLATE_DIAGNOSTICS,
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
            diagnostics.interrupted_message,
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
            message = f"{diagnostics.rate_limited_message}{meta_reference}"
        elif response.status_code in {401, 403}:
            code = "WHATSAPP_PROVIDER_AUTH_FAILED"
            message = f"Meta rejected the configured WhatsApp credentials{meta_reference}"
        elif response.status_code >= 500:
            code = "WHATSAPP_DELIVERY_UNKNOWN"
            message = f"Meta returned a server error and delivery status is unknown{meta_reference}"
        else:
            code = "WHATSAPP_PROVIDER_REJECTED"
            message = f"{diagnostics.rejected_message}{meta_reference}"
        logger.warning(
            diagnostics.log_event,
            extra={
                "status_code": response.status_code,
                diagnostics.code_log_key: provider_code,
                diagnostics.subcode_log_key: provider_subcode,
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
            diagnostics.accepted_without_id,
            code="WHATSAPP_PROVIDER_RESPONSE_INVALID",
            delivery_unknown=True,
        )
    provider_id = messages[0].get("id") if isinstance(messages[0], dict) else None
    if not provider_id:
        raise WhatsAppCloudApiError(
            diagnostics.accepted_without_id,
            code="WHATSAPP_PROVIDER_RESPONSE_INVALID",
            delivery_unknown=True,
        )
    return str(provider_id)
