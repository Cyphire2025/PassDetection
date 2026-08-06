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
    WhatsAppCloudApiError,
    send_whatsapp_document_template,
    upload_whatsapp_document,
)
from app.infrastructure.whatsapp.document_delivery_runtime import (
    _propagate_first_released_document_batch,
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
            file_content=b"%PDF-1.7\npdf-content\n%%EOF",
            content_type="application/octet-stream",
        )
        provider_id = await send_whatsapp_document_template(
            client=client,
            settings=self._settings(),
            to_number="+919876543210",
            template_name="documents_v1",
            media_id=media_id,
            filename="visa.pdf",
            parameters=[
                "This is your attached VISA",
                "Kindly cross check all your details",
            ],
        )

        self.assertEqual(provider_id, "wamid.document-1")
        upload_payload = client.post.await_args_list[0].kwargs
        self.assertEqual(upload_payload["data"], {"messaging_product": "whatsapp"})
        self.assertEqual(upload_payload["files"]["file"][2], "application/pdf")
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
                {"type": "text", "text": "This is your attached VISA"},
                {"type": "text", "text": "Kindly cross check all your details"},
            ],
        )

    async def test_document_upload_rejects_non_pdf_before_meta(self) -> None:
        client = types.SimpleNamespace(post=AsyncMock())

        with self.assertRaises(WhatsAppCloudApiError) as raised:
            await upload_whatsapp_document(
                client=client,
                settings=self._settings(),
                file_name="renamed.pdf",
                file_content=b"not-a-pdf",
                content_type="application/pdf",
            )

        self.assertEqual(raised.exception.code, "WHATSAPP_DOCUMENT_INVALID")
        client.post.assert_not_awaited()

    async def test_document_upload_retains_safe_meta_error_reference(self) -> None:
        response = types.SimpleNamespace(
            status_code=400,
            json=lambda: {
                "error": {
                    "code": 100,
                    "error_subcode": 2388004,
                    "message": "sensitive provider detail",
                }
            },
        )
        client = types.SimpleNamespace(post=AsyncMock(return_value=response))

        with self.assertRaises(WhatsAppCloudApiError) as raised:
            await upload_whatsapp_document(
                client=client,
                settings=self._settings(),
                file_name="visa.pdf",
                file_content=b"%PDF-1.7\n%%EOF",
                content_type="application/pdf",
            )

        self.assertIn("Meta code 100", str(raised.exception))
        self.assertIn("subcode 2388004", str(raised.exception))
        self.assertNotIn("sensitive provider detail", str(raised.exception))

    def test_message_content_and_parameters_are_deterministic(self) -> None:
        self.assertEqual(
            document_template_parameters(
                message_content_1=" This is your attached FLIGHT TICKET ",
                message_content_2=" Kindly cross check all your details ",
            ),
            [
                "This is your attached FLIGHT TICKET",
                "Kindly cross check all your details",
            ],
        )
        rendered = render_document_message(
            message_content_1="This is your attached VISA",
            message_content_2="Kindly cross check all your details",
        )
        self.assertIn("Dear Delegates", rendered)
        self.assertIn("This is your attached VISA", rendered)
        self.assertIn("Kindly cross check all your details", rendered)
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

    async def test_worker_collapses_first_release_batch_and_skips_prior_release(self) -> None:
        agency_id = uuid.uuid4()
        group_id = uuid.uuid4()
        batch_id = uuid.uuid4()
        first_document_id = uuid.uuid4()
        resent_document_id = uuid.uuid4()
        first_passenger_id = uuid.uuid4()
        resent_passenger_id = uuid.uuid4()
        current = MagicMock()
        current.all.return_value = [
            types.SimpleNamespace(
                distributed_document_id=first_document_id,
                passenger_id=first_passenger_id,
            ),
            # Multiple files for one passenger still produce one mobile event.
            types.SimpleNamespace(
                distributed_document_id=uuid.uuid4(),
                passenger_id=first_passenger_id,
            ),
            types.SimpleNamespace(
                distributed_document_id=resent_document_id,
                passenger_id=resent_passenger_id,
            ),
        ]
        prior = MagicMock()
        prior.scalars.return_value = [resent_document_id]
        session = AsyncMock()
        session.execute.side_effect = [current, prior]

        propagation = AsyncMock(return_value=types.SimpleNamespace(sync_changes=3))
        with patch(
            "app.infrastructure.whatsapp.document_delivery_runtime."
            "propagate_mobile_passenger_change",
            propagation,
        ):
            count = await _propagate_first_released_document_batch(
                session,
                send_batch_id=batch_id,
                agency_id=agency_id,
                group_id=group_id,
            )

        self.assertEqual(count, 3)
        propagation.assert_awaited_once()
        kwargs = propagation.await_args.kwargs
        self.assertEqual(kwargs["passenger_submission_ids"], {first_passenger_id})
        self.assertEqual(
            kwargs["propagation_key"], f"document-delivery-batch:{batch_id}"
        )
        self.assertFalse(kwargs["reconcile_identities"])

    async def test_webhook_recovery_release_triggers_mobile_invalidation(self) -> None:
        now = datetime.now(tz=UTC)
        delivery = DocumentWhatsAppDeliveryModel(
            id=uuid.uuid4(),
            agency_id=uuid.uuid4(),
            group_id=uuid.uuid4(),
            passenger_id=uuid.uuid4(),
            send_batch_id=uuid.uuid4(),
            document_type="flight_ticket",
            document_filename="ticket.pdf",
            passenger_name="Passenger",
            phone_number="+919876543210",
            normalized_phone_number="+919876543210",
            template_name="global_connect_document_v1",
            status="delivery_unknown",
            attempt_count=1,
            provider_message_id="wamid.document-recovered",
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
                                                    "id": "wamid.document-recovered",
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
        propagation = AsyncMock(return_value=types.SimpleNamespace(sync_changes=1))
        with (
            patch(
                "app.presentation.api.v1.routes.whatsapp.get_settings",
                return_value=types.SimpleNamespace(
                    whatsapp_app_secret="",
                    is_production=False,
                ),
            ),
            patch(
                "app.presentation.api.v1.routes.whatsapp."
                "propagate_mobile_passenger_change",
                propagation,
            ),
        ):
            response = await receive_whatsapp_webhook(
                request=request,
                x_hub_signature_256=None,
                session=session,
            )

        self.assertEqual(response.processed_statuses, 1)
        self.assertEqual(delivery.status, "delivered")
        propagation.assert_awaited_once()
        self.assertEqual(
            propagation.await_args.kwargs["passenger_submission_ids"],
            {delivery.passenger_id},
        )
        session.commit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
