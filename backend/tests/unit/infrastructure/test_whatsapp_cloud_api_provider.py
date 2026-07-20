"""Tests for Meta Cloud API template payload construction."""

from __future__ import annotations

import types
import unittest
from unittest.mock import AsyncMock

import httpx

from app.infrastructure.whatsapp.cloud_api_provider import (
    WhatsAppCloudApiError,
    send_whatsapp_template,
    upload_whatsapp_image,
)


class WhatsAppCloudApiProviderTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _settings() -> types.SimpleNamespace:
        return types.SimpleNamespace(
            whatsapp_access_token="test-token",
            whatsapp_phone_number_id="123456789",
            whatsapp_api_version="v25.0",
            whatsapp_template_language="en_US",
        )

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
            template_name="approved_welcome_template",
            message_type="welcome",
            parameters=[
                'This message is regarding your upcoming trip to "Vietnam 2026".',
            ],
            header_parameters=["media-123"],
        )

        self.assertEqual(provider_id, "wamid.test-123")
        args, kwargs = client.post.call_args
        self.assertEqual(
            args[0],
            "https://graph.facebook.com/v25.0/123456789/messages",
        )
        self.assertEqual(kwargs["json"]["recipient_type"], "individual")
        self.assertEqual(kwargs["json"]["to"], "919876543210")
        self.assertEqual(kwargs["json"]["type"], "template")
        self.assertEqual(
            kwargs["json"]["template"]["name"],
            "approved_welcome_template",
        )
        self.assertEqual(
            kwargs["json"]["template"]["language"],
            {"code": "en_US"},
        )
        self.assertEqual(
            [component["type"] for component in kwargs["json"]["template"]["components"]],
            ["header", "body"],
        )
        self.assertEqual(
            kwargs["json"]["template"]["components"][0]["parameters"],
            [{"type": "image", "image": {"id": "media-123"}}],
        )
        self.assertEqual(
            kwargs["json"]["template"]["components"][1]["parameters"],
            [
                {
                    "type": "text",
                    "text": 'This message is regarding your upcoming trip to "Vietnam 2026".',
                },
            ],
        )

    async def test_uploads_welcome_image_and_returns_meta_media_id(self) -> None:
        response = types.SimpleNamespace(
            status_code=200,
            json=lambda: {"id": "media-456"},
        )
        client = types.SimpleNamespace(post=AsyncMock(return_value=response))

        media_id = await upload_whatsapp_image(
            client=client,
            settings=self._settings(),
            file_name="welcome.jpg",
            file_content=b"jpeg-bytes",
            content_type="image/jpeg",
        )

        self.assertEqual(media_id, "media-456")
        args, kwargs = client.post.await_args
        self.assertEqual(
            args[0],
            "https://graph.facebook.com/v25.0/123456789/media",
        )
        self.assertEqual(kwargs["data"]["messaging_product"], "whatsapp")
        self.assertEqual(kwargs["data"]["type"], "image/jpeg")
        self.assertEqual(kwargs["files"]["file"][1], b"jpeg-bytes")

    async def test_redacts_raw_provider_error_details(self) -> None:
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

        with self.assertRaises(WhatsAppCloudApiError) as raised:
            await send_whatsapp_template(
                client=client,
                settings=settings,
                to_number="+919876543210",
                template_name="approved_welcome_template",
                message_type="welcome",
                parameters=["Trip statement"],
                header_parameters=["media-123"],
            )
        self.assertEqual(
            raised.exception.code,
            "WHATSAPP_PROVIDER_REJECTED",
        )
        self.assertNotIn("Template is not approved", str(raised.exception))
        self.assertNotIn("Invalid parameter", str(raised.exception))
        self.assertIn("Meta rejected this template message", str(raised.exception))

    async def test_passport_payload_has_one_body_component_with_four_parameters(self) -> None:
        response = types.SimpleNamespace(
            status_code=200,
            json=lambda: {"messages": [{"id": "wamid.passport-123"}]},
        )
        client = types.SimpleNamespace(post=AsyncMock(return_value=response))
        parameters = [
            "Please use the secure link below for your trip to Thailand.",
            "https://travel.example/upload/abc",
            "Please fill in all required details and review everything carefully.",
            "Support Desk: 9876543210",
        ]

        await send_whatsapp_template(
            client=client,
            settings=self._settings(),
            to_number="+919876543210",
            template_name="approved_passport_template",
            message_type="passport_link",
            parameters=parameters,
            header_parameters=[],
        )

        template = client.post.await_args.kwargs["json"]["template"]
        self.assertEqual(
            [component["type"] for component in template["components"]],
            ["body"],
        )
        self.assertEqual(
            template["components"][0]["parameters"],
            [{"type": "text", "text": value} for value in parameters],
        )

    async def test_connect_failure_is_safe_to_retry(self) -> None:
        request = httpx.Request("POST", "https://graph.facebook.com")
        client = types.SimpleNamespace(
            post=AsyncMock(side_effect=httpx.ConnectTimeout("connect", request=request))
        )

        with self.assertRaises(WhatsAppCloudApiError) as raised:
            await send_whatsapp_template(
                client=client,
                settings=self._settings(),
                to_number="+919876543210",
                template_name="welcome",
                message_type="welcome",
                parameters=["Trip statement"],
                header_parameters=["media-123"],
            )

        self.assertTrue(raised.exception.transient)
        self.assertFalse(raised.exception.delivery_unknown)

    async def test_read_timeout_is_suppressed_instead_of_retried(self) -> None:
        request = httpx.Request("POST", "https://graph.facebook.com")
        client = types.SimpleNamespace(
            post=AsyncMock(side_effect=httpx.ReadTimeout("read", request=request))
        )

        with self.assertRaises(WhatsAppCloudApiError) as raised:
            await send_whatsapp_template(
                client=client,
                settings=self._settings(),
                to_number="+919876543210",
                template_name="welcome",
                message_type="welcome",
                parameters=["Trip statement"],
                header_parameters=["media-123"],
            )

        self.assertFalse(raised.exception.transient)
        self.assertTrue(raised.exception.delivery_unknown)

    async def test_server_error_is_suppressed_instead_of_retried(self) -> None:
        response = types.SimpleNamespace(
            status_code=500,
            json=lambda: {"error": {"message": "Temporary provider failure"}},
        )
        client = types.SimpleNamespace(post=AsyncMock(return_value=response))

        with self.assertRaises(WhatsAppCloudApiError) as raised:
            await send_whatsapp_template(
                client=client,
                settings=self._settings(),
                to_number="+919876543210",
                template_name="welcome",
                message_type="welcome",
                parameters=["Trip statement"],
                header_parameters=["media-123"],
            )

        self.assertFalse(raised.exception.transient)
        self.assertTrue(raised.exception.delivery_unknown)

    async def test_success_without_message_id_is_suppressed(self) -> None:
        response = types.SimpleNamespace(
            status_code=200,
            json=lambda: {"messages": [{}]},
        )
        client = types.SimpleNamespace(post=AsyncMock(return_value=response))

        with self.assertRaises(WhatsAppCloudApiError) as raised:
            await send_whatsapp_template(
                client=client,
                settings=self._settings(),
                to_number="+919876543210",
                template_name="welcome",
                message_type="welcome",
                parameters=["Trip statement"],
                header_parameters=["media-123"],
            )

        self.assertTrue(raised.exception.delivery_unknown)

    async def test_rejects_missing_media_header_or_wrong_body_count_before_http(self) -> None:
        client = types.SimpleNamespace(post=AsyncMock())

        with self.assertRaisesRegex(WhatsAppCloudApiError, "one image header"):
            await send_whatsapp_template(
                client=client,
                settings=self._settings(),
                to_number="+919876543210",
                template_name="approved_welcome_template",
                message_type="welcome",
                header_parameters=[],
                parameters=["Trip statement"],
            )
        with self.assertRaisesRegex(WhatsAppCloudApiError, "exactly 4"):
            await send_whatsapp_template(
                client=client,
                settings=self._settings(),
                to_number="+919876543210",
                template_name="approved_passport_template",
                message_type="passport_link",
                parameters=["intro", "https://example.test", "instructions"],
            )

        client.post.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
