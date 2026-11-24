"""Provider diagnostics never turn response text into staff-visible identifiers."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.infrastructure.whatsapp.cloud_api_provider import (
    WhatsAppCloudApiError,
    send_whatsapp_document_template,
    send_whatsapp_qr_template,
    send_whatsapp_template,
    upload_whatsapp_document,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["template", "document", "qr", "upload"])
@pytest.mark.parametrize("status", [400, 429, 500])
async def test_malformed_error_identifiers_do_not_echo_private_response_text(
    operation: str, status: int, caplog: pytest.LogCaptureFixture,
) -> None:
    private = "synthetic-passport-AB123456\nsynthetic-credential-should-not-be-logged"
    settings = SimpleNamespace(
        whatsapp_access_token="synthetic-provider-token",
        whatsapp_phone_number_id="123456789",
        whatsapp_api_version="v25.0",
        whatsapp_template_language="en_US",
    )
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, json={"error": {
            "code": private, "error_subcode": private,
            "message": private, "error_data": {"details": private},
        }})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        common = {"client": client, "settings": settings}
        with pytest.raises(WhatsAppCloudApiError) as failure:
            if operation == "upload":
                await upload_whatsapp_document(
                    **common, file_name="synthetic.pdf", file_content=b"%PDF-synthetic",
                    content_type="application/pdf",
                )
            elif operation == "template":
                await send_whatsapp_template(
                    **common, to_number="+919999999999", template_name="welcome",
                    message_type="welcome", parameters=["Reviewed trip statement"],
                    header_parameters=["synthetic-media"],
                )
            elif operation == "document":
                await send_whatsapp_document_template(
                    **common, to_number="+919999999999", template_name="documents_v1",
                    media_id="synthetic-media", filename="synthetic.pdf",
                    parameters=["Attached travel document", "Please check your details"],
                )
            else:
                await send_whatsapp_qr_template(
                    **common, to_number="+919999999999", template_name="qr_v1",
                    media_id="synthetic-media", parameters=["Save your trip QR"],
                )

    assert len(requests) == 1
    assert private not in failure.value.persistence_message
    assert "synthetic-passport" not in repr([record.__dict__ for record in caplog.records])
    assert failure.value.transient is (status == 429 or (operation == "upload" and status == 500))
    assert failure.value.delivery_unknown is (operation != "upload" and status == 500)
