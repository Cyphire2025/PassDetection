"""Traveller destinations stay passenger-bound and wait for a welcome receipt."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.database.models import (
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    PassportRosterResolutionModel,
    WhatsAppPhoneWelcomeModel,
)
from app.infrastructure.whatsapp import document_delivery_runtime, qr_delivery_runtime
from app.infrastructure.whatsapp.private_delivery_policy import (
    lock_private_delivery_group_source_snapshot,
    validate_private_delivery_recipient,
)
from tests.unit.infrastructure.test_private_delivery_policy import (
    NOW,
    PHONE,
    _document_delivery,
    _qr_delivery,
    _seed_private_delivery_context,
)

PARENT_PHONE = "+919876543211"
OTHER_PARENT_PHONE = "+919876543212"


def _welcome(agency_id: uuid.UUID, phone: str, status: str = "delivered"):
    return WhatsAppPhoneWelcomeModel(
        agency_id=agency_id,
        normalized_phone_number=phone,
        status=status,
        attempt_id=uuid.uuid4(),
        attempt_kind="traveller",
    )


async def _validate(session: AsyncSession, context, passenger, phone: str, source="submission"):
    return await validate_private_delivery_recipient(
        session,
        agency_id=context["agency"].id,
        group_id=context["group"].id,
        passenger_id=passenger.id,
        broadcast_group_id=context["broadcast"].id,
        recipient_id=context["recipient"].id,
        normalized_phone_number=phone,
        delivery_source=source,
    )


@pytest.mark.asyncio
async def test_qualifier_code_does_not_redirect_parents_private_documents(db_session):
    context = await _seed_private_delivery_context(db_session, passenger_count=2)
    context["link"].matching_field_keys = ["producer_code"]
    context["recipient"].imported_fields = {"Producer Code": "QUALIFIER-42"}
    for passenger, phone in zip(context["passengers"], [PARENT_PHONE, OTHER_PARENT_PHONE]):
        passenger.client_phone = phone
        passenger.custom_answers = [{"label": "Producer Code", "value": "QUALIFIER-42"}]
        db_session.add(_welcome(context["agency"].id, phone))
    await db_session.flush()

    for passenger, phone in zip(context["passengers"], [PARENT_PHONE, OTHER_PARENT_PHONE]):
        assert (await _validate(db_session, context, passenger, phone)).allowed
        assert not (await _validate(db_session, context, passenger, PHONE)).allowed
    # A known welcome on the qualifier's number never authorizes a different traveller number.
    mother, father = context["passengers"]
    assert not (await _validate(db_session, context, mother, OTHER_PARENT_PHONE)).allowed
    assert not (await _validate(db_session, context, father, PARENT_PHONE)).allowed


@pytest.mark.asyncio
async def test_explicit_shared_traveller_phone_can_receive_each_passengers_document(db_session):
    context = await _seed_private_delivery_context(db_session, passenger_count=2)
    for passenger in context["passengers"]:
        passenger.client_phone = "98765 43210"
    await db_session.flush()
    for passenger in context["passengers"]:
        assert (await _validate(db_session, context, passenger, PHONE)).allowed
        # QR's imported identity policy retains its stronger one-passenger requirement.
        assert not (await _validate(db_session, context, passenger, PHONE, "broadcast")).allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("phone", [None, "", "invalid", "+919876543211"])
async def test_document_destination_never_falls_back_to_qualifier_or_family_head(db_session, phone):
    context = await _seed_private_delivery_context(db_session)
    passenger = context["passengers"][0]
    passenger.client_phone = phone
    await db_session.flush()
    assert not (await _validate(db_session, context, passenger, PHONE)).allowed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "welcome_status", [None, "queued", "processing", "submitted", "sent", "failed", "delivery_unknown"]
)
@pytest.mark.parametrize("source", ["submission", "broadcast"])
async def test_private_documents_and_qr_require_confirmed_welcome(db_session, welcome_status, source):
    context = await _seed_private_delivery_context(db_session)
    passenger = context["passengers"][0]
    passenger.client_phone = PHONE
    state = (await db_session.execute(select(WhatsAppPhoneWelcomeModel))).scalar_one()
    if welcome_status is None:
        await db_session.delete(state)
    else:
        state.status = welcome_status
    await db_session.flush()
    result = await _validate(db_session, context, passenger, PHONE, source)
    assert not result.allowed
    assert result.reason and "welcome" in result.reason.lower()
    assert PHONE not in result.reason


@pytest.mark.asyncio
@pytest.mark.parametrize("welcome_status", ["delivered", "read"])
async def test_welcome_success_on_same_number_reuses_existing_broadcast_receipt(db_session, welcome_status):
    context = await _seed_private_delivery_context(db_session)
    passenger = context["passengers"][0]
    passenger.client_phone = PHONE
    state = (await db_session.execute(select(WhatsAppPhoneWelcomeModel))).scalar_one()
    state.status = welcome_status
    await db_session.flush()
    assert (await _validate(db_session, context, passenger, PHONE)).allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["phone", "approval", "opt_in", "rejected", "deleted_group"])
async def test_queue_snapshot_is_rejected_after_authoritative_source_changes(db_session, mutation):
    context = await _seed_private_delivery_context(db_session)
    passenger = context["passengers"][0]
    passenger.client_phone = PHONE
    await db_session.flush()
    assert (await _validate(db_session, context, passenger, PHONE)).allowed
    if mutation == "phone":
        passenger.client_phone = PARENT_PHONE
    elif mutation == "approval":
        passenger.status = "pending_upload"
    elif mutation == "opt_in":
        context["broadcast"].recipient_opt_in_confirmed_at = None
    elif mutation == "deleted_group":
        context["group"].deleted_at = NOW
    else:
        db_session.add(PassportRosterResolutionModel(
            agency_id=context["agency"].id,
            client_group_id=context["group"].id,
            submission_id=passenger.id,
            resolution_type="rejected",
            status="active",
        ))
    await db_session.flush()
    assert not (await _validate(db_session, context, passenger, PHONE)).allowed


@pytest.mark.asyncio
async def test_new_phone_does_not_inherit_previous_phone_welcome(db_session):
    context = await _seed_private_delivery_context(db_session)
    passenger = context["passengers"][0]
    passenger.client_phone = PARENT_PHONE
    await db_session.flush()
    assert not (await _validate(db_session, context, passenger, PARENT_PHONE)).allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["document", "qr"])
@pytest.mark.parametrize("welcome_status", ["delivered", "queued", "submitted", "delivery_unknown"])
async def test_worker_rechecks_welcome_before_provider_even_with_batch_snapshot(
    db_session, monkeypatch, kind, welcome_status
):
    context = await _seed_private_delivery_context(db_session)
    passenger = context["passengers"][0]
    passenger.client_phone = PHONE
    # Keep the fixture token valid relative to runtime's real clock.
    context["token"].expires_at = datetime.now(tz=UTC) + timedelta(days=1)
    state = (await db_session.execute(select(WhatsAppPhoneWelcomeModel))).scalar_one()
    state.status = welcome_status
    if kind == "document":
        batch = DocumentDistributionBatchModel(
            id=uuid.uuid4(), agency_id=context["agency"].id,
            group_id=context["group"].id, document_type="visa", status="saved",
        )
        document = DistributedDocumentModel(
            id=uuid.uuid4(), batch_id=batch.id, agency_id=context["agency"].id,
            group_id=context["group"].id, passenger_id=passenger.id,
            document_type="visa", original_filename="visa.pdf", storage_key="test/visa.pdf",
            match_status="matched",
        )
        delivery = _document_delivery(context, status="queued")
        delivery.document_batch_id = batch.id
        delivery.distributed_document_id = document.id
        db_session.add_all([batch, document])
        runtime = document_delivery_runtime
        runner = runtime.run_document_whatsapp_broadcast
        monkeypatch.setattr(runtime, "MinioStorageRepository", lambda: SimpleNamespace(
            get_file=AsyncMock(return_value=b"%PDF-1.7 fixture"),
        ))
        monkeypatch.setattr(runtime, "upload_whatsapp_document", AsyncMock(return_value="media"))
        send = AsyncMock(return_value="wamid.document")
        monkeypatch.setattr(runtime, "send_whatsapp_document_template", send)
    else:
        delivery = _qr_delivery(context, status="queued")
        runtime = qr_delivery_runtime
        runner = runtime.run_qr_whatsapp_broadcast
        # SQLite drops timezone metadata on reload; use an equally naive clock
        # only for this fixture while retaining the real token-expiry logic.
        production_qr_status = runtime.qr_status
        monkeypatch.setattr(runtime, "qr_status", lambda token: production_qr_status(
            token, now=datetime.now(tz=UTC).replace(tzinfo=token.expires_at.tzinfo),
        ))
        monkeypatch.setattr(runtime, "upload_whatsapp_image", AsyncMock(return_value="media"))
        monkeypatch.setattr(runtime, "render_attendance_qr_png", lambda *_: b"fixture-image")
        send = AsyncMock(return_value="wamid.qr")
        monkeypatch.setattr(runtime, "send_whatsapp_qr_template", send)
    db_session.add(delivery)
    await db_session.commit()
    snapshot = await lock_private_delivery_group_source_snapshot(
        db_session, agency_id=context["agency"].id, group_id=context["group"].id,
    )
    await db_session.commit()
    monkeypatch.setattr(runtime, "AsyncSessionFactory", async_sessionmaker(
        db_session.bind, expire_on_commit=False,
    ))
    await runner(send_batch_id=str(delivery.send_batch_id), _delivery_id=delivery.id,
                 _source_snapshot=snapshot, _client=SimpleNamespace())
    await db_session.refresh(delivery)
    if welcome_status == "delivered":
        assert send.await_count == 1
        assert send.await_args.kwargs["to_number"] == PHONE
        assert delivery.status == "submitted"
    else:
        send.assert_not_awaited()
        assert delivery.status == "failed"
        assert "welcome" in delivery.error_message.lower()
