"""GC App removal uses real row locks and additive, preserving PostgreSQL DDL."""

import asyncio
import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import select, text

from app.infrastructure.database.gc_mobile_models import GCGroupAccessModel
from app.infrastructure.database.models import ClientGroupModel
from tests.service_integration.test_fcm_dispatch_postgresql import pg_factory as pg_factory
from tests.unit.presentation.test_gc_app_closed_collection_groups import _configure
from tests.unit.presentation.test_gc_app_group_removal import configured_group, remove
from tests.unit.presentation.test_gc_app_group_removal import (
    test_deliberate_readd_preserves_history_and_rejects_old_delete_or_ordinary_edit as test_deliberate_readd_preserves_history_and_rejects_old_delete_or_ordinary_edit,
)
from tests.unit.presentation.test_gc_app_group_removal import (
    test_failed_commit_does_not_acknowledge_or_partially_remove as test_failed_commit_does_not_acknowledge_or_partially_remove,
)
from tests.unit.presentation.test_gc_app_group_removal import (
    test_readd_rejects_unavailable_original_group as test_readd_rejects_unavailable_original_group,
)

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"),
]


@pytest.fixture
async def db_session(pg_factory):
    async with pg_factory() as session:
        yield session


@pytest.mark.parametrize("first,second", [("remove", "remove"), ("edit", "remove"), ("remove", "edit"), ("restore", "remove")])
async def test_delete_edit_restore_serialize_even_with_cached_old_access(pg_factory, first, second):
    async with pg_factory() as session:
        actor, organization, group, initial = await configured_group(session)
        group_id, organization_id = group.id, organization.id
        if first == "restore":
            await remove(session, actor, group_id, initial.revision)
        revision = (await session.scalar(select(GCGroupAccessModel))).revision

    ready = asyncio.Event()
    cached = asyncio.Event()
    waiting_pid = None

    async def operation(session, action):
        if action == "remove":
            return await remove(session, actor, group_id, revision)
        from types import SimpleNamespace
        return await _configure(
            session, actor, SimpleNamespace(id=organization_id), SimpleNamespace(id=group_id),
            expected_revision=revision, restore_removed=action == "restore",
        )

    async def blocked_operation():
        nonlocal waiting_pid
        async with pg_factory() as contender:
            # Retain stale ORM objects explicitly; the row lock must refresh
            # them after the winning transaction changes revision/state.
            old_group = await contender.get(ClientGroupModel, group_id)
            old_access = await contender.scalar(select(GCGroupAccessModel))
            assert old_group is not None and old_access.revision == revision
            cached.set()
            await ready.wait()
            waiting_pid = await contender.scalar(text("SELECT pg_backend_pid()"))
            try:
                await operation(contender, second)
                await contender.commit()
                return 204
            except HTTPException as error:
                await contender.rollback()
                return error.status_code

    contender_task = asyncio.create_task(blocked_operation())
    try:
        await asyncio.wait_for(cached.wait(), timeout=5)
        async with pg_factory() as holder:
            holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
            await holder.execute(select(ClientGroupModel).where(ClientGroupModel.id == group_id).with_for_update())
            ready.set()

            async def verify_blocked():
                while waiting_pid is None or not await holder.scalar(
                    text("SELECT :holder = ANY(pg_blocking_pids(:waiting))"),
                    {"holder": holder_pid, "waiting": waiting_pid},
                ):
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(verify_blocked(), timeout=5)
            assert not contender_task.done()
            await operation(holder, first)
            await holder.commit()
        assert await asyncio.wait_for(contender_task, timeout=10) == 409
    finally:
        if not contender_task.done():
            contender_task.cancel()
        await asyncio.gather(contender_task, return_exceptions=True)
    async with pg_factory() as session:
        access = await session.scalar(select(GCGroupAccessModel))
        assert access.revision == revision + 1
        assert (access.removed_at is not None) == (first == "remove")


async def test_migration_keeps_existing_rows_and_enforces_removed_access_gate(pg_factory):
    async with pg_factory() as session:
        original = await session.scalar(text("SELECT current_schema()"))
        assert original.startswith("fcm_dispatch_test_")
        schema = f"gc_removal_migration_{uuid.uuid4().hex}"
        await session.execute(text(f'CREATE SCHEMA "{schema}"'))
        await session.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        await session.execute(text("CREATE TABLE gc_group_access (id uuid PRIMARY KEY, is_enabled boolean NOT NULL, revoked_at timestamptz, original_name text NOT NULL)"))
        await session.execute(text("CREATE TABLE retained_history (id uuid PRIMARY KEY, access_id uuid REFERENCES gc_group_access(id), body text NOT NULL)"))
        access_id, history_id = uuid.uuid4(), uuid.uuid4()
        await session.execute(text("INSERT INTO gc_group_access VALUES (:id, true, NULL, 'Original trip')"), {"id": access_id})
        await session.execute(text("INSERT INTO retained_history VALUES (:id, :access_id, 'Historical message')"), {"id": history_id, "access_id": access_id})
        path = Path(__file__).resolve().parents[2] / "alembic/versions/0099_gc_group_access_removal.py"
        spec = importlib.util.spec_from_file_location("gc_group_removal_migration", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        connection = await session.connection()

        def upgrade(sync_connection):
            with Operations.context(MigrationContext.configure(sync_connection)):
                module.upgrade()

        await connection.run_sync(upgrade)
        assert (await session.execute(text("SELECT id, is_enabled, revoked_at, original_name, removed_at FROM gc_group_access"))).one() == (access_id, True, None, "Original trip", None)
        assert (await session.execute(text("SELECT id, access_id, body FROM retained_history"))).one() == (history_id, access_id, "Historical message")
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                await session.execute(text("UPDATE gc_group_access SET removed_at=now()"))
        await session.execute(text("UPDATE gc_group_access SET is_enabled=false, revoked_at=now(), removed_at=now()"))
        with pytest.raises(RuntimeError, match="downgrade refused"):
            module.downgrade()
        await session.commit()
        print(f"GC_REMOVAL_MIGRATION_SCHEMA_RETAINED={schema}")
