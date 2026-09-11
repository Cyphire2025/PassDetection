"""Actual HTTP review, welcome prerequisite and submitted document destinations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    DocumentWhatsAppDeliveryModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
    WhatsAppPhoneWelcomeAttemptModel,
    WhatsAppPhoneWelcomeModel,
)
from app.infrastructure.whatsapp.phone_welcome import sync_phone_welcome
from app.presentation.api.v1.routes import document_distribution_delivery, traveller_welcome
from tests.traveller_delivery_fixtures import (
    FATHER_PHONE,
    MOTHER_PHONE,
    QUALIFIER_PHONE,
    WELCOME_TEXT,
    seed_traveller_delivery,
)

PREFIX = "/api/v1/document-distribution"


@pytest.fixture(autouse=True)
def configured_provider(monkeypatch):
    from app.core.config.settings import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "whatsapp_access_token", "synthetic-access-token")
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "synthetic-sender")
    monkeypatch.setattr(settings, "whatsapp_document_template_name", "document-template")
    monkeypatch.setattr(traveller_welcome, "publish_whatsapp_task", AsyncMock())
    monkeypatch.setattr(document_distribution_delivery, "publish_whatsapp_task", AsyncMock())


async def welcome_preview(client, context, **params):
    response = await client.get(f"{PREFIX}/groups/{context.group.id}/whatsapp-welcome-preview", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def send_welcome(client, context, preview, **extra):
    return await client.post(f"{PREFIX}/groups/{context.group.id}/whatsapp-welcome-send", json={
        "phone_numbers": [row["phone_number"] for row in preview["recipients"] if row["eligible"]],
        "preview_token": preview["preview_token"], "source_broadcast_id": preview["source_broadcast_id"], **extra,
    })


async def send_documents(client, context):
    return await client.post(f"{PREFIX}/batches/{context.batch.id}/whatsapp-send", json={
        "document_ids": [str(row.id) for row in context.documents],
        "message_content_1": "Your travel document.", "message_content_2": "Safe travels.",
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("document_type", ["visa", "flight_ticket", "flight_ticket_arrival",
    "flight_ticket_domestic", "flight_ticket_domestic_arrival"])
async def test_parents_receive_documents_only_after_their_own_welcomes(db_session, client, document_type):
    context = await seed_traveller_delivery(db_session, client, document_type=document_type)
    preview = await welcome_preview(client, context)
    assert preview["summary"]["needs_welcome"] == 2
    assert {row["phone_number"] for row in preview["recipients"]} == {MOTHER_PHONE, FATHER_PHONE}
    assert all(WELCOME_TEXT in row["rendered_message"] for row in preview["recipients"])
    assert (await send_documents(client, context)).status_code == 409
    queued = await send_welcome(client, context, preview)
    assert queued.status_code == 202, queued.text
    assert queued.json()["queued_count"] == 2
    attempts = (await db_session.scalars(select(WhatsAppPhoneWelcomeAttemptModel))).all()
    assert len(attempts) == 2
    assert await db_session.scalar(select(func.count()).select_from(WhatsAppBroadcastRecipientModel)) == 1
    assert await db_session.scalar(select(func.count()).select_from(DocumentWhatsAppDeliveryModel)) == 0
    for attempt in attempts:
        assert attempt.header_parameter_values == ["original-image"]
        await sync_phone_welcome(db_session, agency_id=context.agency.id,
            phone=attempt.normalized_phone_number, attempt_id=attempt.id, status="sent")
    await db_session.commit()
    assert (await send_documents(client, context)).status_code == 409
    for attempt in attempts:
        await sync_phone_welcome(db_session, agency_id=context.agency.id,
            phone=attempt.normalized_phone_number, attempt_id=attempt.id, status="delivered")
    await db_session.commit()
    repeated = await send_welcome(client, context, preview)
    assert repeated.status_code == 202 and repeated.json()["queued_count"] == 0, repeated.text
    sent = await send_documents(client, context)
    assert sent.status_code == 202 and sent.json()["queued_count"] == 2, sent.text
    deliveries = (await db_session.scalars(select(DocumentWhatsAppDeliveryModel))).all()
    assert {row.normalized_phone_number for row in deliveries} == {MOTHER_PHONE, FATHER_PHONE}
    assert all(row.normalized_phone_number != QUALIFIER_PHONE for row in deliveries)
    assert all(row.recipient_id is None for row in deliveries)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["agency_staff", "agency_manager", "super_admin"])
async def test_original_phone_skips_welcome_and_existing_account_scope_works(db_session, client, role):
    context = await seed_traveller_delivery(db_session, client, phones=[QUALIFIER_PHONE, MOTHER_PHONE], role=role)
    preview = await welcome_preview(client, context)
    assert preview["summary"]["already_welcomed"] == 1
    assert preview["summary"]["needs_welcome"] == 1
    response = await send_welcome(client, context, preview)
    assert response.status_code == 202 and response.json()["queued_count"] == 1, response.text


@pytest.mark.asyncio
async def test_shared_entered_phone_gets_one_welcome_and_missing_phone_never_falls_back(db_session, client):
    context = await seed_traveller_delivery(db_session, client, phones=[MOTHER_PHONE, "9900000002", None])
    preview = await welcome_preview(client, context)
    assert preview["summary"] == {"total_numbers": 1, "needs_welcome": 1, "already_welcomed": 0,
                                  "in_progress": 0, "blocked": 1}
    contact = next(row for row in preview["recipients"] if row["phone_number"])
    assert len(contact["passenger_ids"]) == 2
    response = await send_welcome(client, context, preview)
    assert response.status_code == 202 and response.json()["queued_count"] == 1, response.text


@pytest.mark.asyncio
async def test_corrected_phone_rejects_stale_review_without_queuing(db_session, client):
    context = await seed_traveller_delivery(db_session, client)
    preview = await welcome_preview(client, context)
    context.passengers[0].client_phone = "+919900000044"
    await db_session.commit()
    response = await send_welcome(client, context, preview)
    assert response.status_code == 409
    assert await db_session.scalar(select(func.count()).select_from(WhatsAppPhoneWelcomeAttemptModel)) == 0


@pytest.mark.asyncio
async def test_image_replacement_preserves_original_welcome_text(db_session, client):
    context = await seed_traveller_delivery(db_session, client)
    preview = await welcome_preview(client, context, header_image_id="replacement-image")
    response = await send_welcome(client, context, preview, header_image_id="replacement-image")
    assert response.status_code == 202, response.text
    attempts = (await db_session.scalars(select(WhatsAppPhoneWelcomeAttemptModel))).all()
    assert all(row.header_parameter_values == ["replacement-image"] for row in attempts)
    assert all(row.template_parameter_values[0] == WELCOME_TEXT for row in attempts)


@pytest.mark.asyncio
async def test_original_legacy_text_welcome_retains_its_exact_parameters(db_session, client):
    context = await seed_traveller_delivery(db_session, client)
    log = await db_session.scalar(select(WhatsAppMessageLogModel))
    log.header_parameter_values = []
    log.template_parameter_values = [WELCOME_TEXT, "Original support contacts"]
    await db_session.commit()
    preview = await welcome_preview(client, context)
    assert preview["can_send"] is True
    response = await send_welcome(client, context, preview)
    assert response.status_code == 202, response.text
    attempts = (await db_session.scalars(select(WhatsAppPhoneWelcomeAttemptModel))).all()
    assert all(row.header_parameter_values == [] for row in attempts)
    assert all(row.template_parameter_values == log.template_parameter_values for row in attempts)
    replacement = await welcome_preview(client, context, header_image_id="replacement-image")
    assert replacement["can_send"] is False
    assert "Legacy text" in replacement["configuration_error"]


@pytest.mark.asyncio
async def test_default_source_uses_linked_broadcast_with_a_reusable_welcome(db_session, client):
    context = await seed_traveller_delivery(db_session, client)
    earlier = WhatsAppBroadcastGroupModel(id=uuid.uuid4(), agency_id=context.agency.id,
        name="Unused old list", recipient_opt_in_confirmed_at=datetime.now(tz=UTC),
        created_at=datetime(2020, 1, 1, tzinfo=UTC))
    db_session.add(earlier)
    await db_session.flush()
    db_session.add(ClientGroupWhatsAppBroadcastLinkModel(id=uuid.uuid4(), agency_id=context.agency.id,
        client_group_id=context.group.id, broadcast_group_id=earlier.id, matching_field_keys=[]))
    await db_session.commit()
    preview = await welcome_preview(client, context)
    assert preview["source_broadcast_id"] == str(context.source.id)
    assert preview["can_send"] is True
    explicit_empty = await welcome_preview(client, context, source_broadcast_id=str(earlier.id))
    assert explicit_empty["source_broadcast_id"] == str(earlier.id)
    assert explicit_empty["can_send"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("welcome_status", ["queued", "processing", "submitted", "sent", "failed", "delivery_unknown"])
async def test_every_unconfirmed_welcome_state_blocks_direct_document_send(db_session, client, welcome_status):
    context = await seed_traveller_delivery(db_session, client, phones=[MOTHER_PHONE])
    db_session.add(WhatsAppPhoneWelcomeModel(id=uuid.uuid4(), agency_id=context.agency.id,
        normalized_phone_number=MOTHER_PHONE, status=welcome_status,
        attempt_id=uuid.uuid4(), attempt_kind="traveller"))
    await db_session.commit()
    response = await send_documents(client, context)
    assert response.status_code == 409
    assert await db_session.scalar(select(func.count()).select_from(DocumentWhatsAppDeliveryModel)) == 0
