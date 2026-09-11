"""Real database tests for welcome identity, provider outcomes and replay safety."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
    WhatsAppPhoneWelcomeAttemptModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.whatsapp import traveller_welcome_runtime as runtime
from app.infrastructure.whatsapp.phone_welcome import (
    claim_phone_welcome,
    fail_unclaimed_traveller_welcomes,
    order_welcome_receipts,
    require_welcome_delivered,
    sync_phone_welcome,
    welcome_states_for_phones,
)
from app.infrastructure.whatsapp.welcome_recovery import recover_stale_welcomes
from app.presentation.api.v1.routes.whatsapp_delivery_support import (
    _provider_status_state_predicates,
)

PHONE = "+919876543210"


async def _agency(session: AsyncSession) -> uuid.UUID:
    agency_id = uuid.uuid4()
    session.add(AgencyModel(id=agency_id, name="Agency", email=f"{agency_id}@example.test"))
    await session.commit()
    return agency_id


@pytest.mark.parametrize(
    "status", ["queued", "processing", "submitted", "sent", "delivery_unknown", "delivered", "read"]
)
async def test_phone_claim_suppresses_across_sources_and_only_delivery_unlocks(db_session, status):
    agency = await _agency(db_session)
    first, second = uuid.uuid4(), uuid.uuid4()
    assert (
        await claim_phone_welcome(
            db_session, agency_id=agency, phone=PHONE, attempt_id=first, attempt_kind="broadcast"
        )
        == "claimed"
    )
    await sync_phone_welcome(
        db_session, agency_id=agency, phone=PHONE, attempt_id=first, status=status
    )
    await db_session.commit()
    assert (
        await claim_phone_welcome(
            db_session, agency_id=agency, phone=PHONE, attempt_id=second, attempt_kind="traveller"
        )
        == status
    )
    assert await require_welcome_delivered(db_session, agency_id=agency, phone=PHONE) == (
        status in {"delivered", "read"}
    )
    other_agency = await _agency(db_session)
    assert not await require_welcome_delivered(db_session, agency_id=other_agency, phone=PHONE)
    assert (
        await claim_phone_welcome(
            db_session,
            agency_id=other_agency,
            phone=PHONE,
            attempt_id=second,
            attempt_kind="traveller",
        )
        == "claimed"
    )


async def test_old_failure_cannot_release_retry_and_old_success_prevents_duplicate(db_session):
    agency = await _agency(db_session)
    first, retry = uuid.uuid4(), uuid.uuid4()
    await claim_phone_welcome(
        db_session, agency_id=agency, phone=PHONE, attempt_id=first, attempt_kind="broadcast"
    )
    await sync_phone_welcome(
        db_session, agency_id=agency, phone=PHONE, attempt_id=first, status="failed"
    )
    assert (
        await claim_phone_welcome(
            db_session, agency_id=agency, phone=PHONE, attempt_id=retry, attempt_kind="traveller"
        )
        == "claimed"
    )
    await sync_phone_welcome(
        db_session, agency_id=agency, phone=PHONE, attempt_id=first, status="failed"
    )
    assert (await welcome_states_for_phones(db_session, agency_id=agency, phones=[PHONE]))[
        PHONE
    ] == "queued"
    await sync_phone_welcome(
        db_session, agency_id=agency, phone=PHONE, attempt_id=first, status="delivered"
    )
    await sync_phone_welcome(
        db_session, agency_id=agency, phone=PHONE, attempt_id=retry, status="failed"
    )
    assert await require_welcome_delivered(db_session, agency_id=agency, phone=PHONE)
    assert not await require_welcome_delivered(db_session, agency_id=agency, phone="+919999999999")


async def _attempt(session: AsyncSession):
    agency = await _agency(session)
    group_id, broadcast_id, passenger_id, attempt_id, batch_id = (uuid.uuid4() for _ in range(5))
    session.add(
        ClientGroupModel(
            id=group_id, agency_id=agency, name="Journey", token=str(group_id), status="active"
        )
    )
    session.add(
        WhatsAppBroadcastGroupModel(
            id=broadcast_id,
            agency_id=agency,
            name="Original list",
            recipient_opt_in_confirmed_at=datetime.now(UTC),
        )
    )
    await session.flush()
    session.add(
        ClientGroupWhatsAppBroadcastLinkModel(
            client_group_id=group_id, broadcast_group_id=broadcast_id, agency_id=agency
        )
    )
    passenger = PassportSubmissionModel(
        id=passenger_id,
        agency_id=agency,
        group_id=group_id,
        client_name="Traveller",
        client_phone=PHONE,
        image_s3_key="test.jpg",
        status="staff_approved",
    )
    session.add(passenger)
    await claim_phone_welcome(
        session, agency_id=agency, phone=PHONE, attempt_id=attempt_id, attempt_kind="traveller"
    )
    attempt = WhatsAppPhoneWelcomeAttemptModel(
        id=attempt_id,
        batch_id=batch_id,
        agency_id=agency,
        group_id=group_id,
        broadcast_group_id=broadcast_id,
        passenger_ids=[str(passenger_id)],
        normalized_phone_number=PHONE,
        recipient_name="Traveller",
        template_name="saved_welcome",
        rendered_message="Reviewed company welcome",
        header_parameter_values=["saved-image"],
        template_parameter_values=["Reviewed company welcome"],
        status="queued",
    )
    session.add(attempt)
    await session.commit()
    return attempt, passenger


async def test_direct_worker_preserves_saved_content_and_never_repeats_provider_send(
    db_session, monkeypatch
):
    attempt, _ = await _attempt(db_session)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(runtime, "AsyncSessionFactory", factory)
    provider = AsyncMock(return_value="wamid.welcome")
    monkeypatch.setattr(runtime, "send_whatsapp_template", provider)
    await runtime.run_traveller_welcome_broadcast(batch_id=str(attempt.batch_id))
    await runtime.run_traveller_welcome_broadcast(batch_id=str(attempt.batch_id))
    provider.assert_awaited_once()
    assert provider.await_args.kwargs["to_number"] == PHONE
    assert provider.await_args.kwargs["parameters"] == ["Reviewed company welcome"]
    assert provider.await_args.kwargs["header_parameters"] == ["saved-image"]
    assert provider.await_args.kwargs["template_name"] == "saved_welcome"
    await db_session.refresh(attempt)
    assert attempt.status == "submitted"
    assert not await require_welcome_delivered(db_session, agency_id=attempt.agency_id, phone=PHONE)
    assert not (await db_session.execute(select(WhatsAppBroadcastRecipientModel))).scalars().all()


@pytest.mark.parametrize("change", ["phone", "approval", "source_opt_in", "source_link", "payload"])
async def test_direct_worker_rechecks_current_traveller_and_source_before_provider(
    db_session, monkeypatch, change
):
    attempt, passenger = await _attempt(db_session)
    if change == "phone":
        passenger.client_phone = "+919999999999"
    elif change == "approval":
        passenger.status = "pending"
    elif change == "source_opt_in":
        (
            await db_session.get(WhatsAppBroadcastGroupModel, attempt.broadcast_group_id)
        ).recipient_opt_in_confirmed_at = None
    elif change == "source_link":
        link = (
            await db_session.execute(select(ClientGroupWhatsAppBroadcastLinkModel))
        ).scalar_one()
        await db_session.delete(link)
    else:
        attempt.header_parameter_values = []
    await db_session.commit()
    monkeypatch.setattr(
        runtime, "AsyncSessionFactory", async_sessionmaker(db_session.bind, expire_on_commit=False)
    )
    provider = AsyncMock()
    monkeypatch.setattr(runtime, "send_whatsapp_template", provider)
    await runtime.run_traveller_welcome_broadcast(batch_id=str(attempt.batch_id))
    provider.assert_not_awaited()
    await db_session.refresh(attempt)
    assert attempt.status == "failed"


async def test_unknown_provider_result_blocks_retry_and_other_messages(db_session, monkeypatch):
    attempt, _ = await _attempt(db_session)
    monkeypatch.setattr(
        runtime, "AsyncSessionFactory", async_sessionmaker(db_session.bind, expire_on_commit=False)
    )
    provider = AsyncMock(side_effect=httpx.ReadTimeout("unknown"))
    monkeypatch.setattr(runtime, "send_whatsapp_template", provider)
    await runtime.run_traveller_welcome_broadcast(batch_id=str(attempt.batch_id))
    await runtime.run_traveller_welcome_broadcast(batch_id=str(attempt.batch_id))
    provider.assert_awaited_once()
    await db_session.refresh(attempt)
    assert attempt.status == "delivery_unknown"
    assert (
        await claim_phone_welcome(
            db_session,
            agency_id=attempt.agency_id,
            phone=PHONE,
            attempt_id=uuid.uuid4(),
            attempt_kind="broadcast",
        )
        == "delivery_unknown"
    )


async def test_publication_compensation_only_releases_queued_attempts(db_session):
    attempt, _ = await _attempt(db_session)
    await fail_unclaimed_traveller_welcomes(
        db_session, batch_id=attempt.batch_id, error_message="broker unavailable"
    )
    await db_session.commit()
    assert (
        await claim_phone_welcome(
            db_session,
            agency_id=attempt.agency_id,
            phone=PHONE,
            attempt_id=uuid.uuid4(),
            attempt_kind="traveller",
        )
        == "claimed"
    )


async def test_positive_receipt_for_old_phone_cannot_update_current_recipient_state(db_session):
    attempt, _ = await _attempt(db_session)
    recipient = WhatsAppBroadcastRecipientModel(
        agency_id=attempt.agency_id,
        broadcast_group_id=attempt.broadcast_group_id,
        phone_number="+919999999999",
        normalized_phone_number="+919999999999",
    )
    db_session.add(recipient)
    await db_session.flush()
    state = WhatsAppRecipientMessageStateModel(
        agency_id=attempt.agency_id,
        broadcast_group_id=attempt.broadcast_group_id,
        recipient_id=recipient.id,
        message_type="welcome",
        batch_id=attempt.batch_id,
        status="failed",
    )
    db_session.add(state)
    await db_session.flush()
    log = WhatsAppMessageLogModel(
        id=uuid.uuid4(),
        agency_id=attempt.agency_id,
        broadcast_group_id=attempt.broadcast_group_id,
        recipient_id=recipient.id,
        message_type="welcome",
        batch_id=attempt.batch_id,
        status="delivered",
        normalized_phone_number=PHONE,
    )
    result = await db_session.execute(
        select(WhatsAppRecipientMessageStateModel).where(
            *_provider_status_state_predicates(log, provider_status="delivered")
        )
    )
    assert result.scalar_one_or_none() is None


async def test_fresh_duplicate_worker_does_not_interrupt_live_claim_and_stale_claim_recovers(
    db_session, monkeypatch
):
    attempt, _ = await _attempt(db_session)
    attempt.status = "processing"
    await sync_phone_welcome(
        db_session,
        agency_id=attempt.agency_id,
        phone=PHONE,
        attempt_id=attempt.id,
        status="processing",
    )
    await db_session.commit()
    monkeypatch.setattr(
        runtime, "AsyncSessionFactory", async_sessionmaker(db_session.bind, expire_on_commit=False)
    )
    provider = AsyncMock()
    monkeypatch.setattr(runtime, "send_whatsapp_template", provider)
    await runtime.run_traveller_welcome_broadcast(batch_id=str(attempt.batch_id))
    await db_session.refresh(attempt)
    assert attempt.status == "processing"
    assert await recover_stale_welcomes(db_session) == 0
    assert (
        await recover_stale_welcomes(db_session, now=datetime.now(UTC) + timedelta(minutes=31)) == 1
    )
    await db_session.commit()
    assert attempt.status == "delivery_unknown"
    provider.assert_not_awaited()
    assert (
        await claim_phone_welcome(
            db_session,
            agency_id=attempt.agency_id,
            phone=PHONE,
            attempt_id=uuid.uuid4(),
            attempt_kind="broadcast",
        )
        == "delivery_unknown"
    )


async def test_provider_acceptance_is_reconciled_after_transient_commit_failure(
    db_session, monkeypatch
):
    attempt, _ = await _attempt(db_session)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(runtime, "AsyncSessionFactory", factory)
    provider = AsyncMock(return_value="wamid.reconciled")
    monkeypatch.setattr(runtime, "send_whatsapp_template", provider)
    original_commit = AsyncSession.commit
    failed_once = False

    async def commit_with_one_failure(session):
        nonlocal failed_once
        if provider.await_count and not failed_once:
            failed_once = True
            raise RuntimeError("transient local commit failure")
        await original_commit(session)

    monkeypatch.setattr(AsyncSession, "commit", commit_with_one_failure)
    await runtime.run_traveller_welcome_broadcast(batch_id=str(attempt.batch_id))
    await runtime.run_traveller_welcome_broadcast(batch_id=str(attempt.batch_id))
    provider.assert_awaited_once()
    await db_session.refresh(attempt)
    assert failed_once
    assert attempt.status == "submitted"
    assert attempt.provider_message_id == "wamid.reconciled"


async def test_direct_welcome_receipt_unlocks_number_and_late_failure_does_not_regress(db_session):
    attempt, _ = await _attempt(db_session)
    attempt.provider_message_id = "wamid.receipt"
    attempt.status = "submitted"
    await sync_phone_welcome(
        db_session,
        agency_id=attempt.agency_id,
        phone=PHONE,
        attempt_id=attempt.id,
        status="submitted",
    )
    await db_session.commit()
    assert not await require_welcome_delivered(db_session, agency_id=attempt.agency_id, phone=PHONE)
    assert (
        await runtime.process_traveller_welcome_receipt(
            db_session,
            provider_id=attempt.provider_message_id,
            provider_status="delivered",
            error_message=None,
            provider_status_at=datetime.now(UTC),
        )
        == 1
    )
    await db_session.commit()
    assert await require_welcome_delivered(db_session, agency_id=attempt.agency_id, phone=PHONE)

    await runtime.process_traveller_welcome_receipt(
        db_session,
        provider_id=attempt.provider_message_id,
        provider_status="failed",
        error_message="late",
        provider_status_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    assert await require_welcome_delivered(db_session, agency_id=attempt.agency_id, phone=PHONE)


async def test_multiple_phone_receipts_lock_canonically_and_keep_each_phone_time_order(db_session):
    first, _ = await _attempt(db_session)
    second, _ = await _attempt(db_session)
    first.provider_message_id = "wamid.first"
    second.provider_message_id = "wamid.second"
    await db_session.commit()
    now = datetime.now(UTC)
    events = [
        ("wamid.second", "read", None, now),
        ("wamid.first", "delivered", None, now),
        ("wamid.first", "sent", None, now - timedelta(seconds=1)),
    ]
    await order_welcome_receipts(db_session, events)
    keys = {"wamid.first": str(first.agency_id), "wamid.second": str(second.agency_id)}
    assert events == sorted(events, key=lambda item: (keys[item[0]], item[3]))
    assert [event[1] for event in events if event[0] == "wamid.first"] == ["sent", "delivered"]
