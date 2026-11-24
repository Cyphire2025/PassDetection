"""Keep current and rolling-release template payloads exact at the HTTP seam."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app.infrastructure.whatsapp.cloud_api_provider import (
    send_whatsapp_document_template,
    send_whatsapp_qr_template,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,count", [("document", 2), ("document", 3), ("qr", 1)])
async def test_private_template_payload_keeps_media_and_parameter_order(kind: str, count: int) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.synthetic-contract"}]})

    settings = SimpleNamespace(
        whatsapp_access_token="synthetic-token", whatsapp_phone_number_id="123456789",
        whatsapp_api_version="v25.0", whatsapp_template_language="en_US",
    )
    parameters = [f"parameter-{index}" for index in range(count)]
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        common = dict(client=client, settings=settings, to_number="+919999999999",
                      template_name="reviewed_template", media_id="synthetic-media", parameters=parameters)
        if kind == "document":
            provider_id = await send_whatsapp_document_template(**common, filename="traveller.pdf")
        else:
            provider_id = await send_whatsapp_qr_template(**common)

    assert provider_id == "wamid.synthetic-contract"
    assert len(requests) == 1
    assert str(requests[0].url) == "https://graph.facebook.com/v25.0/123456789/messages"
    assert requests[0].headers["Authorization"] == "Bearer synthetic-token"
    media = ({"type": "document", "document": {"id": "synthetic-media", "filename": "traveller.pdf"}}
             if kind == "document" else {"type": "image", "image": {"id": "synthetic-media"}})
    assert json.loads(requests[0].content) == {
        "messaging_product": "whatsapp", "recipient_type": "individual", "to": "919999999999",
        "type": "template", "template": {
            "name": "reviewed_template", "language": {"code": "en_US"},
            "components": [
                {"type": "header", "parameters": [media]},
                {"type": "body", "parameters": [{"type": "text", "text": value} for value in parameters]},
            ],
        },
    }
