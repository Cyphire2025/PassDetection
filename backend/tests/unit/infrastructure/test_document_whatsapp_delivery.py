"""Tests for document-template transport and monotonic delivery receipts."""

from __future__ import annotations

import json
import types
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.application.use_cases.whatsapp.document_templates import (
    document_template_parameters,
    render_document_message,
)
from app.infrastructure.database.models import DocumentWhatsAppDeliveryModel
from app.infrastructure.whatsapp.cloud_api_provider import (
    send_whatsapp_document_template,
    upload_whatsapp_document,
)
from app.infrastructure.whatsapp.document_delivery_runtime import (
    apply_document_provider_status,
)
from app.presentation.api.v1.routes.whatsapp import receive_whatsapp_webhook


class DocumentWhatsAppDeliveryTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _settings() -> types.SimpleNamespace:
        return types.SimpleNamespace(
            whatsapp_access_token="test-token",
            whatsapp_phone_number_id="123456789",
            whatsapp_api_version="v25.0",
            whatsapp_template_language="en_US",
        )

    async def test_upload_and_send_use_a_document_header(self) -> None:
        upload_response = types.SimpleNamespace(
            status_code=200,
            json=lambda: {"id": "media-document-1"},
        )
        send_response = types.SimpleNamespace(
            status_code=200,
            json=lambda: {"messages": [{"id": "wamid.document-1"}]},
        )
        client = types.SimpleNamespace(
            post=AsyncMock(side_effect=[upload_response, send_response])
        )

        media_id = await upload_whatsapp_document(
            client=client,
            settings=self._settings(),
            file_name="visa.pdf",
            file_content=b"pdf-content",
            content_type="application/pdf",
        )
        provider_id = await send_whatsapp_document_template(
            client=client,
            settings=self._settings(),
            to_number="+919876543210",
            template_name="global_connect_document_v1",
            media_id=media_id,
            filename="visa.pdf",
            parameters=["Asha Singh", "Visa", "Thailand 2026"],
        )

        self.assertEqual(provider_id, "wamid.document-1")
        send_payload = client.post.await_args_list[1].kwargs["json"]
        components = send_payload["template"]["components"]
        self.assertEqual(
            components[0]["parameters"],
            [
                {
                    "type": "document",
                    "document": {
                        "id": "media-document-1",
                        "filename": "visa.pdf",
                    },
                }
            ],
        )
        self.assertEqual(
            components[1]["parameters"],
            [
                {"type": "text", "text": "Asha Singh"},
                {"type": "text", "text": "Visa"},
                {"type": "text", "text": "Thailand 2026"},
            ],
        )

    def test_message_content_and_parameters_are_deterministic(self) -> None:
        self.assertEqual(
            document_template_parameters(
                passenger_name=" Asha Singh ",
                document_type="flight_ticket",
                group_name=" Thailand 2026 ",
            ),
            ["Asha Singh", "Flight Ticket", "Thailand 2026"],
        )
        rendered = render_document_message(
            passenger_name="Asha Singh",
            document_type="visa",
            group_name="Thailand 2026",
        )
        self.assertIn("Your Visa for Thailand 2026 is attached", rendered)
        self.assertIn("Team Global Connect Travels", rendered)

    def test_receipts_are_monotonic_and_late_failures_do_not_regress_read(self) -> None:
        now = datetime.now(tz=UTC)
        delivery = DocumentWhatsAppDeliveryModel(
            id=uuid.uuid4(),
            agency_id=uuid.uuid4(),
            group_id=uuid.uuid4(),
            send_batch_id=uuid.uuid4(),
            document_type="visa",
            document_filename="visa.pdf",
            passenger_name="Asha Singh",
            phone_number="+919876543210",
            normalized_phone_number="+919876543210",
            template_name="global_connect_document_v1",
            status="submitted",
            attempt_count=1,
            status_updated_at=now,
            created_at=now,
            updated_at=now,
        )
        apply_document_provider_status(
            delivery,
            provider_status="read",
            error_message=None,
            provider_status_at=now,
            now=now,
        )
        apply_document_provider_status(
            delivery,
            provider_status="failed",
            error_message="late failure",
            provider_status_at=now + timedelta(seconds=1),
            now=now + timedelta(seconds=1),
        )
        self.assertEqual(delivery.status, "read")

    async def test_webhook_updates_document_delivery_when_no_broadcast_log(self) -> None:
        now = datetime.now(tz=UTC)
        delivery = DocumentWhatsAppDeliveryModel(
            id=uuid.uuid4(),
            agency_id=uuid.uuid4(),
            group_id=uuid.uuid4(),
            send_batch_id=uuid.uuid4(),
            document_type="visa",
            document_filename="visa.pdf",
            passenger_name="Asha Singh",
            phone_number="+919876543210",
            normalized_phone_number="+919876543210",
            template_name="global_connect_document_v1",
            status="submitted",
            attempt_count=1,
            provider_message_id="wamid.document-1",
            status_updated_at=now,
            created_at=now,
            updated_at=now,
        )
        empty_logs = MagicMock()
        empty_logs.scalars.return_value.all.return_value = []
        document_rows = MagicMock()
        document_rows.scalars.return_value.all.return_value = [delivery]
        session = AsyncMock()
        session.execute.side_effect = [empty_logs, document_rows]
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
                                                    "id": "wamid.document-1",
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
