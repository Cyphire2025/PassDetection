"""Meta WhatsApp Cloud API template-message transport."""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config.settings import Settings


class WhatsAppCloudApiError(RuntimeError):
    """A safe provider error suitable for per-recipient message logs."""

    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


def _text_parameter(value: str) -> dict[str, str]:
    return {"type": "text", "text": value}


async def send_whatsapp_template(
    *,
    client: httpx.AsyncClient,
    settings: Settings,
    to_number: str,
    template_name: str,
    parameters: list[str],
    header_parameters: list[str] | None = None,
) -> str:
    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        raise WhatsAppCloudApiError("WhatsApp Cloud API credentials are incomplete")

    template: dict[str, Any] = {
        "name": template_name,
        "language": {"code": settings.whatsapp_template_language},
    }
    components: list[dict[str, Any]] = []
    if header_parameters:
        components.append(
            {
                "type": "header",
                "parameters": [_text_parameter(parameter) for parameter in header_parameters],
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
    except httpx.HTTPError as exc:
        raise WhatsAppCloudApiError(
            "WhatsApp Cloud API could not be reached",
            transient=True,
        ) from exc
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code >= 400:
        error = data.get("error", {}) if isinstance(data, dict) else {}
        details = error.get("error_data", {}).get("details") if isinstance(error, dict) else None
        message = details or (error.get("message") if isinstance(error, dict) else None)
        raise WhatsAppCloudApiError(
            str(message or f"WhatsApp API returned {response.status_code}")[:2000],
            transient=response.status_code == 429 or response.status_code >= 500,
        )
    messages = data.get("messages") if isinstance(data, dict) else None
    if not isinstance(messages, list) or not messages:
        raise WhatsAppCloudApiError(
            "WhatsApp API accepted the request without returning a message ID",
            transient=True,
        )
    provider_id = messages[0].get("id") if isinstance(messages[0], dict) else None
    if not provider_id:
        raise WhatsAppCloudApiError(
            "WhatsApp API accepted the request without returning a message ID",
            transient=True,
        )
    return str(provider_id)
