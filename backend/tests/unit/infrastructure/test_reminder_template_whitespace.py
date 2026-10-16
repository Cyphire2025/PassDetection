"""Regression for real Meta 132018 failures on pasted reminder paragraphs."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.application.use_cases.whatsapp.message_templates import render_message, template_parameters
from app.application.use_cases.whatsapp.template_text import normalize_template_text
from app.infrastructure.whatsapp.cloud_api_provider import (
    send_whatsapp_document_update_template,
    send_whatsapp_template,
)
from app.presentation.api.v1.routes.whatsapp_composer_support import _resolve_send_message_content


@pytest.mark.parametrize("content", ["Please\n\nupload\tyour documents.", " Please\r\nupload     your documents. ", "Please\u00a0upload\u2028your documents."])
async def test_preview_queue_and_provider_agree_on_single_line_variable(content):
    expected = "Please upload your documents."
    assert normalize_template_text(content) == expected
    assert _resolve_send_message_content("reminder", content, group_name="Trip") == expected
    values = dict(message_type="reminder", group_name="Trip", support_contacts="", message_content=content)
    assert template_parameters(**values) == [expected]
    assert f"\n\n{expected}\n\n" in render_message(**values)
    client = SimpleNamespace(post=AsyncMock(return_value=SimpleNamespace(status_code=200, json=lambda: {"messages": [{"id": "wamid.test"}]})))
    settings = SimpleNamespace(whatsapp_access_token="test", whatsapp_phone_number_id="test", whatsapp_api_version="v25.0", whatsapp_template_language="en")
    # The transport also guards explicitly retried legacy snapshots.
    await send_whatsapp_template(client=client, settings=settings, to_number="+919876543210", template_name="reminder_v1", message_type="reminder", parameters=[content])
    assert client.post.call_args.kwargs["json"]["template"]["components"] == [{"type": "body", "parameters": [{"type": "text", "text": expected}]}]
    await send_whatsapp_document_update_template(client=client, settings=settings, to_number="+919876543210", template_name="pending_v1", language_code="en", message_content=content)
    assert client.post.call_args.kwargs["json"]["template"]["components"] == [{"type": "body", "parameters": [{"type": "text", "text": expected}]}]


def test_normalization_preserves_unicode_emphasis_and_links():
    assert normalize_template_text("*कल*\nhttps://example.test/a?b=1&c=2 🎫") == "*कल* https://example.test/a?b=1&c=2 🎫"
