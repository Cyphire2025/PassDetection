"""Real PostgreSQL transaction/locking proof in disposable, per-test schemas."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import URL, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.infrastructure.database.models import (
    Base,
    WhatsAppProviderMessageBindingModel,
    WhatsAppProviderReceiptModel,
)
from app.infrastructure.whatsapp import receipt_runtime, traveller_welcome_runtime
from app.infrastructure.whatsapp.phone_welcome import require_welcome_delivered
from app.infrastructure.whatsapp.receipt_bindings import bind_source_provider_message
from app.infrastructure.whatsapp.receipt_inbox import persist_verified_receipts
from app.infrastructure.whatsapp.receipt_runtime import (
    reconcile_pending_receipts,
    reconcile_receipt,
)
from tests.unit.infrastructure.test_phone_welcome import PHONE, _attempt
from tests.unit.infrastructure.test_whatsapp_receipt_inbox import (
    ACCOUNT,
    event,
    seed_source,
    signed_webhook,
)

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1",
        reason="requires isolated PostgreSQL test service",
    ),
]


def pg_url():
    return URL.create(
        "postgresql+asyncpg",
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        database=os.environ["POSTGRES_DB"],
    )


@pytest.fixture
async def pg_factory():
    schema = f"receipt_test_{uuid.uuid4().hex}"
    admin = create_async_engine(pg_url(), poolclass=NullPool)
    engine = create_async_engine(
        pg_url(),
        poolclass=NullPool,
        connect_args={
            "server_settings": {
                "search_path": schema,
                "lock_timeout": "5000",
                "statement_timeout": "15000",
            }
        },
    )
    try:
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


async def test_actual_worker_early_webhook_recovers_without_second_send(pg_factory, monkeypatch):
    async with pg_factory() as session:
        attempt, _ = await _attempt(session)
        batch_id, agency_id, attempt_id = attempt.batch_id, attempt.agency_id, attempt.id
    monkeypatch.setattr(traveller_welcome_runtime, "AsyncSessionFactory", pg_factory)
    monkeypatch.setattr(
        traveller_welcome_runtime,
        "get_settings",
        lambda: SimpleNamespace(whatsapp_phone_number_id=ACCOUNT),
    )

    async def send_with_early_receipt(**kwargs):
        async with pg_factory() as webhook_session:
            response = await signed_webhook(
                webhook_session, monkeypatch, [event(timestamp=datetime.now(UTC))]
            )
            assert response.processed_statuses == 0
        return "wamid.test"

    send = AsyncMock(side_effect=send_with_early_receipt)
    monkeypatch.setattr(traveller_welcome_runtime, "send_whatsapp_template", send)
    await asyncio.wait_for(
        traveller_welcome_runtime.run_traveller_welcome_broadcast(batch_id=str(batch_id)),
        timeout=20,
    )
    async with pg_factory() as session:
        assert (
            await reconcile_pending_receipts(session, now=datetime.now(UTC) + timedelta(minutes=2))
        ) == {"applied": 1}
        assert await require_welcome_delivered(session, agency_id=agency_id, phone=PHONE)
        binding = await session.scalar(select(WhatsAppProviderMessageBindingModel))
        assert binding.source_id == attempt_id and binding.provider_phone_number_id == ACCOUNT
    await traveller_welcome_runtime.run_traveller_welcome_broadcast(batch_id=str(batch_id))
    send.assert_awaited_once()


async def test_concurrent_duplicate_insert_and_replay_apply_once(pg_factory, monkeypatch):
    async with pg_factory() as session:
        source = await seed_source(session, "otp")
        source.provider_reference = "wamid.test"
        await bind_source_provider_message(session, source, provider_phone_number_id=ACCOUNT)
        await session.commit()
    receipt = event(status="failed", timestamp=datetime.now(UTC))

    async def insert_duplicate():
        async with pg_factory() as session:
            ids = await persist_verified_receipts(session, [receipt, receipt])
            await session.commit()
            return ids[0]

    ids = await asyncio.wait_for(
        asyncio.gather(*(insert_duplicate() for _ in range(4))), timeout=20
    )
    assert len(set(ids)) == 1
    entered, release = asyncio.Event(), asyncio.Event()
    original = receipt_runtime._apply_to_source

    async def paused_apply(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(receipt_runtime, "_apply_to_source", paused_apply)

    async def apply():
        async with pg_factory() as session:
            return await reconcile_receipt(session, ids[0])

    first = asyncio.create_task(apply())
    await asyncio.wait_for(entered.wait(), timeout=10)
    assert await asyncio.wait_for(apply(), timeout=5) == "skipped"
    release.set()
    assert await asyncio.wait_for(first, timeout=10) == "applied"
    async with pg_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(WhatsAppProviderReceiptModel))
            == 1
        )
        assert (
            await session.scalar(
                text("SELECT count(*) FROM audit_logs WHERE action='mobile.otp_delivery_status'")
            )
            == 1
        )


async def test_receipt_rollback_replays_atomically(pg_factory, monkeypatch):
    async with pg_factory() as session:
        source = await seed_source(session, "document")
        source_id = source.id
        source.provider_message_id = "wamid.test"
        await bind_source_provider_message(session, source, provider_phone_number_id=ACCOUNT)
        ids = await persist_verified_receipts(session, [event(timestamp=datetime.now(UTC))])
        await session.commit()
    original = receipt_runtime._apply_to_source

    async def crash_after_source_mutation(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("simulated crash before transaction commit")

    monkeypatch.setattr(receipt_runtime, "_apply_to_source", crash_after_source_mutation)
    async with pg_factory() as session:
        assert await reconcile_pending_receipts(session, receipt_ids=ids) == {"retry": 1}
    async with pg_factory() as session:
        assert (
            await session.scalar(
                text("SELECT status FROM document_whatsapp_deliveries WHERE id=:id"),
                {"id": source_id},
            )
            == "processing"
        )
        assert await session.scalar(select(WhatsAppProviderReceiptModel.state)) == "pending"
    monkeypatch.setattr(receipt_runtime, "_apply_to_source", original)
    async with pg_factory() as session:
        assert await reconcile_pending_receipts(
            session, now=datetime.now(UTC) + timedelta(minutes=2)
        ) == {"applied": 1}


async def test_additive_receipt_migration_upgrade_and_downgrade():
    engine = create_async_engine(pg_url(), poolclass=NullPool)
    schema = f"receipt_migration_{uuid.uuid4().hex}"
    path = Path(__file__).resolve().parents[2] / "alembic/versions/0094_whatsapp_receipt_inbox.py"
    spec = importlib.util.spec_from_file_location("whatsapp_receipt_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            await connection.execute(text("CREATE TABLE agencies (id uuid PRIMARY KEY)"))
            await connection.execute(
                text(
                    "CREATE TABLE whatsapp_message_logs (id uuid PRIMARY KEY, provider_message_id varchar(255))"
                )
            )
            await connection.execute(
                text(
                    "CREATE TABLE mobile_otp_challenges (id uuid PRIMARY KEY, provider_reference varchar(255))"
                )
            )

            async def apply(direction):
                def run(sync):
                    migration.op = Operations(MigrationContext.configure(sync))
                    getattr(migration, direction)()

                await connection.run_sync(run)

            await apply("upgrade")
            assert (
                await connection.scalar(text("SELECT to_regclass('whatsapp_provider_receipts')"))
                is not None
            )
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM whatsapp_provider_message_bindings")
                )
                == 0
            )
            await apply("downgrade")
            assert (
                await connection.scalar(text("SELECT to_regclass('whatsapp_provider_receipts')"))
                is None
            )
            assert (
                await connection.scalar(text("SELECT to_regclass('whatsapp_message_logs')"))
                is not None
            )
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
