"""Tests for Meta Cloud API template payload construction."""

from __future__ import annotations

import types
import unittest
from unittest.mock import AsyncMock

from app.infrastructure.whatsapp.cloud_api_provider import (
    WhatsAppCloudApiError,
    send_whatsapp_template,
)


class WhatsAppCloudApiProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_one_individual_template_with_ordered_parameters(self) -> None:
        response = types.SimpleNamespace(
            status_code=200,
            json=lambda: {"messages": [{"id": "wamid.test-123"}]},
        )
        client = types.SimpleNamespace(post=AsyncMock(return_value=response))
        settings = types.SimpleNamespace(
            whatsapp_access_token="test-token",
            whatsapp_phone_number_id="123456789",
            whatsapp_api_version="v25.0",
            whatsapp_template_language="en_US",
        )

        provider_id = await send_whatsapp_template(
            client=client,
            settings=settings,
            to_number="+919876543210",
            template_name="global_connect_welcome_v1",
            header_parameters=["Aarav"],
            parameters=[
                "Vietnam 2026",
                "Bluechip",
                "All further trip details will be shared here.",
                "- Santosh: 9873536643",
            ],
        )

        self.assertEqual(provider_id, "wamid.test-123")
        _, kwargs = client.post.call_args
        self.assertEqual(kwargs["json"]["recipient_type"], "individual")
        self.assertEqual(kwargs["json"]["to"], "919876543210")
        self.assertEqual(kwargs["json"]["type"], "template")
        self.assertEqual(
            kwargs["json"]["template"]["components"][0]["parameters"],
            [{"type": "text", "text": "Aarav"}],
        )
        self.assertEqual(
            kwargs["json"]["template"]["components"][1]["parameters"],
            [
                {"type": "text", "text": "Vietnam 2026"},
                {"type": "text", "text": "Bluechip"},
                {"type": "text", "text": "All further trip details will be shared here."},
                {"type": "text", "text": "- Santosh: 9873536643"},
            ],
        )

    async def test_exposes_safe_provider_error_details(self) -> None:
        response = types.SimpleNamespace(
            status_code=400,
            json=lambda: {
                "error": {
                    "message": "Invalid parameter",
                    "error_data": {"details": "Template is not approved"},
                }
            },
        )
        client = types.SimpleNamespace(post=AsyncMock(return_value=response))
        settings = types.SimpleNamespace(
            whatsapp_access_token="test-token",
            whatsapp_phone_number_id="123456789",
            whatsapp_api_version="v25.0",
            whatsapp_template_language="en_US",
        )

        with self.assertRaisesRegex(WhatsAppCloudApiError, "Template is not approved"):
            await send_whatsapp_template(
                client=client,
                settings=settings,
                to_number="+919876543210",
                template_name="global_connect_welcome_v1",
                parameters=["Aarav"],
            )


if __name__ == "__main__":
    unittest.main()
