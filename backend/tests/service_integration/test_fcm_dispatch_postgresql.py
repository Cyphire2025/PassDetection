"""Direct FCM durability proof in an explicitly named, isolated PostgreSQL DB.

Requires RUN_SERVICE_INTEGRATION=1 and FCM_TEST_POSTGRES_DB beginning with
passdetection_ci_ or passdetection_fcm_test_. Normal POSTGRES_HOST/PORT/USER/
PASSWORD select the server; the application POSTGRES_DB is deliberately ignored.
Set FCM_TEST_KEEP_SCHEMA=1 to retain each newly created UUID schema. Nothing in
the application database is read or changed. Providers below are in-memory fakes.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import URL, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.mobile.notification_service import (
    cancel_announcement_notifications,
    dispatch_mobile_push_batch,
)
from app.application.mobile.push_provider import MobilePushTicket
from app.core.security.mobile_push_crypto import mobile_push_fernet
from app.infrastructure.database.gc_mobile_models import (
    GCAnnouncementModel,
    GCGroupAccessModel,
    MobileNotificationModel,
    MobilePushDeliveryModel,
    MobilePushRegistrationModel,
)
from app.infrastructure.database.models import Base
from tests.service_integration.test_announcement_push_guard_postgresql import (
    push_target as push_target,
)

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1",
        reason="explicit isolated PostgreSQL acceptance environment required",
    ),
]


@pytest.fixture
async def pg_factory():
    database = os.environ.get("FCM_TEST_POSTGRES_DB", "")
    if not database.startswith(("passdetection_ci_", "passdetection_fcm_test_")):
        pytest.fail(
            "FCM_TEST_POSTGRES_DB must explicitly name a passdetection_ci_ or passdetection_fcm_test_ database"
        )
    if database == os.environ.get("POSTGRES_DB"):
        pytest.fail("The explicitly named test database must differ from application POSTGRES_DB")
    url = URL.create(
        "postgresql+asyncpg",
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host=os.environ["POSTGRES_HOST"],
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        database=database,
    )
    schema = f"fcm_dispatch_test_{uuid.uuid4().hex}"
    admin = create_async_engine(url, poolclass=NullPool, echo=False)
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        echo=False,
        connect_args={
            "server_settings": {
                "search_path": schema,
                "lock_timeout": "5000",
                "statement_timeout": "15000",
            }
        },
    )
    created = False
    try:
        async with admin.begin() as connection:
            assert await connection.scalar(text("SELECT current_database()")) == database
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        async with engine.begin() as connection:
            assert await connection.scalar(text("SELECT current_schema()")) == schema
            await connection.run_sync(Base.metadata.create_all)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        if created:
            if os.getenv("FCM_TEST_KEEP_SCHEMA") == "1":
                print(f"FCM_TEST_SCHEMA_RETAINED={schema}")
            else:
                # This exact UUID schema was created by this fixture in the
                # separately named test database. Never touch public/app data.
                async with admin.begin() as connection:
                    await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


@pytest.fixture
async def fcm_target(pg_factory, push_target):
    now, access_id, source_id, notification_id = push_target
    async with pg_factory() as session:
        registration = await session.scalar(select(MobilePushRegistrationModel))
        registration.provider = "fcm"
        registration.app_bundle_id = "com.globalconnects.groupcompanion"
        registration.token_ciphertext = mobile_push_fernet().encrypt(b"synthetic-native-fcm-token")
        notification = await session.get(MobileNotificationModel, notification_id)
        notification.notification_type = "personal_document_changed"
        await session.commit()
        registration_id = registration.id
    return now, access_id, source_id, notification_id, registration_id


class FakeFcmProvider:
    name = "fcm"
    enabled = True
    supports_receipts = False

    def __init__(self, on_send=None):
        self.on_send = on_send
        self.calls = 0
        self.prepared = False

    async def prepare(self):
        self.prepared = True

    async def send(self, messages):
        assert self.prepared
        self.calls += 1
        if self.on_send is not None:
            await self.on_send(messages)
        return [
            MobilePushTicket(
                registration_id=message.registration_id,
                notification_id=message.notification_id,
                accepted=True,
                retryable=False,
                requires_receipt=False,
                provider_ticket_id=f"projects/group-companion-c2c30/messages/{message.notification_id}",
            )
            for message in messages
        ]

    async def get_receipts(self, ids):
        raise AssertionError("FCM has no receipt endpoint; tests must never poll one")


async def test_intent_is_committed_and_visible_to_an_independent_session_before_http(
    pg_factory,
    fcm_target,
):
    now, _, _, notification_id, _ = fcm_target
    observed = []

    async def verify_committed_intent(messages):
        async with pg_factory() as observer:
            row = await observer.scalar(
                select(MobilePushDeliveryModel).where(
                    MobilePushDeliveryModel.notification_id == notification_id,
                )
            )
            assert row is not None and row.status == "submitting"
            assert row.provider_ticket_id is None and row.delivered_at is None
            assert row.send_attempts == 1
            observed.append(row.id)
        assert len(messages) == 1

    provider = FakeFcmProvider(verify_committed_intent)
    async with pg_factory() as session:
        assert await dispatch_mobile_push_batch(session, provider=provider, limit=20, now=now) == 1
        await session.commit()
    async with pg_factory() as session:
        row = await session.get(MobilePushDeliveryModel, observed[0])
        assert row.status == "provider_accepted" and row.submitted_at is not None
        assert row.delivered_at is None
        assert (await session.get(MobileNotificationModel, notification_id)).status == "sent"
    assert provider.calls == 1


async def test_crash_after_possible_send_preserves_intent_and_recovers_unknown_without_retry(
    pg_factory,
    fcm_target,
):
    now, _, _, notification_id, _ = fcm_target

    async def crash_after_possible_send(messages):
        assert len(messages) == 1
        raise RuntimeError("synthetic worker interruption after possible provider acceptance")

    interrupted = FakeFcmProvider(crash_after_possible_send)
    async with pg_factory() as session:
        with pytest.raises(RuntimeError, match="synthetic worker interruption"):
            await dispatch_mobile_push_batch(session, provider=interrupted, limit=20, now=now)
        await session.rollback()
    async with pg_factory() as session:
        row = await session.scalar(select(MobilePushDeliveryModel))
        assert row.status == "submitting" and row.send_attempts == 1
        assert row.provider_ticket_id is None and row.delivered_at is None

    later = FakeFcmProvider()
    async with pg_factory() as session:
        assert (
            await dispatch_mobile_push_batch(
                session,
                provider=later,
                limit=20,
                now=now + timedelta(minutes=16),
            )
            == 0
        )
        await session.commit()
    async with pg_factory() as session:
        row = await session.scalar(select(MobilePushDeliveryModel))
        notification = await session.get(MobileNotificationModel, notification_id)
        assert row.status == "unknown" and row.send_attempts == 1
        assert row.last_error_code == "provider_outcome_unknown"
        assert row.provider_ticket_id is None and row.delivered_at is None
        assert notification.failure_code == "provider_outcome_unknown"
        assert (
            await dispatch_mobile_push_batch(
                session,
                provider=later,
                limit=20,
                now=now + timedelta(hours=1),
            )
            == 0
        )
    assert interrupted.calls == 1 and later.calls == 0


async def test_access_revocation_in_the_intent_commit_gap_prevents_provider_send(
    pg_factory,
    fcm_target,
    monkeypatch,
):
    now, access_id, source_id, notification_id, _ = fcm_target
    provider = FakeFcmProvider()
    async with pg_factory() as session:
        original_commit = session.commit
        injected = False

        async def commit_then_withdraw():
            nonlocal injected
            await original_commit()
            if injected:
                return
            injected = True
            async with pg_factory() as withdrawal:
                access = await withdrawal.scalar(
                    select(GCGroupAccessModel)
                    .where(
                        GCGroupAccessModel.id == access_id,
                    )
                    .with_for_update()
                )
                source = await withdrawal.scalar(
                    select(GCAnnouncementModel)
                    .where(
                        GCAnnouncementModel.id == source_id,
                    )
                    .with_for_update()
                )
                source.status = "retired"
                source.retired_at = now
                access.is_enabled = False
                await withdrawal.flush()
                await cancel_announcement_notifications(
                    withdrawal,
                    access=access,
                    announcement_id=source_id,
                    now=now,
                )
                await withdrawal.commit()

        monkeypatch.setattr(session, "commit", commit_then_withdraw)
        assert await dispatch_mobile_push_batch(session, provider=provider, limit=20, now=now) == 0
        await original_commit()
    async with pg_factory() as session:
        notification = await session.get(MobileNotificationModel, notification_id)
        delivery = await session.scalar(select(MobilePushDeliveryModel))
        assert notification.status == "cancelled"
        assert delivery.status == "cancelled" and delivery.provider_ticket_id is None
    assert injected and provider.calls == 0


async def test_competing_worker_and_stale_recovery_skip_a_live_sender(pg_factory, fcm_target):
    now, _, _, _, _ = fcm_target
    entered, release = asyncio.Event(), asyncio.Event()

    async def pause_send(messages):
        assert len(messages) == 1
        entered.set()
        await release.wait()

    first_provider, competitor = FakeFcmProvider(pause_send), FakeFcmProvider()

    async def first_worker():
        async with pg_factory() as session:
            result = await dispatch_mobile_push_batch(
                session, provider=first_provider, limit=20, now=now
            )
            await session.commit()
            return result

    operation = asyncio.create_task(first_worker())
    try:
        await asyncio.wait_for(entered.wait(), timeout=10)
        async with pg_factory() as session:
            await session.connection()
            # Advancing this worker's clock also makes the first intent a
            # recovery candidate. Its live parent lock must fence both paths.
            assert (
                await asyncio.wait_for(
                    dispatch_mobile_push_batch(
                        session,
                        provider=competitor,
                        limit=20,
                        now=now + timedelta(minutes=16),
                    ),
                    timeout=3,
                )
                == 0
            )
            await session.commit()
        async with pg_factory() as observer:
            row = await observer.scalar(select(MobilePushDeliveryModel))
            assert row.status == "submitting" and row.send_attempts == 1
        assert competitor.calls == 0
        release.set()
        assert await asyncio.wait_for(operation, timeout=10) == 1
    finally:
        release.set()
        if not operation.done():
            operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)
    async with pg_factory() as session:
        row = await session.scalar(select(MobilePushDeliveryModel))
        assert row.status == "provider_accepted" and row.send_attempts == 1
        assert (
            await dispatch_mobile_push_batch(session, provider=competitor, limit=20, now=now) == 0
        )
    assert first_provider.calls == 1 and competitor.calls == 0


def _load_migration():
    path = (
        Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0095_mobile_fcm_delivery.py"
    )
    spec = importlib.util.spec_from_file_location("isolated_fcm_0095_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _migration(session, module, direction):
    connection = await session.connection()

    def apply(sync_connection):
        module.op = Operations(MigrationContext.configure(sync_connection))
        getattr(module, direction)()

    await connection.run_sync(apply)


async def _delivery_row(session, original, registration_id, state, now):
    notification = MobileNotificationModel(
        id=uuid.uuid4(),
        agency_id=original.agency_id,
        group_id=original.group_id,
        gc_group_access_id=original.gc_group_access_id,
        recipient_type=original.recipient_type,
        recipient_user_id=original.recipient_user_id,
        notification_type="synthetic_schema_proof",
        category="announcement",
        priority="normal",
        title="Synthetic",
        body="Synthetic",
        dedupe_key=f"synthetic-schema:{uuid.uuid4()}",
        public_payload={},
        status="queued",
        available_at=now,
    )
    session.add(notification)
    await session.flush()
    receipt_state = state in {"receipt_pending", "delivered", "provider_accepted"}
    delivery = MobilePushDeliveryModel(
        id=uuid.uuid4(),
        agency_id=original.agency_id,
        notification_id=notification.id,
        registration_id=registration_id,
        provider="fcm" if state in {"provider_accepted", "unknown"} else "expo",
        status=state,
        send_attempts=1,
        receipt_attempts=0,
        next_attempt_at=now,
        provider_ticket_id=f"synthetic-ticket-{notification.id}" if receipt_state else None,
        submitted_at=now if receipt_state else None,
        delivered_at=now if state == "delivered" else None,
        failed_at=now if state == "failed" else None,
    )
    session.add(delivery)
    await session.flush()
    return delivery


async def test_0095_preserves_every_legacy_status_and_adds_honest_fcm_states(
    pg_factory, fcm_target
):
    now, _, _, notification_id, registration_id = fcm_target
    migration = _load_migration()
    assert migration.down_revision == "0094_whatsapp_receipt_inbox"
    async with pg_factory() as session:
        # The isolated fixture starts with today's metadata. Restore only this
        # new empty test table's 0094 CHECKs before exercising the actual upgrade.
        await _migration(session, migration, "downgrade")
        original = await session.get(MobileNotificationModel, notification_id)
        legacy = [
            await _delivery_row(session, original, registration_id, state, now)
            for state in (
                "submitting",
                "retry",
                "receipt_pending",
                "delivered",
                "failed",
                "cancelled",
            )
        ]
        before = {row.id: (row.status, row.provider_ticket_id, row.delivered_at) for row in legacy}
        await session.commit()
        await _migration(session, migration, "upgrade")
        await session.commit()
        actual = list(
            await session.scalars(
                select(MobilePushDeliveryModel)
                .where(
                    MobilePushDeliveryModel.id.in_(before),
                )
                .execution_options(populate_existing=True)
            )
        )
        assert {
            row.id: (row.status, row.provider_ticket_id, row.delivered_at) for row in actual
        } == before
        accepted = await _delivery_row(session, original, registration_id, "provider_accepted", now)
        unknown = await _delivery_row(session, original, registration_id, "unknown", now)
        assert accepted.delivered_at is None and accepted.provider_ticket_id is not None
        assert unknown.delivered_at is None and unknown.provider_ticket_id is None
        await session.commit()
        with pytest.raises(IntegrityError) as invalid_receipt:
            async with session.begin_nested():
                accepted.provider_ticket_id = None
                accepted.submitted_at = None
                await session.flush()
        assert "ck_mobile_push_delivery_receipt_shape" in str(invalid_receipt.value.orig)
        with pytest.raises(RuntimeError, match="downgrade refused"):
            await _migration(session, migration, "downgrade")
        await session.rollback()
