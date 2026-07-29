"""Tests for QR rendering, template transport, and delivery receipts."""

from __future__ import annotations

import io
import json
import types
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image

from app.application.use_cases.whatsapp.qr_templates import (
    QR_DEFAULT_MESSAGE_CONTENT,
    qr_template_parameters,
    render_qr_message,
)
from app.infrastructure.database.models import PassengerQrWhatsAppDeliveryModel
from app.infrastructure.qr.qr_image_renderer import render_attendance_qr_png
from app.infrastructure.whatsapp.cloud_api_provider import (
    send_whatsapp_qr_template,
)
from app.infrastructure.whatsapp.qr_delivery_runtime import (
    apply_qr_provider_status,
)
from app.presentation.api.v1.routes.tour_operations_qr_delivery import (
    _recover_stale_qr_deliveries,
)
from app.presentation.api.v1.routes.whatsapp import receive_whatsapp_webhook


class QrWhatsAppDeliveryTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _settings() -> types.SimpleNamespace:
        return types.SimpleNamespace(
            whatsapp_access_token="test-token",
            whatsapp_phone_number_id="123456789",
            whatsapp_api_version="v25.0",
            whatsapp_template_language="en",
        )

    @staticmethod
    def _delivery(
        *,
        now: datetime,
        provider_message_id: str | None = None,
    ) -> PassengerQrWhatsAppDeliveryModel:
        return PassengerQrWhatsAppDeliveryModel(
            id=uuid.uuid4(),
            agency_id=uuid.uuid4(),
            group_id=uuid.uuid4(),
            passenger_id=uuid.uuid4(),
            qr_token_id=uuid.uuid4(),
            send_batch_id=uuid.uuid4(),
            passenger_name="Asha Singh",
            phone_number="+919876543210",
            normalized_phone_number="+919876543210",
            template_name="qrcode_v1",
            template_parameter_values=[QR_DEFAULT_MESSAGE_CONTENT],
            status="submitted",
            attempt_count=1,
            provider_message_id=provider_message_id,
            status_updated_at=now,
            created_at=now,
            updated_at=now,
        )

    def test_qr_renderer_returns_a_decodable_png(self) -> None:
        content = render_attendance_qr_png("pdatt:" + "A" * 43)
        self.assertTrue(content.startswith(b"\x89PNG\r\n\x1a\n"))
        with Image.open(io.BytesIO(content)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.width, image.height)
            self.assertGreaterEqual(image.width, 300)

    async def test_send_uses_an_image_header_and_one_body_parameter(self) -> None:
        response = types.SimpleNamespace(
            status_code=200,
            json=lambda: {"messages": [{"id": "wamid.qr-1"}]},
        )
        client = types.SimpleNamespace(post=AsyncMock(return_value=response))

        provider_id = await send_whatsapp_qr_template(
            client=client,
            settings=self._settings(),
            to_number="+919876543210",
            template_name="qrcode_v1",
            media_id="media-qr-1",
            parameters=qr_template_parameters(
                message_content=QR_DEFAULT_MESSAGE_CONTENT,
            ),
        )

        self.assertEqual(provider_id, "wamid.qr-1")
        payload = client.post.await_args.kwargs["json"]
        self.assertEqual(payload["to"], "919876543210")
        self.assertEqual(payload["template"]["name"], "qrcode_v1")
        self.assertEqual(
            payload["template"]["components"],
            [
                {
                    "type": "header",
                    "parameters": [{"type": "image", "image": {"id": "media-qr-1"}}],
                },
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": QR_DEFAULT_MESSAGE_CONTENT}],
                },
            ],
        )

    def test_message_content_is_trimmed_and_rendered_in_approved_layout(self) -> None:
        self.assertEqual(
            qr_template_parameters(message_content=" Individual QR message "),
            ["Individual QR message"],
        )
        rendered = render_qr_message(message_content="Individual QR message")
        self.assertIn("Dear Delegates", rendered)
        self.assertIn("Individual QR message", rendered)
        self.assertIn("Team Global Connect Travels", rendered)

    def test_receipts_are_monotonic_and_late_failures_do_not_regress_read(self) -> None:
        now = datetime.now(tz=UTC)
        delivery = self._delivery(now=now)
        apply_qr_provider_status(
            delivery,
            provider_status="read",
            error_message=None,
            provider_status_at=now,
            now=now,
        )
        apply_qr_provider_status(
            delivery,
            provider_status="failed",
            error_message="late failure",
            provider_status_at=now + timedelta(seconds=1),
            now=now + timedelta(seconds=1),
        )
        self.assertEqual(delivery.status, "read")

    async def test_preview_recovery_distinguishes_safe_queue_retry_from_unknown_delivery(
        self,
    ) -> None:
        queued_result = types.SimpleNamespace(rowcount=1)
        processing_result = types.SimpleNamespace(rowcount=2)
        session = AsyncMock()
        session.execute.side_effect = [queued_result, processing_result]
        group = types.SimpleNamespace(
            id=uuid.uuid4(),
            agency_id=uuid.uuid4(),
        )

        recovered = await _recover_stale_qr_deliveries(
            session,
            group=group,
            now=datetime.now(tz=UTC),
        )

        self.assertEqual(recovered, 3)
        self.assertEqual(session.execute.await_count, 2)
        queued_statement = str(session.execute.await_args_list[0].args[0])
        processing_statement = str(session.execute.await_args_list[1].args[0])
        self.assertIn("passenger_qr_whatsapp_deliveries.status", queued_statement)
        self.assertIn("passenger_qr_whatsapp_deliveries.status", processing_statement)

    async def test_webhook_updates_qr_delivery_when_no_other_log_matches(self) -> None:
        now = datetime.now(tz=UTC)
        delivery = self._delivery(
            now=now,
            provider_message_id="wamid.qr-1",
        )
        empty_logs = MagicMock()
        empty_logs.scalars.return_value.all.return_value = []
        empty_documents = MagicMock()
        empty_documents.scalars.return_value.all.return_value = []
        qr_rows = MagicMock()
        qr_rows.scalars.return_value.all.return_value = [delivery]
        session = AsyncMock()
        session.execute.side_effect = [empty_logs, empty_documents, qr_rows]
        request = types.SimpleNamespace(
            body=AsyncMock(
                return_value=json.dumps(
                    {
                        "entry": [
                            {
                                "changes": [
                                    {
                                        "value": {
                                            "statuses": [
                                                {
                                                    "id": "wamid.qr-1",
                                                    "status": "delivered",
                                                    "timestamp": "1784419200",
                                                }
                                            ]
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ).encode("utf-8")
            )
        )
        with patch(
            "app.presentation.api.v1.routes.whatsapp.get_settings",
            return_value=types.SimpleNamespace(
                whatsapp_app_secret="",
                is_production=False,
            ),
        ):
            response = await receive_whatsapp_webhook(
                request=request,
                x_hub_signature_256=None,
                session=session,
            )
        self.assertEqual(response.processed_statuses, 1)
        self.assertEqual(delivery.status, "delivered")
        session.commit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
