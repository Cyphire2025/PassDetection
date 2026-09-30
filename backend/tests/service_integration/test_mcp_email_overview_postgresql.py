"""Retained PostgreSQL owner-count proof; never mailbox/provider/capacity proof."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import URL, event, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.mcp import email_overview_reads
from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.email_overview_reads import (
    EmailOverviewReadError,
    MCPEmailOverviewReadService,
)
from app.core.config.mcp import MCPSettings
from app.domain.entities.entities import UserRole
from app.infrastructure.database.email_models import (
    EmailArtifactDocumentModel,
    EmailArtifactModel,
    EmailConnectionModel,
    EmailMessageModel,
    EmailReviewItemModel,
)
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import AuditLogModel, UserModel, UserSecurityStateModel
from app.infrastructure.repositories.email_summary_repository import SUMMARY_FIELDS
from app.infrastructure.repositories.user_repository import UserRepository
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes import email_integration_activity, email_integration_connections
from tests.integration.test_mcp_operations import seed_identity
from tests.mcp_email_overview_fixtures import PER_COHORT, seed_email_overview
from tests.postgresql_schema import create_isolated_postgresql_tables

pytestmark = [pytest.mark.service_integration, pytest.mark.skipif(
    os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required")]
MODELS = (EmailConnectionModel, EmailMessageModel, EmailArtifactModel, EmailArtifactDocumentModel, EmailReviewItemModel)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def email_postgres(test_settings, record_testsuite_property):
    host, database = os.environ.get("POSTGRES_HOST", "localhost"), os.environ["POSTGRES_DB"]
    if host not in {"127.0.0.1", "localhost"} or not database.startswith("passdetection_ci_"):
        pytest.fail("Email overview proof requires the dedicated loopback CI database")
    schema = "manual_review_" + uuid.uuid4().hex
    record_testsuite_property("retained_email_overview_postgresql_schema", schema)
    engine = create_async_engine(URL.create("postgresql+asyncpg", username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"], host=host, port=int(os.environ["POSTGRES_PORT"]), database=database),
        poolclass=NullPool, connect_args={"server_settings": {
            "search_path": schema, "statement_timeout": "15000", "lock_timeout": "5000"}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    settings = test_settings.model_copy(update={"mcp": MCPSettings(enabled=True)})
    try:
        async with engine.begin() as connection:
            assert await connection.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='pg_trgm')"))
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await create_isolated_postgresql_tables(connection, schema)
        async with sessions() as session:
            session.add(MCPControlModel(id=1, enabled=True))
            actor, grants, _ = await seed_identity(session, settings)
            data = await seed_email_overview(session, actor, opaque_size=2 * 1024 * 1024)
            grants[0].capabilities = ["mcp:read"]
            await session.commit()
            grant = grants[0]
            principal = MCPPrincipal(grant.id, actor.id, grant.client_id, ("mcp:read",), grant.expires_at, grant.resource)
        yield SimpleNamespace(engine=engine, sessions=sessions, settings=settings, schema=schema,
                              actor=actor.id, principal=principal, data=data)
    finally:
        await engine.dispose()  # Retain this synthetic schema and all rows.


@pytest.fixture(autouse=True)
def forbid_external_io(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Email overview reads must not call a provider or storage")
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(MinioStorageRepository, "__init__", forbidden)


def service(f, session, settings=None):
    return MCPEmailOverviewReadService(session, settings or f.settings)


async def snapshot(f, session):
    hashes = [(await session.execute(text(f'SELECT id, md5(row_to_json(t)::text) FROM "{f.schema}"."{model.__tablename__}" t ORDER BY id'))).all()
              for model in MODELS]
    counts = [await session.scalar(select(func.count()).select_from(model)) for model in (
        MCPOperationModel, MCPArtifactModel, AuditLogModel)]
    return hashes, counts


async def test_postgresql_exact_owner_counts_utc_json_predicates_and_website_parity(email_postgres, monkeypatch):
    f = email_postgres
    monkeypatch.setattr(email_overview_reads, "email_summary_day_start", lambda: f.data.today)
    monkeypatch.setattr(email_integration_activity, "email_summary_day_start", lambda: f.data.today)
    async with f.sessions() as session:
        before = await snapshot(f, session)
        for agency in (None, f.data.agencies[0].id, f.data.agencies[1].id):
            await session.execute(update(UserModel).where(UserModel.id == f.actor).values(agency_id=agency))
            actor = await UserRepository(session).get_by_id(f.actor)
            expected = await email_integration_activity.email_integration_summary(actor, session)
            actual = await service(f, session).get_summary(f.principal)
            assert {name: actual[name] for name in SUMMARY_FIELDS} == expected.model_dump() == f.data.expected
            assert actual["period_start_utc"] == f.data.today.isoformat()
            assert actual["mailbox_scope"] == "personal_owner_only"
            assert actual["consistency"] == {"mode": "live_multi_query", "snapshot_guaranteed": False}
            assert "SECRET" not in json.dumps(actual) and "PRIVATE" not in json.dumps(actual)
        assert f.data.agencies[0].is_active is False
        actor.role, actor.agency_id = UserRole.AGENCY_STAFF, f.data.agencies[0].id
        assert (await email_integration_activity.email_integration_summary(actor, session)).model_dump() == PER_COHORT
        assert await snapshot(f, session) == before
        await session.rollback()


async def test_postgresql_large_opaque_json_only_seven_scalar_counts_no_private_hydration(email_postgres):
    f = email_postgres
    statements = []
    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())
    def forbidden(*_args):
        raise AssertionError("Email summary hydrated a private mailbox ORM row")
    event.listen(f.engine.sync_engine, "before_cursor_execute", capture)
    for model in MODELS:
        event.listen(model, "load", forbidden)
        event.listen(model, "refresh", forbidden)
    try:
        async with f.sessions() as session:
            result = await service(f, session).get_summary(f.principal)
    finally:
        event.remove(f.engine.sync_engine, "before_cursor_execute", capture)
        for model in MODELS:
            event.remove(model, "load", forbidden)
            event.remove(model, "refresh", forbidden)
    business = [query for query in statements if "from email_" in query]
    assert len(statements) == 11 and len(business) == 7
    assert all(query.startswith("select count(") and "owner_user_id =" in query for query in business)
    projections = "\n".join(query.split("\nfrom")[0] for query in business)
    assert not any(private in projections for private in ("ciphertext", "body", "subject", "match_evidence", "storage", "email_address", "provider_account"))
    assert any("match_evidence" in query and "is false" in query for query in business)
    assert not any(query.lstrip().startswith(("insert", "update", "delete")) for query in statements)
    assert len(json.dumps(result, ensure_ascii=True).encode()) < 8192
    assert {name: result[name] for name in SUMMARY_FIELDS} == f.data.expected


async def test_postgresql_status_configuration_only_no_mailbox_selects_or_secrets(email_postgres, monkeypatch):
    f = email_postgres
    settings = f.settings.model_copy(update=dict(email_integrations_enabled=True, email_sync_enabled=True,
        email_ai_enabled=True, google_api_key=SecretStr("SECRET_API_KEY"), email_ai_notifications_enabled=True,
        gmail_oauth_client_id="SECRET_ID", gmail_oauth_client_secret=SecretStr("SECRET_CLIENT"),
        gmail_oauth_redirect_uri="https://private.example/callback", email_token_encryption_key=SecretStr("SECRET_KEY"),
        outlook_oauth_client_id=None))
    monkeypatch.setattr(email_integration_connections, "get_settings", lambda: settings)
    async with f.sessions() as session:
        actor = await UserRepository(session).get_by_id(f.actor)
        expected = (await email_integration_connections.email_integration_status(actor)).model_dump()
        statements = []
        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            statements.append(statement.lower())
        event.listen(f.engine.sync_engine, "before_cursor_execute", capture)
        try:
            actual = await service(f, session, settings).get_status(f.principal)
        finally:
            event.remove(f.engine.sync_engine, "before_cursor_execute", capture)
        assert len(statements) == 4 and not any("from email_" in query for query in statements)
        assert {key: actual[key] for key in expected} == expected
        assert actual["providers"][0]["configured"] is True and actual["providers"][1]["configured"] is False
        assert "SECRET" not in json.dumps(actual) and "private.example" not in json.dumps(actual)
        assert actual["consistency"]["mode"] == "configuration_observation"


@pytest.mark.parametrize("change", ["revoked", "capability", "expired", "inactive", "deleted", "role", "security_version", "wrong_actor"])
async def test_postgresql_live_authority_blocks_both_reads_before_mailbox_queries(email_postgres, change):
    f, now = email_postgres, datetime.now(UTC)
    async with f.sessions() as session:
        principal = f.principal
        if change in {"revoked", "capability", "expired"}:
            values = {"revoked": {"revoked_at": now}, "capability": {"capabilities": []},
                "expired": {"created_at": now - timedelta(days=2), "expires_at": now - timedelta(days=1)}}[change]
            await session.execute(update(MCPGrantModel).where(MCPGrantModel.id == principal.grant_id).values(**values))
        elif change in {"inactive", "deleted", "role"}:
            values = {"inactive": {"is_active": False}, "deleted": {"deleted_at": now}, "role": {"role": "agency_staff"}}[change]
            await session.execute(update(UserModel).where(UserModel.id == f.actor).values(**values))
        elif change == "security_version":
            await session.execute(update(UserSecurityStateModel).where(UserSecurityStateModel.user_id == f.actor).values(session_version=2))
        else:
            principal = replace(principal, user_id=f.data.other.id)
        statements = []
        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            statements.append(statement.lower())
        event.listen(f.engine.sync_engine, "before_cursor_execute", capture)
        try:
            for method in ("get_status", "get_summary"):
                with pytest.raises(MCPAuthError):
                    await getattr(service(f, session), method)(principal)
        finally:
            event.remove(f.engine.sync_engine, "before_cursor_execute", capture)
        assert not any("from email_" in query for query in statements)
        await session.rollback()
        assert (await service(f, session).get_status(f.principal))["completeness"] == "complete"


@pytest.mark.parametrize(("lock", "method"), [("source", "get_summary"), ("grant", "get_summary"), ("grant", "get_status")])
async def test_postgresql_real_blocked_sql_deadline_rollback_retry(email_postgres, monkeypatch, lock, method):
    f = email_postgres
    async with f.sessions() as holder, f.sessions() as reader:
        before = await snapshot(f, reader)
        await reader.rollback()
        if lock == "source":
            await holder.execute(text("LOCK TABLE email_messages IN ACCESS EXCLUSIVE MODE"))
        else:
            await holder.execute(select(MCPGrantModel.id).where(MCPGrantModel.id == f.principal.grant_id).with_for_update())
        monkeypatch.setattr(email_overview_reads, "EMAIL_OVERVIEW_TIMEOUT_SECONDS", 0.15)
        with pytest.raises(EmailOverviewReadError, match="email_overview_busy"):
            await getattr(service(f, reader), method)(f.principal)
        await reader.rollback()
        await holder.rollback()
        monkeypatch.setattr(email_overview_reads, "EMAIL_OVERVIEW_TIMEOUT_SECONDS", 10)
        result = await asyncio.wait_for(getattr(service(f, reader), method)(f.principal), 3)
        assert result["completeness"] == "complete" and await snapshot(f, reader) == before


async def test_postgresql_owner_change_waits_until_read_transaction_finishes(email_postgres):
    f = email_postgres
    async with f.sessions() as reader, f.sessions() as writer:
        await service(f, reader).get_summary(f.principal)
        await writer.execute(text("SET LOCAL lock_timeout = '100ms'"))
        with pytest.raises(DBAPIError) as denied:
            await writer.execute(update(UserModel).where(UserModel.id == f.actor).values(is_active=False))
        assert getattr(denied.value.orig, "sqlstate", None) == "55P03"
        await writer.rollback()
        await reader.rollback()
        await writer.execute(update(UserModel).where(UserModel.id == f.actor).values(is_active=False))
        await writer.rollback()


async def test_postgresql_external_cancellation_leaves_mailbox_and_audit_unchanged(email_postgres):
    f = email_postgres
    async with f.sessions() as holder, f.sessions() as reader:
        before = await snapshot(f, reader)
        await reader.rollback()
        await holder.execute(select(UserModel.id).where(UserModel.id == f.actor).with_for_update())
        waiting = asyncio.Event()
        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            if "FOR SHARE OF users" in statement:
                waiting.set()
        event.listen(f.engine.sync_engine, "before_cursor_execute", capture)
        task = asyncio.create_task(service(f, reader).get_summary(f.principal))
        try:
            await asyncio.wait_for(waiting.wait(), 3)
            assert not task.done()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await reader.rollback()
            await holder.rollback()
            result = await service(f, reader).get_summary(f.principal)
            assert {key: result[key] for key in SUMMARY_FIELDS} == f.data.expected
            assert await snapshot(f, reader) == before
        finally:
            event.remove(f.engine.sync_engine, "before_cursor_execute", capture)
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
