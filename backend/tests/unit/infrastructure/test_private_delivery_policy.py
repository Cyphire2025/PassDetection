"""Fail-closed private WhatsApp recipient and mutation policy tests."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    DocumentWhatsAppDeliveryModel,
    PassengerQRTokenModel,
    PassengerQrWhatsAppDeliveryModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.whatsapp.document_delivery_runtime import (
    run_document_whatsapp_broadcast,
)
from app.infrastructure.whatsapp.private_delivery_policy import (
    PrivateDeliveryMutationBlocked,
    PrivateDeliveryRecipientValidation,
    prepare_private_delivery_identity_mutation,
    validate_private_delivery_recipient,
)

NOW = datetime(2026, 8, 2, 12, tzinfo=UTC)
PHONE = "+919876543210"


async def _seed_private_delivery_context(
    session: AsyncSession,
    *,
    passenger_count: int = 1,
) -> dict[str, object]:
    agency = AgencyModel(
        id=uuid.uuid4(),
        name="Agency",
        email=f"{uuid.uuid4()}@example.test",
    )
    group = ClientGroupModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        name="Trip",
        token=f"token-{uuid.uuid4()}",
        status="active",
        departure_cities=[],
        created_at=NOW,
    )
    broadcast = WhatsAppBroadcastGroupModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        name="Delegates",
        organizing_company_name="Agency",
        recipient_opt_in_confirmed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    recipient = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        broadcast_group_id=broadcast.id,
        name="Family contact",
        phone_number=PHONE,
        normalized_phone_number=PHONE,
        imported_fields={},
        created_at=NOW,
    )
    link = ClientGroupWhatsAppBroadcastLinkModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        client_group_id=group.id,
        broadcast_group_id=broadcast.id,
        created_at=NOW,
    )
    passengers = [
        PassportSubmissionModel(
            id=uuid.uuid4(),
            agency_id=agency.id,
            group_id=group.id,
            client_name=f"Passenger {index + 1}",
            family_head_phone=PHONE,
            image_s3_key=f"private-test/{index}.jpg",
            status="confirmed",
            confirmed_fields={},
            extracted_fields={},
            staff_metadata={},
            created_at=NOW,
            updated_at=NOW,
        )
        for index in range(passenger_count)
    ]
    token = PassengerQRTokenModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        passenger_id=passengers[0].id,
        token_hash=uuid.uuid4().hex,
        qr_payload="pdatt:" + "A" * 43,
        token_version=1,
        is_active=True,
        expires_at=NOW + timedelta(days=1),
        created_at=NOW,
        updated_at=NOW,
    )
    session.add_all([agency, group, broadcast, recipient, link, *passengers, token])
    await session.flush()
    return {
        "agency": agency,
        "group": group,
        "broadcast": broadcast,
        "recipient": recipient,
        "passengers": passengers,
        "token": token,
    }


def _document_delivery(context: dict[str, object], *, status: str) -> DocumentWhatsAppDeliveryModel:
    agency = context["agency"]
    group = context["group"]
    broadcast = context["broadcast"]
    recipient = context["recipient"]
    passenger = context["passengers"][0]
    return DocumentWhatsAppDeliveryModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        group_id=group.id,
        passenger_id=passenger.id,
        broadcast_group_id=broadcast.id,
        recipient_id=recipient.id,
        send_batch_id=uuid.uuid4(),
        document_type="visa",
        document_filename="visa.pdf",
        passenger_name=passenger.client_name,
        phone_number=PHONE,
        normalized_phone_number=PHONE,
        template_name="documents_v1",
        status=status,
        attempt_count=0,
        status_updated_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _qr_delivery(context: dict[str, object], *, status: str) -> PassengerQrWhatsAppDeliveryModel:
    agency = context["agency"]
    group = context["group"]
    broadcast = context["broadcast"]
    recipient = context["recipient"]
    passenger = context["passengers"][0]
    token = context["token"]
    return PassengerQrWhatsAppDeliveryModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        group_id=group.id,
        passenger_id=passenger.id,
        qr_token_id=token.id,
        broadcast_group_id=broadcast.id,
        recipient_id=recipient.id,
        send_batch_id=uuid.uuid4(),
        passenger_name=passenger.client_name,
        phone_number=PHONE,
        normalized_phone_number=PHONE,
        template_name="qrcode_v1",
        template_parameter_values=["Your QR"],
        status=status,
        attempt_count=0,
        status_updated_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.asyncio
async def test_shared_phone_between_passengers_fails_closed(
    db_session: AsyncSession,
) -> None:
    context = await _seed_private_delivery_context(db_session, passenger_count=2)

    result = await validate_private_delivery_recipient(
        db_session,
        agency_id=context["agency"].id,
        group_id=context["group"].id,
        passenger_id=context["passengers"][0].id,
        broadcast_group_id=context["broadcast"].id,
        recipient_id=context["recipient"].id,
        normalized_phone_number=PHONE,
    )

    assert result.allowed is False
    assert result.reason is not None
    assert PHONE not in result.reason


@pytest.mark.asyncio
async def test_queue_snapshot_is_revalidated_after_recipient_phone_changes(
    db_session: AsyncSession,
) -> None:
    context = await _seed_private_delivery_context(db_session)
    original = await validate_private_delivery_recipient(
        db_session,
        agency_id=context["agency"].id,
        group_id=context["group"].id,
        passenger_id=context["passengers"][0].id,
        broadcast_group_id=context["broadcast"].id,
        recipient_id=context["recipient"].id,
        normalized_phone_number=PHONE,
    )
    assert original.allowed is True

    context["recipient"].normalized_phone_number = "+919111111111"
    context["recipient"].phone_number = "+919111111111"
    await db_session.flush()

    changed = await validate_private_delivery_recipient(
        db_session,
        agency_id=context["agency"].id,
        group_id=context["group"].id,
        passenger_id=context["passengers"][0].id,
        broadcast_group_id=context["broadcast"].id,
        recipient_id=context["recipient"].id,
        normalized_phone_number=PHONE,
    )
    assert changed.allowed is False


@pytest.mark.asyncio
async def test_final_validation_locks_every_authoritative_identity_source(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = await _seed_private_delivery_context(db_session)
    statements: list[object] = []
    original_execute = db_session.execute

    async def recording_execute(statement: object, *args: object, **kwargs: object) -> object:
        statements.append(statement)
        return await original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", recording_execute)
    result = await validate_private_delivery_recipient(
        db_session,
        agency_id=context["agency"].id,
        group_id=context["group"].id,
        passenger_id=context["passengers"][0].id,
        broadcast_group_id=context["broadcast"].id,
        recipient_id=context["recipient"].id,
        normalized_phone_number=PHONE,
    )

    assert result.allowed is True
    assert len(statements) == 4
    compiled = [
        str(statement.compile(dialect=postgresql.dialect()))
        for statement in statements
    ]
    assert all("FOR UPDATE" in sql for sql in compiled)
    assert "client_groups" in compiled[0]
    assert "client_group_whatsapp_broadcast_links" in compiled[1]
    assert "whatsapp_broadcast_groups" in compiled[1]
    assert "recipient_opt_in_confirmed_at IS NOT NULL" not in compiled[1]
    assert "whatsapp_broadcast_recipients" in compiled[2]
    assert "removed_at IS NULL" not in compiled[2]
    assert "suppressed_by_roster_resolution_id IS NULL" not in compiled[2]
    assert "passport_submissions" in compiled[3]
    assert "passport_submissions.status IN" not in compiled[3]


@pytest.mark.asyncio
async def test_locked_pending_submission_is_filtered_from_current_matcher(
    db_session: AsyncSession,
) -> None:
    context = await _seed_private_delivery_context(db_session)
    pending = PassportSubmissionModel(
        id=uuid.uuid4(),
        agency_id=context["agency"].id,
        group_id=context["group"].id,
        client_name="Pending passenger",
        family_head_phone=PHONE,
        image_s3_key="private-test/pending.jpg",
        status="pending_upload",
        confirmed_fields={},
        extracted_fields={},
        staff_metadata={},
        created_at=NOW,
        updated_at=NOW,
    )
    db_session.add(pending)
    await db_session.flush()

    result = await validate_private_delivery_recipient(
        db_session,
        agency_id=context["agency"].id,
        group_id=context["group"].id,
        passenger_id=context["passengers"][0].id,
        broadcast_group_id=context["broadcast"].id,
        recipient_id=context["recipient"].id,
        normalized_phone_number=PHONE,
    )

    assert result.allowed is True


@pytest.mark.asyncio
async def test_identity_mutation_cancels_queued_document_and_qr_ledgers(
    db_session: AsyncSession,
) -> None:
    context = await _seed_private_delivery_context(db_session)
    document = _document_delivery(context, status="queued")
    qr = _qr_delivery(context, status="queued")
    db_session.add_all([document, qr])
    await db_session.flush()

    mutation_started_at = datetime.now(tz=UTC)
    cancelled = await prepare_private_delivery_identity_mutation(
        db_session,
        agency_id=context["agency"].id,
        group_id=context["group"].id,
        cancel_queued=True,
        cancellation_reason="Recipient mapping changed",
    )
    await db_session.flush()

    assert cancelled == 2
    assert document.status == qr.status == "failed"
    assert document.error_message == qr.error_message == "Recipient mapping changed"
    assert document.status_updated_at >= mutation_started_at
    assert document.updated_at == document.status_updated_at
    assert qr.status_updated_at >= mutation_started_at
    assert qr.updated_at == qr.status_updated_at


@pytest.mark.asyncio
async def test_identity_mutation_blocks_processing_or_unknown_private_delivery(
    db_session: AsyncSession,
) -> None:
    context = await _seed_private_delivery_context(db_session)
    document = _document_delivery(context, status="processing")
    qr = _qr_delivery(context, status="queued")
    db_session.add_all([document, qr])
    await db_session.flush()

    with pytest.raises(PrivateDeliveryMutationBlocked):
        await prepare_private_delivery_identity_mutation(
            db_session,
            agency_id=context["agency"].id,
            group_id=context["group"].id,
            cancel_queued=True,
            cancellation_reason="Recipient mapping changed",
        )

    assert document.status == "processing"
    assert qr.status == "queued"


def _async_session_context(session: AsyncMock) -> MagicMock:
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    return context


@pytest.mark.asyncio
async def test_source_mutation_waits_until_provider_window_is_recorded() -> None:
    """A source identity writer cannot pass the final provider transaction."""

    delivery_id = uuid.uuid4()
    batch_id = uuid.uuid4()
    delivery = SimpleNamespace(
        id=delivery_id,
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        passenger_id=uuid.uuid4(),
        distributed_document_id=uuid.uuid4(),
        document_batch_id=uuid.uuid4(),
        broadcast_group_id=uuid.uuid4(),
        recipient_id=uuid.uuid4(),
        normalized_phone_number=PHONE,
        document_filename="visa.pdf",
        document_type="visa",
        passenger_name="Passenger",
        template_name="documents_v1",
        template_parameter_values=["Your VISA", "Check your details"],
        status="processing",
        error_message=None,
        provider_message_id=None,
        provider_media_id=None,
        status_updated_at=NOW,
        updated_at=NOW,
    )
    document = SimpleNamespace(storage_key="documents/visa.pdf", content_type="application/pdf")
    source_batch = SimpleNamespace(status="saved")
    group = SimpleNamespace(name="Trip")

    claim_result = MagicMock()
    claim_result.scalar_one_or_none.return_value = delivery_id
    claim_session = AsyncMock()
    claim_session.execute.return_value = claim_result

    initial_result = MagicMock()
    initial_result.one_or_none.return_value = (delivery, document, group)
    initial_session = AsyncMock()
    initial_session.execute.return_value = initial_result

    snapshot_result = MagicMock()
    snapshot_result.scalar_one_or_none.return_value = delivery
    source_result = MagicMock()
    source_result.one_or_none.return_value = (document, source_batch)
    locked_result = MagicMock()
    locked_result.scalar_one_or_none.return_value = delivery
    provider_session = AsyncMock()
    provider_session.execute.side_effect = [
        snapshot_result,
        source_result,
        locked_result,
    ]

    source_lock = asyncio.Lock()
    mutation_attempted = asyncio.Event()
    mutation_finished = asyncio.Event()
    mutation_task: asyncio.Task[None] | None = None

    async def final_validation(*_args: object, **_kwargs: object) -> PrivateDeliveryRecipientValidation:
        await source_lock.acquire()
        return PrivateDeliveryRecipientValidation(allowed=True)

    async def source_mutation() -> None:
        mutation_attempted.set()
        async with source_lock:
            mutation_finished.set()

    async def provider_send(**_kwargs: object) -> str:
        nonlocal mutation_task
        mutation_task = asyncio.create_task(source_mutation())
        await mutation_attempted.wait()
        await asyncio.sleep(0)
        assert mutation_finished.is_set() is False
        return "wamid.private-1"

    async def commit_provider_outcome() -> None:
        if source_lock.locked():
            source_lock.release()

    provider_session.commit.side_effect = commit_provider_outcome
    storage = SimpleNamespace(get_file=AsyncMock(return_value=b"pdf"))
    client_context = MagicMock()
    client_context.__aenter__ = AsyncMock(return_value=SimpleNamespace())
    client_context.__aexit__ = AsyncMock(return_value=False)
    session_contexts = [
        _async_session_context(claim_session),
        _async_session_context(initial_session),
        _async_session_context(provider_session),
    ]

    with (
        patch(
            "app.infrastructure.whatsapp.document_delivery_runtime.AsyncSessionFactory",
            side_effect=session_contexts,
        ),
        patch(
            "app.infrastructure.whatsapp.document_delivery_runtime.MinioStorageRepository",
            return_value=storage,
        ),
        patch(
            "app.infrastructure.whatsapp.document_delivery_runtime.httpx.AsyncClient",
            return_value=client_context,
        ),
        patch(
            "app.infrastructure.whatsapp.document_delivery_runtime.get_settings",
            return_value=SimpleNamespace(),
        ),
        patch(
            "app.infrastructure.whatsapp.document_delivery_runtime.upload_whatsapp_document",
            new=AsyncMock(return_value="media-1"),
        ),
        patch(
            "app.infrastructure.whatsapp.document_delivery_runtime.validate_private_delivery_recipient",
            side_effect=final_validation,
        ),
        patch(
            "app.infrastructure.whatsapp.document_delivery_runtime.send_whatsapp_document_template",
            side_effect=provider_send,
        ),
    ):
        await run_document_whatsapp_broadcast(
            send_batch_id=str(batch_id),
            _delivery_id=delivery_id,
        )

    assert mutation_task is not None
    await mutation_task
    assert mutation_finished.is_set() is True
    assert delivery.status == "submitted"
