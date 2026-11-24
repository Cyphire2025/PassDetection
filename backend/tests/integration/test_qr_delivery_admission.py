"""QR queue admission keeps durable receipts, no duplicate sends and safe failure retry."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.infrastructure.database.models import PassengerQrWhatsAppDeliveryModel, UserModel
from app.presentation.api.v1.routes import tour_operations_qr_delivery as routes
from tests.dashboard_session_fixtures import issue_dashboard_access
from tests.unit.infrastructure.test_private_delivery_policy import _seed_private_delivery_context


@pytest.mark.parametrize("broker_fails", [False, True])
async def test_qr_admission_keeps_one_receipt_and_retries_only_known_queue_failure(
    client, db_session, monkeypatch, broker_fails
):
    context = await _seed_private_delivery_context(db_session)
    token = context["token"]
    token.expires_at = datetime.now(tz=UTC) + timedelta(days=1)
    actor_id = uuid.uuid4()
    db_session.add(
        UserModel(
            id=actor_id,
            agency_id=context["agency"].id,
            email="qr-administrator@example.com",
            full_name="Synthetic QR administrator",
            role="agency_admin",
            hashed_password="unused",
        )
    )
    await db_session.commit()
    access, _ = await issue_dashboard_access(
        db_session,
        user_id=actor_id,
        agency_id=context["agency"].id,
        role="agency_admin",
    )
    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(
            whatsapp_access_token="synthetic-provider-token",
            whatsapp_phone_number_id="synthetic-phone-id",
        ),
    )
    from app.infrastructure.whatsapp.tasks import process_qr_whatsapp_broadcast

    def publish(*_args, **_kwargs):
        # Publication must occur only after the durable admission commit.
        assert not db_session.in_transaction()
        if broker_fails:
            raise RuntimeError("synthetic-secret-and-private-broker-location")

    publisher = MagicMock(side_effect=publish)
    monkeypatch.setattr(process_qr_whatsapp_broadcast, "apply_async", publisher)
    endpoint = f"/api/v1/tour-operations/groups/{context['group'].id}/qr-codes/whatsapp-send"
    body = {"qr_token_ids": [str(token.id)], "message_content": "Your synthetic QR"}
    headers = {"Authorization": f"Bearer {access}"}
    response = await client.post(endpoint, headers=headers, json=body)
    assert response.status_code == (503 if broker_fails else 202), response.text
    assert "synthetic-secret-and-private-broker-location" not in response.text
    deliveries = list((await db_session.scalars(select(PassengerQrWhatsAppDeliveryModel))).all())
    assert len(deliveries) == 1
    delivery = deliveries[0]
    assert delivery.qr_token_id == token.id and delivery.passenger_id == context["passengers"][0].id
    assert delivery.normalized_phone_number == context["recipient"].normalized_phone_number
    assert delivery.template_parameter_values == [body["message_content"]]
    assert delivery.provider_message_id is None and delivery.provider_media_id is None
    assert delivery.status == ("failed" if broker_fails else "queued")
    receipt_id, original_batch = delivery.id, delivery.send_batch_id
    await db_session.rollback()
    if broker_fails:
        publisher.side_effect = None
        retried = await client.post(endpoint, headers=headers, json=body)
        assert retried.status_code == 202, retried.text
        db_session.expire_all()
        rows = list((await db_session.scalars(select(PassengerQrWhatsAppDeliveryModel))).all())
        assert len(rows) == 1 and rows[0].id == receipt_id
        assert rows[0].status == "queued" and rows[0].send_batch_id != original_batch
    else:
        repeated = await client.post(endpoint, headers=headers, json=body)
        assert repeated.status_code == 409, repeated.text
        publisher.assert_called_once()
