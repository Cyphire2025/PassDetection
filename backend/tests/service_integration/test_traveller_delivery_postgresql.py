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
    WhatsAppPhoneWelcomeModel,
)
from app.infrastructure.whatsapp.phone_welcome import claim_phone_welcome
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
