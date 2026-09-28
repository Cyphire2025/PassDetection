"""Real PostgreSQL recipient fences and phone-level welcome claim races."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import URL, delete, func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.infrastructure.database.models import (
    AgencyModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
    WhatsAppPhoneWelcomeAttemptModel,
    WhatsAppPhoneWelcomeModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.whatsapp.phone_welcome import (
    assert_phone_welcome_claim,
    claim_phone_welcome,
)
from app.infrastructure.whatsapp.private_delivery_policy import (
    lock_private_delivery_group_source_snapshot,
    validate_private_delivery_recipient,
)
from tests.unit.infrastructure.test_private_delivery_policy import (
    PHONE,
    _seed_private_delivery_context,
)

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1",
        reason="requires the isolated migrated PostgreSQL service-integration database",
    ),
]


@pytest.fixture
async def traveller_pg_context():
    url = URL.create(
        "postgresql+asyncpg",
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        database=os.environ["POSTGRES_DB"],
    )
    engine = create_async_engine(url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        context = await _seed_private_delivery_context(session)
        context["passengers"][0].client_phone = PHONE
        await session.commit()
    try:
        yield factory, context
    finally:
        async with factory() as session:
            await session.execute(delete(PassportSubmissionModel).where(
                PassportSubmissionModel.agency_id == context["agency"].id,
            ))
            await session.execute(delete(AgencyModel).where(AgencyModel.id == context["agency"].id))
            await session.commit()
        await engine.dispose()


async def _wait_until_postgres_reports_blocked(factory, backend_pid: int) -> None:
    async with factory() as observer:
        for _ in range(100):
            if await observer.scalar(
                text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                {"pid": backend_pid},
            ):
                return
            await asyncio.sleep(0.02)
    raise AssertionError("The concurrent writer never waited on the authoritative source lock")


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["phone", "roster_exclusion"])
async def test_private_source_fence_blocks_recipient_mutation_until_send_window_closes(
    traveller_pg_context, mutation
):
    factory, context = traveller_pg_context
    passenger = context["passengers"][0]
    started = asyncio.Event()
    writer_pid = []

    async def mutate_source():
        async with factory() as writer:
            writer_pid.append(await writer.scalar(text("SELECT pg_backend_pid()")))
            started.set()
            if mutation == "phone":
                await writer.execute(update(PassportSubmissionModel).where(
                    PassportSubmissionModel.id == passenger.id,
                ).values(client_phone="+919876543211"))
            else:
                writer.add(PassportRosterResolutionModel(
                    agency_id=context["agency"].id,
                    client_group_id=context["group"].id,
                    submission_id=passenger.id,
                    resolution_type="rejected", status="active",
                ))
            await writer.commit()

    writer_task = None
    try:
        async with factory() as sending:
            snapshot = await lock_private_delivery_group_source_snapshot(
                sending, agency_id=context["agency"].id, group_id=context["group"].id,
            )
            assert snapshot and snapshot.allows(
                agency_id=context["agency"].id, group_id=context["group"].id,
                passenger_id=passenger.id, broadcast_group_id=None, recipient_id=None,
                normalized_phone_number=PHONE, delivery_source="submission",
            )
            writer_task = asyncio.create_task(mutate_source())
            await asyncio.wait_for(started.wait(), timeout=3)
            await _wait_until_postgres_reports_blocked(factory, writer_pid[0])
            assert not writer_task.done()
            # The worker keeps this transaction through its provider request.
            await sending.commit()
        await asyncio.wait_for(writer_task, timeout=3)
        async with factory() as next_send:
            validation = await validate_private_delivery_recipient(
                next_send, agency_id=context["agency"].id, group_id=context["group"].id,
                passenger_id=passenger.id, broadcast_group_id=None, recipient_id=None,
                normalized_phone_number=PHONE, delivery_source="submission",
            )
            assert not validation.allowed
    finally:
        if writer_task and not writer_task.done():
            writer_task.cancel()
            await asyncio.gather(writer_task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("previous_status", [None, "failed"])
async def test_simultaneous_traveller_and_broadcast_welcomes_claim_phone_once(
    traveller_pg_context, previous_status
):
    factory, context = traveller_pg_context
    agency_id = context["agency"].id
    phone = "+919876543299"
    if previous_status:
        async with factory() as session:
            session.add(WhatsAppPhoneWelcomeModel(
                agency_id=agency_id, normalized_phone_number=phone, status=previous_status,
                attempt_id=uuid.uuid4(), attempt_kind="traveller",
            ))
            await session.commit()
    started = asyncio.Event()
    contender_pid = []

    async def competing_broadcast():
        async with factory() as contender:
            contender_pid.append(await contender.scalar(text("SELECT pg_backend_pid()")))
            started.set()
            outcome = await claim_phone_welcome(
                contender, agency_id=agency_id, phone=phone,
                attempt_id=uuid.uuid4(), attempt_kind="broadcast",
            )
            await contender.commit()
            return outcome

    task = None
    try:
        async with factory() as first:
            assert await claim_phone_welcome(
                first, agency_id=agency_id, phone=phone,
                attempt_id=uuid.uuid4(), attempt_kind="traveller",
            ) == "claimed"
            task = asyncio.create_task(competing_broadcast())
            await asyncio.wait_for(started.wait(), timeout=3)
            await _wait_until_postgres_reports_blocked(factory, contender_pid[0])
            assert not task.done()
            await first.commit()
        assert await asyncio.wait_for(task, timeout=3) == "queued"
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(
                WhatsAppPhoneWelcomeModel,
            ).where(
                WhatsAppPhoneWelcomeModel.agency_id == agency_id,
                WhatsAppPhoneWelcomeModel.normalized_phone_number == phone,
            )) == 1
    finally:
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def _add_scoped_welcome_intent(session, context, *, kind, broadcast_id, recipient_id,
                               attempt_id, batch_id):
    fields = dict(id=attempt_id, batch_id=batch_id, agency_id=context["agency"].id,
                  broadcast_group_id=broadcast_id, normalized_phone_number=PHONE, status="queued")
    if kind == "broadcast":
        session.add(WhatsAppMessageLogModel(
            **fields, recipient_id=recipient_id, message_type="welcome",
        ))
        session.add(WhatsAppRecipientMessageStateModel(
            agency_id=context["agency"].id, broadcast_group_id=broadcast_id,
            recipient_id=recipient_id, message_type="welcome", status="queued", batch_id=batch_id,
        ))
    else:
        session.add(WhatsAppPhoneWelcomeAttemptModel(
            **fields, group_id=context["group"].id,
            passenger_ids=[str(context["passengers"][0].id)], template_name="reviewed_welcome",
            rendered_message="Welcome to this trip", header_parameter_values=[],
            template_parameter_values=["Welcome to this trip"],
        ))


@pytest.mark.parametrize("first_kind", ["broadcast", "traveller"])
@pytest.mark.parametrize("same_broadcast", [True, False])
async def test_concurrent_scoped_welcome_claims_preserve_broadcast_boundary(
    traveller_pg_context, first_kind, same_broadcast,
):
    factory, context = traveller_pg_context
    agency_id = context["agency"].id
    first_broadcast_id = context["broadcast"].id
    second_broadcast_id = first_broadcast_id
    second_recipient_id = context["recipient"].id
    if not same_broadcast:
        second_broadcast_id, second_recipient_id = uuid.uuid4(), uuid.uuid4()
        async with factory() as setup:
            setup.add(WhatsAppBroadcastGroupModel(
                id=second_broadcast_id, agency_id=agency_id, name="Another trip",
            ))
            await setup.flush()
            setup.add(WhatsAppBroadcastRecipientModel(
                id=second_recipient_id, agency_id=agency_id, broadcast_group_id=second_broadcast_id,
                name="Same traveller", phone_number=PHONE, normalized_phone_number=PHONE,
            ))
            await setup.commit()

    first_id, second_id, first_batch, second_batch = (uuid.uuid4() for _ in range(4))
    second_kind = "traveller" if first_kind == "broadcast" else "broadcast"
    started = asyncio.Event()
    contender_pid = []

    async def competing_claim():
        async with factory() as contender:
            contender_pid.append(await contender.scalar(text("SELECT pg_backend_pid()")))
            started.set()
            outcome = await claim_phone_welcome(
                contender, agency_id=agency_id, phone=PHONE, attempt_id=second_id,
                attempt_kind=second_kind, broadcast_group_id=second_broadcast_id,
                batch_id=second_batch,
            )
            if outcome == "claimed":
                _add_scoped_welcome_intent(
                    contender, context, kind=second_kind, broadcast_id=second_broadcast_id,
                    recipient_id=second_recipient_id, attempt_id=second_id, batch_id=second_batch,
                )
            await contender.commit()
            return outcome

    task = None
    try:
        async with factory() as first:
            # The fixture's global projection is already delivered. It must
            # neither suppress either new broadcast nor authorize duplicates.
            assert await claim_phone_welcome(
                first, agency_id=agency_id, phone=PHONE, attempt_id=first_id,
                attempt_kind=first_kind, broadcast_group_id=first_broadcast_id,
                batch_id=first_batch,
            ) == "claimed"
            task = asyncio.create_task(competing_claim())
            await asyncio.wait_for(started.wait(), timeout=3)
            await _wait_until_postgres_reports_blocked(factory, contender_pid[0])
            if same_broadcast:
                async with factory() as observer:
                    blocked_query = await observer.scalar(text(
                        "SELECT query FROM pg_stat_activity WHERE pid = :pid"
                    ), {"pid": contender_pid[0]})
                    assert "whatsapp_broadcast_groups" in blocked_query
            assert not task.done()
            # Persist the authoritative intent while the broadcast lock is
            # still held, exactly as each producer does before queue publish.
            _add_scoped_welcome_intent(
                first, context, kind=first_kind, broadcast_id=first_broadcast_id,
                recipient_id=context["recipient"].id, attempt_id=first_id, batch_id=first_batch,
            )
            await first.commit()
        assert await asyncio.wait_for(task, timeout=3) == (
            "queued" if same_broadcast else "claimed"
        )
        async with factory() as verification:
            durable_intents = sum([
                await verification.scalar(select(func.count()).select_from(model).where(
                    model.agency_id == agency_id,
                )) for model in (WhatsAppMessageLogModel, WhatsAppPhoneWelcomeAttemptModel)
            ])
            assert durable_intents == (1 if same_broadcast else 2)
            assert await assert_phone_welcome_claim(
                verification, agency_id=agency_id, phone=PHONE, attempt_id=first_id,
                broadcast_group_id=first_broadcast_id,
            )
            if not same_broadcast:
                assert await assert_phone_welcome_claim(
                    verification, agency_id=agency_id, phone=PHONE, attempt_id=second_id,
                    broadcast_group_id=second_broadcast_id,
                )
            assert await verification.scalar(select(WhatsAppPhoneWelcomeModel.status).where(
                WhatsAppPhoneWelcomeModel.agency_id == agency_id,
                WhatsAppPhoneWelcomeModel.normalized_phone_number == PHONE,
            )) == "delivered"
    finally:
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
