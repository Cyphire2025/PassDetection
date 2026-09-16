"""Saved-message removal ordering against real PostgreSQL row locks and DDL."""

import asyncio
import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import func, select, text

from app.application.mobile.authored_notification_service import (
    delete_notification_draft,
    save_notification_draft,
    send_notification,
)
from app.infrastructure.database.gc_mobile_models import MobileNotificationModel
from app.infrastructure.database.gc_notification_models import (
    GCNotificationBatchModel,
    GCNotificationDraftModel,
)
from app.presentation.api.v1.routes.gc_notifications import get_batch_by_request
from app.presentation.api.v1.schemas.gc_notification_schemas import NotificationDraftUpdate
from tests.authored_notification_fixtures import authored_audience, reviewed_draft
from tests.service_integration.test_fcm_dispatch_postgresql import pg_factory as pg_factory
from tests.unit.application.test_saved_notification_deletion import (
    test_delete_retains_history_outbox_grants_and_committed_request_recovery as test_delete_retains_history_outbox_grants_and_committed_request_recovery,
)
from tests.unit.application.test_saved_notification_deletion import (
    test_delete_stale_revision_preserves_saved_content as test_delete_stale_revision_preserves_saved_content,
)
from tests.unit.application.test_saved_notification_deletion import (
    test_saved_removal_does_not_cancel_an_already_queued_send as test_saved_removal_does_not_cancel_an_already_queued_send,
)

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="explicit isolated PostgreSQL required"
    ),
]


@pytest.fixture
async def db_session(pg_factory):
    async with pg_factory() as session:
        yield session


@pytest.mark.parametrize(
    ("first", "second", "result"),
    [
        ("delete", "send", "missing"),
        ("delete", "edit", "missing"),
        ("edit", "delete", "draft_conflict"),
        ("send", "delete", "ok"),
    ],
)
async def test_delete_edit_send_serialize_on_saved_record(pg_factory, first, second, result):
    async with pg_factory() as session:
        actor, _, _, _, _ = await authored_audience(session, device=False)
        draft, _, request = await reviewed_draft(session, actor)
        scope = {"agency_id": actor.agency_id, "actor_id": actor.id, "draft_id": draft.id}
        await session.commit()

    async def operation(session, action):
        if action == "send":
            await send_notification(session, **scope, body=request)
        elif action == "delete":
            await delete_notification_draft(session, **scope, expected_revision=1)
        else:
            await save_notification_draft(
                session,
                **scope,
                body=NotificationDraftUpdate(
                    title="Edited", body="Revised", audience="all_active_trips", expected_revision=1
                ),
            )

    ready = asyncio.Event()
    waiting_pid = None

    async def blocked_operation():
        nonlocal waiting_pid
        async with pg_factory() as session:
            try:
                async with session.begin():
                    waiting_pid = await session.scalar(text("SELECT pg_backend_pid()"))
                    ready.set()
                    await operation(session, second)
                return "ok"
            except HTTPException as error:
                return "missing" if error.status_code == 404 else error.detail

    async with pg_factory() as holder:
        async with holder.begin():
            holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
            await operation(holder, first)
            contender = asyncio.create_task(blocked_operation())
            try:
                await asyncio.wait_for(ready.wait(), timeout=5)

                # Verify actual server-side contention, not a timing-dependent gather order.
                async def wait_for_lock():
                    while not await holder.scalar(
                        text("SELECT :holder = ANY(pg_blocking_pids(:waiting))"),
                        {"holder": holder_pid, "waiting": waiting_pid},
                    ):
                        await asyncio.sleep(0.01)

                await asyncio.wait_for(wait_for_lock(), timeout=5)
                assert not contender.done()
            except BaseException:
                contender.cancel()
                await asyncio.gather(contender, return_exceptions=True)
                raise
        assert await asyncio.wait_for(contender, timeout=10) == result

    async with pg_factory() as session:
        saved = await session.get(GCNotificationDraftModel, scope["draft_id"])
        assert (saved.deleted_at is not None) == (first != "edit")
        assert saved.revision == 2
        expected_sends = 1 if first == "send" else 0
        assert (
            await session.scalar(select(func.count()).select_from(GCNotificationBatchModel))
            == expected_sends
        )
        assert (
            await session.scalar(select(func.count()).select_from(MobileNotificationModel))
            == expected_sends * 2
        )


