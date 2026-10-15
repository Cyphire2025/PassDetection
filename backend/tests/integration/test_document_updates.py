"""Real HTTP/SQL update audiences and idempotent outbox writes; no provider calls."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    DocumentWhatsAppDeliveryModel,
    PassportSubmissionModel,
    UserModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.database.whatsapp_send_intent_models import WhatsAppSendIntentModel
from app.infrastructure.repositories.user_repository import UserRepository
from app.infrastructure.whatsapp import web_publication
from app.infrastructure.whatsapp.traveller_destinations import TravellerDestination
from app.presentation.api.v1.routes import document_distribution_delivery as document_routes
from app.presentation.api.v1.routes import (
    document_distribution_delivery_preview as document_preview,
)
from app.presentation.api.v1.routes import document_update_preview as preview_module
from app.presentation.api.v1.routes import document_updates as routes
from app.presentation.dependencies.auth import get_current_active_user


@pytest.fixture
async def updates(db_session, monkeypatch):
    agency = AgencyModel(id=uuid.uuid4(), name="Updates", email="agency@example.test")
    db_session.add(agency)
    await db_session.flush()
    actor = UserModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        role="agency_admin",
        email="admin@example.test",
        hashed_password="unused",
        full_name="Staff",
        is_active=True,
    )
    group = ClientGroupModel(
        id=uuid.uuid4(), agency_id=agency.id, name="Trip", token=uuid.uuid4().hex
    )
    broadcast = WhatsAppBroadcastGroupModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        name="Audience",
        recipient_opt_in_confirmed_at=datetime.now(UTC),
    )
    db_session.add_all([actor, group, broadcast])
    await db_session.flush()
    passengers = [
        PassportSubmissionModel(
            id=uuid.uuid4(),
            agency_id=agency.id,
            group_id=group.id,
            client_name=f"Person {i}",
            image_s3_key="test/passport",
            status="staff_approved",
        )
        for i in range(5)
    ]
    recipients = [
        WhatsAppBroadcastRecipientModel(
            id=uuid.uuid4(),
            agency_id=agency.id,
            broadcast_group_id=broadcast.id,
            name=f"Contact {i}",
            phone_number=f"+9198765432{i:02}",
            normalized_phone_number=f"+9198765432{i:02}",
        )
        for i in range(4)
    ]
    db_session.add_all([*passengers, *recipients])
    await db_session.commit()
    destinations = [
        TravellerDestination(
            passenger_id=person.id,
            passenger_name=person.client_name,
            phone_number=recipients[min(i, 3)].normalized_phone_number,
            recipient_id=recipients[min(i, 3)].id,
            broadcast_group_id=broadcast.id,
            phone_source="linked_broadcast",
        )
        for i, person in enumerate(passengers)
    ]

    async def load_destinations(*_, **__):
        return destinations

    monkeypatch.setattr(preview_module, "load_traveller_destinations", load_destinations)
    monkeypatch.setattr(
        preview_module, "configured_template_name", AsyncMock(return_value="pending_v1")
    )
    monkeypatch.setattr(
        preview_module,
        "get_settings",
        lambda: SimpleNamespace(whatsapp_access_token="test", whatsapp_phone_number_id="test"),
    )
    publish = AsyncMock(return_value=1)
    monkeypatch.setattr(web_publication, "run_whatsapp_send_publication", publish)
    actor_entity = await UserRepository(db_session).get_by_id(actor.id)
    app = FastAPI()
    app.include_router(routes.router)
    app.include_router(document_routes.router)
    app.dependency_overrides[get_current_active_user] = lambda: actor_entity
    app.dependency_overrides[get_db_session] = lambda: db_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield SimpleNamespace(
            client=client,
            group=group,
            agency=agency,
            passengers=passengers,
            recipients=recipients,
            destinations=destinations,
            publish=publish,
            session=db_session,
        )


def path(updates, lane="visa"):
    return f"/groups/{updates.group.id}/{lane}"


async def document(updates, index, *, status=None, lane="visa", match_status="matched"):
    batch = DocumentDistributionBatchModel(
        id=uuid.uuid4(),
        agency_id=updates.agency.id,
        group_id=updates.group.id,
        document_type=lane,
        status="saved",
        uploaded_count=1,
        matched_count=1,
    )
    updates.session.add(batch)
    await updates.session.flush()
    doc = DistributedDocumentModel(
        id=uuid.uuid4(),
        batch_id=batch.id,
        agency_id=updates.agency.id,
        group_id=updates.group.id,
        passenger_id=updates.passengers[index].id,
        document_type=lane,
        original_filename="test.pdf",
        storage_key="test/document",
        match_status=match_status,
    )
    updates.session.add(doc)
    await updates.session.flush()
    if status:
        updates.session.add(
            DocumentWhatsAppDeliveryModel(
                id=uuid.uuid4(),
                agency_id=updates.agency.id,
                group_id=updates.group.id,
                document_batch_id=batch.id,
                distributed_document_id=doc.id,
                passenger_id=updates.passengers[index].id,
                send_batch_id=uuid.uuid4(),
                document_type=lane,
                document_filename="test.pdf",
                passenger_name=f"Person {index}",
                phone_number="+919876543200",
                normalized_phone_number="+919876543200",
                template_name="documents_v1",
                status=status,
                attempt_count=1,
            )
        )
    await updates.session.commit()
    return doc


@pytest.mark.parametrize(
    "lane",
    [
        "visa",
        "flight_ticket",
        "flight_ticket_arrival",
        "flight_ticket_domestic",
        "flight_ticket_domestic_arrival",
    ],
)
async def test_preview_includes_missing_failed_unknown_partial_but_not_confirmed(updates, lane):
    await document(updates, 0, status="submitted", lane=lane)
    await document(updates, 1, status="delivery_unknown", lane=lane)
    await document(updates, 2, status="failed", lane=lane)
    await document(updates, 3, status="read", lane=lane)
    await document(updates, 3, lane=lane)
    response = await updates.client.get(path(updates, lane) + "/update-preview")
    assert response.status_code == 200, response.text
    rows = {row["passenger_name"]: row for row in response.json()["recipients"]}
    assert not rows["Person 0"]["eligible"]
    assert all(rows[f"Person {i}"]["eligible"] for i in range(1, 5))
    assert rows["Person 3"]["confirmed_count"] == 1
    assert rows["Person 3"]["document_count"] == 2


async def test_queue_deduplicates_shared_phone_freezes_template_and_is_idempotent(updates):
    preview = (await updates.client.get(path(updates) + "/update-preview")).json()
    payload = {
        "request_id": str(uuid.uuid4()),
        "preview_token": preview["preview_token"],
        "passenger_ids": [str(row.id) for row in updates.passengers],
        "message_content": "Your visas are being processed.",
    }
    response = await updates.client.post(path(updates) + "/send-update", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["queued_count"] == 4
    assert response.json()["passenger_count"] == 5
    replay = await updates.client.post(path(updates) + "/send-update", json=payload)
    assert replay.json() == response.json()
    logs = list((await updates.session.scalars(select(WhatsAppMessageLogModel))).all())
    assert len(logs) == 4
    assert all(log.template_parameter_values == [payload["message_content"]] for log in logs)
    assert all(
        log.header_parameter_values == [] and log.template_name == "pending_v1" for log in logs
    )
    assert all(log.message_type == "document_update" for log in logs)
    assert sorted(len(log.document_update_context["passenger_ids"]) for log in logs) == [1, 1, 1, 2]
    assert len((await updates.session.scalars(select(WhatsAppSendIntentModel))).all()) == 1
    assert updates.publish.await_count == 1
    assert not list((await updates.session.scalars(select(DocumentWhatsAppDeliveryModel))).all())
    changed = {**payload, "message_content": "Different content"}
    assert (
        await updates.client.post(path(updates) + "/send-update", json=changed)
    ).status_code == 409


async def test_stale_preview_or_confirmed_selection_cannot_queue(updates):
    preview = (await updates.client.get(path(updates) + "/update-preview")).json()
    await document(updates, 0, status="sent")
    payload = {
        "request_id": str(uuid.uuid4()),
        "preview_token": preview["preview_token"],
        "passenger_ids": [str(updates.passengers[0].id)],
        "message_content": "Update",
    }
    assert (
        await updates.client.post(path(updates) + "/send-update", json=payload)
    ).status_code == 409
    fresh = (await updates.client.get(path(updates) + "/update-preview")).json()
    payload["preview_token"] = fresh["preview_token"]
    assert (
        await updates.client.post(path(updates) + "/send-update", json=payload)
    ).status_code == 409
    assert not list((await updates.session.scalars(select(WhatsAppMessageLogModel))).all())


async def test_superseded_pdf_does_not_remove_passenger_from_update_audience(updates):
    await document(updates, 0, status="read", match_status="superseded")
    await document(updates, 0)
    response = (await updates.client.get(path(updates) + "/update-preview")).json()
    assert response["recipients"][0]["eligible"]
    assert response["recipients"][0]["document_count"] == 1


async def test_broadcast_scope_excludes_other_destinations(updates):
    response = await updates.client.get(
        path(updates) + "/update-preview", params={"broadcast_group_id": str(uuid.uuid4())}
    )
    assert response.json()["recipients"] == []
    assert (
        await updates.client.get(f"/groups/{uuid.uuid4()}/visa/update-preview")
    ).status_code == 404


async def test_update_status_projection_is_lane_specific_and_preserves_pdf_state(updates):
    # create_all ignores PostgreSQL's partial-index predicate on SQLite. Mirror
    # the real predicate so different non-resend updates may share a recipient.
    await updates.session.execute(text("DROP INDEX uq_whatsapp_active_explicit_resend"))
    await updates.session.execute(text(
        "CREATE UNIQUE INDEX uq_whatsapp_active_explicit_resend "
        "ON whatsapp_message_logs (recipient_id, message_type) "
        "WHERE is_explicit_resend = 1 AND status IN ('queued', 'processing', 'delivery_unknown')"
    ))
    await document(updates, 0, status="delivery_unknown")
    now = datetime.now(UTC)
    visa_log = WhatsAppMessageLogModel(
        id=uuid.uuid4(), batch_id=uuid.uuid4(), agency_id=updates.agency.id,
        broadcast_group_id=updates.destinations[0].broadcast_group_id,
        recipient_id=updates.recipients[0].id, message_type="document_update",
        status="failed", error_message="Provider rejected the text update.",
        status_updated_at=now,
        document_update_context={"group_id": str(updates.group.id), "document_type": "visa",
                                 "passenger_ids": [str(updates.passengers[0].id)]},
    )
    flight_log = WhatsAppMessageLogModel(
        id=uuid.uuid4(), batch_id=uuid.uuid4(), agency_id=updates.agency.id,
        broadcast_group_id=updates.destinations[0].broadcast_group_id,
        recipient_id=updates.recipients[0].id, message_type="document_update",
        status="delivered", error_message=None, status_updated_at=now,
        document_update_context={"group_id": str(updates.group.id), "document_type": "flight_ticket",
                                 "passenger_ids": [str(updates.passengers[0].id)]},
    )
    updates.session.add_all([visa_log, flight_log])
    await updates.session.commit()
    visa = (await updates.client.get(path(updates) + "/update-preview")).json()["recipients"][0]
    flight = (await updates.client.get(path(updates, "flight_ticket") + "/update-preview")).json()["recipients"][0]
    assert visa["latest_update_status"] == "failed"
    assert visa["latest_update_error"] == "Provider rejected the text update."
    assert visa["latest_update_at"].startswith(now.date().isoformat())
    assert flight["latest_update_status"] == "delivered"
    assert flight["latest_update_error"] is None
    delivery = await updates.session.scalar(select(DocumentWhatsAppDeliveryModel))
    assert delivery.status == "delivery_unknown"
    # A later delivery receipt supersedes a previous failure explanation.
    visa_log.status = "delivered"
    await updates.session.commit()
    resolved = (await updates.client.get(path(updates) + "/update-preview")).json()["recipients"][0]
    assert resolved["latest_update_error"] is None


async def test_document_send_cannot_escape_recipient_broadcast_scope(updates, monkeypatch):
    from dataclasses import replace

    first = await document(updates, 0)
    outside = await document(updates, 1)
    updates.destinations[1] = replace(updates.destinations[1], broadcast_group_id=uuid.uuid4())
    monkeypatch.setattr(document_preview, "load_traveller_destinations", AsyncMock(return_value=updates.destinations))
    source = SimpleNamespace(id=updates.destinations[0].broadcast_group_id, name="Current broadcast")
    monkeypatch.setattr(document_preview, "linked_welcome_sources", AsyncMock(return_value=[source]))
    monkeypatch.setattr(document_preview, "configured_template_name", AsyncMock(return_value="documents_v1"))
    monkeypatch.setattr(document_preview, "get_settings", lambda: SimpleNamespace(whatsapp_access_token="test", whatsapp_phone_number_id="test"))
    publisher = AsyncMock(side_effect=AssertionError("Out-of-scope sends must never publish"))
    monkeypatch.setattr(document_routes, "publish_whatsapp_task", publisher)
    scoped = await updates.client.get(path(updates) + "/whatsapp-preview", params={"broadcast_group_id": str(source.id)})
    assert scoped.status_code == 200, scoped.text
    preview = scoped.json()
    assert [row["document_id"] for row in preview["recipients"]] == [str(first.id)]
    result = await updates.client.post(f"/batches/{first.batch_id}/whatsapp-send", json={
        "preview_token": preview["preview_token"], "broadcast_group_id": str(source.id),
        "document_ids": [str(outside.id)], "message_content_1": "Your visa", "message_content_2": "Please review",
    })
    assert result.status_code in {400, 409}, result.text
    publisher.assert_not_awaited()
    assert not list((await updates.session.scalars(select(DocumentWhatsAppDeliveryModel))).all())
