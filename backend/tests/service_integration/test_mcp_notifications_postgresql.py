"""Retained-schema notification proof: real PostgreSQL, no delivery/load claim."""

import asyncio
import os
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import URL, event, func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.mcp import notification_reads
from app.application.mcp.notification_changes import notification_acknowledgement_operation
from app.application.mcp.notification_reads import MCPNotificationReadService
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.core.config.mcp import MCPSettings
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_models import MCPControlModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AuditLogModel,
    NotificationModel,
    PassportExportHistoryModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.repositories.notification_projection_repository import (
    NotificationProjectionLimitError,
)
from app.infrastructure.repositories.notification_repository import NotificationRepository
from tests.integration.test_mcp_operations import seed_identity
from tests.mcp_notification_fixtures import seed_notifications
from tests.postgresql_schema import create_isolated_postgresql_tables

pytestmark = [pytest.mark.service_integration, pytest.mark.skipif(
    os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required")]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def notification_postgres(test_settings, record_testsuite_property):
    host, database = os.environ.get("POSTGRES_HOST", "localhost"), os.environ["POSTGRES_DB"]
    if host not in {"127.0.0.1", "localhost"} or not database.startswith("passdetection_ci_"):
        pytest.fail("Notification proof requires the dedicated loopback CI database")
    schema = "manual_review_" + uuid.uuid4().hex
    record_testsuite_property("retained_notification_postgresql_schema", schema)
    engine = create_async_engine(URL.create("postgresql+asyncpg", username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"], host=host, port=int(os.environ["POSTGRES_PORT"]), database=database),
        poolclass=NullPool, connect_args={"server_settings": {
            "search_path": schema, "statement_timeout": "15000", "lock_timeout": "5000"}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    settings = test_settings.model_copy(update={"mcp": MCPSettings(enabled=True)})
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await create_isolated_postgresql_tables(connection, schema)
        async with sessions() as session:
            session.add(MCPControlModel(id=1, enabled=True))
            actor, grants, tokens = await seed_identity(session, settings, enable_write_policy=True)
            data = await seed_notifications(session, actor.id)
            for index in range(150):
                session.add(NotificationModel(id=uuid.UUID(f"bbbbbbbb-0000-0000-0000-{index:012x}"),
                    agency_id=data.agencies[index % 2].id, user_id=actor.id,
                    type="synthetic", title=f"Synthetic {index}", message="Synthetic retained feed",
                    metadata_json={"private": "x" * (2 * 1024 * 1024) if index == 149 else "hidden",
                        "provider": "gmail", "group_name": ["not text"]},
                    created_at=datetime(2026, 9, 2, tzinfo=UTC)))
            await session.commit()
        yield SimpleNamespace(engine=engine, sessions=sessions, settings=settings,
            actor=actor.id, grants=[g.id for g in grants], tokens=tokens, data=data)
    finally:
        # Intentionally retain every fixture row and schema for evidence.
        await engine.dispose()


def reader(f, session):
    return MCPNotificationReadService(session, cursor_secret=f.settings.app_secret_key, namespace="personal-notifications")


async def acknowledge(f, session, identifier, key, index=0):
    definition = notification_acknowledgement_operation(f.settings.app_secret_key)
    return await MCPOperationService(session, f.settings, [definition]).execute(
        access_token=f.tokens[index], operation_name=definition.policy.name,
        idempotency_key=key, payload={"notification_id": str(identifier)})


async def test_postgresql_canonical_pages_counts_scope_and_bounded_projection(notification_postgres):
    f = notification_postgres
    statements = []
    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement.lower())
    def forbidden(*args):
        raise AssertionError("Notification read hydrated a whole ORM row")
    async with f.sessions() as session:
        event.listen(f.engine.sync_engine, "before_cursor_execute", capture)
        event.listen(NotificationModel, "load", forbidden)
        event.listen(NotificationModel, "refresh", forbidden)
        try:
            page = await reader(f, session).list_personal(f.actor, page_size=100)
        finally:
            event.remove(f.engine.sync_engine, "before_cursor_execute", capture)
            event.remove(NotificationModel, "load", forbidden)
            event.remove(NotificationModel, "refresh", forbidden)
        assert len(statements) == 4 and all(sql.startswith("select") for sql in statements)
        assert "limit" in statements[2] and "jsonb_typeof" in statements[2] and "substr(" in statements[2]
        assert " notifications.metadata," not in statements[2].split("\nfrom")[0]
        assert page["unread_count"] == 152 and len(page["items"]) == 100 and page["has_more"]
        assert page["items"][0]["metadata"] == {"provider": "gmail"}
        web, count, _cursor = await NotificationRepository(session).list_direct_feed(user_id=f.actor, agency_id=None, limit=100)
        assert [row["id"] for row in page["items"]] == [str(row.id) for row in web]
        assert page["unread_count"] == count
        next_page = await reader(f, session).list_personal(f.actor, page_size=100, cursor=page["next_cursor"])
        assert len(next_page["items"]) == 53 and next_page["next_cursor"] is None
        assert len({row["id"] for row in page["items"] + next_page["items"]}) == 153
        for model in (MCPOperationModel, MCPArtifactModel, PassportExportHistoryModel, WhatsAppMessageLogModel):
            assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_postgresql_oversize_field_and_unicode_response_budget(notification_postgres):
    f = notification_postgres
    async with f.sessions() as session:
        await session.execute(update(NotificationModel).where(NotificationModel.user_id == f.actor).values(message="🙂" * 4096))
        with pytest.raises(NotificationProjectionLimitError):
            await reader(f, session).list_personal(f.actor, page_size=100)
        assert len((await reader(f, session).list_personal(f.actor, page_size=1))["items"]) == 1
        await session.execute(update(NotificationModel).where(NotificationModel.user_id == f.actor).values(message="x" * 4097))
        with pytest.raises(NotificationProjectionLimitError):
            await reader(f, session).list_personal(f.actor, page_size=1)
        await session.rollback()


async def test_postgresql_same_operation_concurrency_and_cross_connection_recovery(notification_postgres):
    f, identifier = notification_postgres, notification_postgres.data.rows[0].id
    async def run(index):
        async with f.sessions() as session:
            result = await acknowledge(f, session, identifier, "pg-concurrent-personal-ack-001", index % 2)
            await session.commit()
            return result
    receipts = await asyncio.gather(*(run(index) for index in range(6)))
    assert all(result == receipts[0] for result in receipts)
    assert receipts[0]["data"]["changed"] is True
    async with f.sessions() as session:
        next_ack = await acknowledge(f, session, identifier, "pg-second-personal-ack-001", 1)
        assert next_ack["data"]["changed"] is False
        assert next_ack["data"]["read_at"] == receipts[0]["data"]["read_at"]
        assert await session.scalar(select(func.count()).select_from(MCPOperationModel)) == 2
        assert await session.scalar(select(func.count()).select_from(AuditLogModel)
            .where(AuditLogModel.action == "notification.mcp_acknowledged")) == 2
        await session.commit()


async def test_postgresql_nowait_busy_rolls_back_and_identical_intent_recovers(notification_postgres):
    f, identifier = notification_postgres, notification_postgres.data.rows[2].id
    async with f.sessions() as blocker, f.sessions() as caller:
        before = await caller.scalar(select(func.count()).select_from(MCPOperationModel))
        await blocker.execute(select(NotificationModel.id).where(NotificationModel.id == identifier).with_for_update())
        with pytest.raises(MCPOperationError, match="notification_busy"):
            await acknowledge(f, caller, identifier, "pg-busy-personal-ack-001")
        await caller.rollback()
        assert await caller.scalar(select(func.count()).select_from(MCPOperationModel)) == before
        assert not await caller.scalar(select(NotificationModel.is_read).where(NotificationModel.id == identifier))
        await blocker.rollback()
        result = await acknowledge(f, caller, identifier, "pg-busy-personal-ack-001")
        assert result["data"]["changed"] is True
        await caller.commit()


async def test_postgresql_replay_lock_busy_then_current_owned_receipt_recovers(notification_postgres):
    f, identifier = notification_postgres, notification_postgres.data.rows[0].id
    async with f.sessions() as blocker, f.sessions() as caller:
        await blocker.execute(select(NotificationModel.id).where(NotificationModel.id == identifier).with_for_update())
        with pytest.raises(MCPOperationError, match="notification_busy"):
            await acknowledge(f, caller, identifier, "pg-concurrent-personal-ack-001")
        await caller.rollback()
        await blocker.rollback()
        result = await acknowledge(f, caller, identifier, "pg-concurrent-personal-ack-001", 1)
        assert result["data"]["changed"] is True  # Immutable original receipt, no reapplication.
        assert await caller.scalar(select(func.count()).select_from(MCPOperationModel)) == 3


async def test_postgresql_real_query_deadline_rollback_and_clean_retry(notification_postgres, monkeypatch):
    f = notification_postgres
    async with f.sessions() as blocker, f.sessions() as caller:
        await blocker.execute(text("LOCK TABLE notifications IN ACCESS EXCLUSIVE MODE"))
        monkeypatch.setattr(notification_reads, "NOTIFICATION_READ_TIMEOUT_SECONDS", 0.1)
        with pytest.raises(TimeoutError):
            await reader(f, caller).list_personal(f.actor)
        await caller.rollback()
        await blocker.rollback()
        monkeypatch.setattr(notification_reads, "NOTIFICATION_READ_TIMEOUT_SECONDS", 10)
        result = await reader(f, caller).list_personal(f.actor)
        assert len(result["items"]) == 30
        for model in (MCPArtifactModel, PassportExportHistoryModel, WhatsAppMessageLogModel):
            assert await caller.scalar(select(func.count()).select_from(model)) == 0