@pytest.mark.parametrize("send_before_delete", [False, True])
async def test_pending_recovery_waits_for_delete_and_recovers_concurrent_committed_send(
    pg_factory, send_before_delete
):
    async with pg_factory() as session:
        actor, _, _, _, _ = await authored_audience(session, device=False)
        draft, _, request = await reviewed_draft(session, actor)
        scope = {"agency_id": actor.agency_id, "actor_id": actor.id, "draft_id": draft.id}
        await session.commit()
    ready = asyncio.Event()
    waiting_pid = None

    async def recover():
        nonlocal waiting_pid
        async with pg_factory() as session:
            try:
                async with session.begin():
                    waiting_pid = await session.scalar(text("SELECT pg_backend_pid()"))
                    ready.set()
                    batch = await get_batch_by_request(
                        request_id=request.request_id,
                        agency_id=actor.agency_id,
                        draft_id=scope["draft_id"],
                        current_user=actor,
                        session=session,
                    )
                    return batch.id
            except HTTPException as error:
                return (error.status_code, error.detail)

    async with pg_factory() as holder:
        async with holder.begin():
            holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
            batch_id = None
            if send_before_delete:
                batch_id = (await send_notification(holder, **scope, body=request)).id
            await delete_notification_draft(holder, **scope, expected_revision=1)
            recovery = asyncio.create_task(recover())
            try:
                await asyncio.wait_for(ready.wait(), timeout=5)

                async def wait_for_lock():
                    while not await holder.scalar(
                        text("SELECT :holder = ANY(pg_blocking_pids(:waiting))"),
                        {"holder": holder_pid, "waiting": waiting_pid},
                    ):
                        await asyncio.sleep(0.01)

                await asyncio.wait_for(wait_for_lock(), timeout=5)
                assert not recovery.done()
            except BaseException:
                recovery.cancel()
                await asyncio.gather(recovery, return_exceptions=True)
                raise
        recovered = await asyncio.wait_for(recovery, timeout=10)
        assert recovered == (
            batch_id if send_before_delete else (410, "notification_deleted_without_send")
        )
    async with pg_factory() as session:
        assert await session.scalar(
            select(func.count()).select_from(GCNotificationBatchModel)
        ) == int(send_before_delete)
        assert (
            await session.get(GCNotificationDraftModel, scope["draft_id"])
        ).deleted_at is not None


async def test_additive_0098_retains_existing_saved_and_history_rows(pg_factory):
    schema = f"saved_migration_test_{uuid.uuid4().hex}"
    async with pg_factory() as session:
        await session.execute(text(f'CREATE SCHEMA "{schema}"'))
        await session.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        await session.execute(text("CREATE TABLE users (id uuid PRIMARY KEY)"))
        await session.execute(
            text(
                "CREATE TABLE gc_notification_drafts (id uuid PRIMARY KEY, agency_id uuid, created_at timestamptz, title varchar(100))"
            )
        )
        await session.execute(
            text(
                "CREATE TABLE gc_notification_batches (id uuid PRIMARY KEY, draft_id uuid REFERENCES gc_notification_drafts(id), title varchar(100))"
            )
        )
        saved_id, batch_id, agency_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO gc_notification_drafts VALUES (:id, :agency, CURRENT_TIMESTAMP, 'Existing saved message')"
            ),
            {"id": saved_id, "agency": agency_id},
        )
        await session.execute(
            text(
                "INSERT INTO gc_notification_batches VALUES (:id, :draft, 'Historical exact text')"
            ),
            {"id": batch_id, "draft": saved_id},
        )
        path = (
            Path(__file__).resolve().parents[2]
            / "alembic/versions/0098_notification_saved_delete.py"
        )
        spec = importlib.util.spec_from_file_location("saved_notification_0098_test", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        connection = await session.connection()

        def apply(sync_connection):
            with Operations.context(MigrationContext.configure(sync_connection)):
                migration.upgrade()

        await connection.run_sync(apply)
        row = (
            await session.execute(
                text("SELECT id, title, deleted_at, deleted_by_user_id FROM gc_notification_drafts")
            )
        ).one()
        assert tuple(row) == (saved_id, "Existing saved message", None, None)
        assert (
            await session.execute(text("SELECT id, draft_id, title FROM gc_notification_batches"))
        ).one() == (batch_id, saved_id, "Historical exact text")
        index = await session.scalar(
            text(
                "SELECT indexdef FROM pg_indexes WHERE schemaname=:schema AND indexname='ix_gc_notification_saved_page'"
            ),
            {"schema": schema},
        )
        assert "deleted_at IS NULL" in index
        await session.commit()
        print(f"SAVED_NOTIFICATION_MIGRATION_SCHEMA_RETAINED={schema}")
