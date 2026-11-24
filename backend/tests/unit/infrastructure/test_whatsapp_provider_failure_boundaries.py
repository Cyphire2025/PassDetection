"""No-network provider protocol failures retain safe retry and ambiguity rules."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.infrastructure.whatsapp.cloud_api_provider import (
    WhatsAppCloudApiError,
    send_whatsapp_authentication_template,
    send_whatsapp_document_template,
    send_whatsapp_document_update_template,
    send_whatsapp_qr_template,
    upload_whatsapp_document,
    upload_whatsapp_image,
)


def settings():
    return SimpleNamespace(
        whatsapp_access_token="synthetic-token",
        whatsapp_phone_number_id="123456789",
        whatsapp_api_version="v25.0",
        whatsapp_template_language="en_US",
    )


async def send_private(kind, client, configuration, parameters=None):
    common = dict(
        client=client,
        settings=configuration,
        to_number="+919999999999",
        template_name="reviewed-template",
        media_id="media-id",
        parameters=parameters
        if parameters is not None
        else (["Document", "Please review"] if kind == "document" else ["Your QR"]),
    )
    if kind == "document":
        return await send_whatsapp_document_template(**common, filename="synthetic.pdf")
    return await send_whatsapp_qr_template(**common)


@pytest.mark.parametrize("kind", ["document", "qr"])
@pytest.mark.parametrize("invalid", ["credentials", "parameters"])
async def test_invalid_private_template_never_dispatches_http(kind, invalid):
    client = SimpleNamespace(post=AsyncMock())
    configuration = settings()
    if invalid == "credentials":
        configuration.whatsapp_access_token = ""

    with pytest.raises(WhatsAppCloudApiError) as failure:
        await send_private(kind, client, configuration, [] if invalid == "parameters" else None)

    client.post.assert_not_awaited()
    assert failure.value.code == (
        "WHATSAPP_PROVIDER_NOT_CONFIGURED"
        if invalid == "credentials"
        else "WHATSAPP_TEMPLATE_PAYLOAD_INVALID"
    )


@pytest.mark.parametrize("kind", ["document", "image"])
@pytest.mark.parametrize("failure_kind", ["connect", "read", "invalid_json", "credentials"])
async def test_media_failure_can_retry_upload_without_claiming_message_acceptance(
    kind, failure_kind
):
    requests = []

    def respond(request):
        requests.append(request)
        if failure_kind == "connect":
            raise httpx.ConnectError("synthetic-private-connect-detail", request=request)
        if failure_kind == "read":
            raise httpx.ReadError("synthetic-private-read-detail", request=request)
        return httpx.Response(200, content=b"invalid-json")

    configuration = settings()
    if failure_kind == "credentials":
        configuration.whatsapp_access_token = ""
    upload = upload_whatsapp_document if kind == "document" else upload_whatsapp_image
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(WhatsAppCloudApiError) as failure:
            await upload(
                client=client,
                settings=configuration,
                file_name="synthetic.pdf",
                file_content=b"%PDF-synthetic",
                content_type="application/pdf",
            )

    assert len(requests) == (0 if failure_kind == "credentials" else 1)
    assert failure.value.transient is (failure_kind in {"connect", "read"})
    assert not failure.value.delivery_unknown
    assert "synthetic-private" not in failure.value.persistence_message


@pytest.mark.parametrize("kind", ["document", "qr"])
@pytest.mark.parametrize("reply", ["invalid_json", "missing_id", "auth_denied"])
async def test_template_response_cannot_make_ambiguous_acceptance_retryable(kind, reply):
    def respond(request):
        if reply == "auth_denied":
            return httpx.Response(401, json={"error": {"code": 190}})
        if reply == "invalid_json":
            return httpx.Response(200, content=b"invalid-json")
        return httpx.Response(200, json={"messages": [{}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(WhatsAppCloudApiError) as failure:
            await send_private(kind, client, settings())

    assert not failure.value.transient
    assert failure.value.delivery_unknown is (reply != "auth_denied")
    assert failure.value.code == (
        "WHATSAPP_PROVIDER_AUTH_FAILED"
        if reply == "auth_denied"
        else "WHATSAPP_PROVIDER_RESPONSE_INVALID"
    )


async def test_document_update_uses_frozen_name_language_and_normalized_text():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.update"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await send_whatsapp_document_update_template(
            client=client,
            settings=settings(),
            to_number="+919999999999",
            template_name="frozen-template",
            language_code="en",
            message_content="  Your\n updated  document ",
        )

    assert result == "wamid.update"
    template = json.loads(requests[0].content)["template"]
    assert template == {
        "name": "frozen-template",
        "language": {"code": "en"},
        "components": [
            {"type": "body", "parameters": [{"type": "text", "text": "Your updated document"}]}
        ],
    }


@pytest.mark.parametrize("operation", ["authentication", "document_update"])
async def test_empty_approved_template_configuration_never_contacts_provider(operation):
    client = SimpleNamespace(post=AsyncMock())
    with pytest.raises(WhatsAppCloudApiError):
        if operation == "authentication":
            await send_whatsapp_authentication_template(
                client=client,
                settings=settings(),
                to_number="+919999999999",
                template_name="",
                language_code="en",
                code="123456",
            )
        else:
            await send_whatsapp_document_update_template(
                client=client,
                settings=settings(),
                to_number="+919999999999",
                template_name="",
                language_code="en",
                message_content="Update",
            )
    client.post.assert_not_awaited()
