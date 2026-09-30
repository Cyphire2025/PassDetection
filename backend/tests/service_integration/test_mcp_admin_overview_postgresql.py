"""Retained PostgreSQL administrative count proof; no production/capacity claim."""

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
from sqlalchemy import URL, event, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.mcp import admin_overview_reads
from app.application.mcp.admin_overview_reads import (
    AdminOverviewReadError,
    MCPAdminOverviewReadService,
)
from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.credentials import MCPAuthError
from app.application.use_cases.admin_overview import ADMIN_OVERVIEW_FIELDS
from app.core.config.mcp import MCPSettings
from app.domain.entities.entities import UserRole
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    PassportExportHistoryModel,
    PassportSubmissionModel,
    UserModel,
    UserSecurityStateModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes.admin import get_admin_overview
from tests.integration.test_mcp_operations import seed_identity
from tests.mcp_admin_overview_fixtures import (
    AGENCY_COUNTS,
    GLOBAL_COUNTS,
    NULL_AGENCY_COUNTS,
    seed_admin_overview,
)
from tests.postgresql_schema import create_isolated_postgresql_tables

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"
    ),
]
BUSINESS_MODELS = (AgencyModel, UserModel, ClientGroupModel, PassportSubmissionModel)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def admin_postgres(test_settings, record_testsuite_property):
    host, database = os.environ.get("POSTGRES_HOST", "localhost"), os.environ["POSTGRES_DB"]
    if host not in {"127.0.0.1", "localhost"} or not database.startswith("passdetection_ci_"):
        pytest.fail("Admin overview proof requires the dedicated loopback CI database")
    schema = "manual_review_" + uuid.uuid4().hex
    record_testsuite_property("retained_admin_overview_postgresql_schema", schema)
    engine = create_async_engine(
        URL.create(
            "postgresql+asyncpg",
            username=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
            host=host,
            port=int(os.environ["POSTGRES_PORT"]),
            database=database,
        ),
        poolclass=NullPool,
        connect_args={
            "server_settings": {
                "search_path": schema,
                "statement_timeout": "15000",
                "lock_timeout": "5000",
            }
        },
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    settings = test_settings.model_copy(update={"mcp": MCPSettings(enabled=True)})
    try:
        async with engine.begin() as connection:
            assert await connection.scalar(
                text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='pg_trgm')")
            )
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await create_isolated_postgresql_tables(connection, schema)
        async with sessions() as session:
            session.add(MCPControlModel(id=1, enabled=True))
            actor, grants, _ = await seed_identity(session, settings)
            data = await seed_admin_overview(session, actor, opaque_size=2 * 1024 * 1024)
            grants[0].capabilities = ["mcp:read"]
            await session.commit()
            grant = grants[0]
            principal = MCPPrincipal(
                grant.id, actor.id, grant.client_id, ("mcp:read",), grant.expires_at, grant.resource
            )
        yield SimpleNamespace(
            engine=engine,
            sessions=sessions,
            settings=settings,
            schema=schema,
            actor=actor.id,
            principal=principal,
            agencies=[row.id for row in data.agencies],
            groups=[(row.id, row.status) for row in data.groups],
        )
    finally:
        await engine.dispose()  # Retain this synthetic schema and all rows.


@pytest.fixture(autouse=True)
def forbid_external_io(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Admin overview cannot contact a provider or storage")

    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(MinioStorageRepository, "__init__", forbidden)


def service(f, session, settings=None):
    return MCPAdminOverviewReadService(session, settings or f.settings)


async def snapshot(f, session):
    hashes = [
        (
            await session.execute(
                text(
                    f'SELECT id, md5(row_to_json(t)::text) FROM "{f.schema}"."{model.__tablename__}" t ORDER BY id'
                )
            )
        ).all()
        for model in BUSINESS_MODELS
    ]
    counts = [
        await session.scalar(select(func.count()).select_from(model))
        for model in (
            MCPOperationModel,
            MCPArtifactModel,
            PassportExportHistoryModel,
            WhatsAppMessageLogModel,
            AuditLogModel,
        )
    ]
    return hashes, counts


async def test_postgresql_exact_website_seven_counts_global_and_null_agency(admin_postgres):
    f = admin_postgres
    async with f.sessions() as session:
        for agency in (None, *f.agencies):
            await session.execute(
                update(UserModel).where(UserModel.id == f.actor).values(agency_id=agency)
            )
            actor = await UserRepository(session).get_by_id(f.actor)
            before = await snapshot(f, session)
            expected = (await get_admin_overview(actor, session)).model_dump()
            result = await service(f, session).get_overview(f.principal)
            assert (
                {name: result[name] for name in ADMIN_OVERVIEW_FIELDS} == expected == GLOBAL_COUNTS
            )
            assert result["scope"] == "platform_global" and result["completeness"] == "complete"
            assert result["consistency"] == {
                "mode": "live_multi_query",
                "snapshot_guaranteed": False,
            }
            assert await snapshot(f, session) == before
        await session.rollback()
        actor = await UserRepository(session).get_by_id(f.actor)
        actor.role, actor.agency_id = UserRole.AGENCY_ADMIN, f.agencies[0]
        assert (await get_admin_overview(actor, session)).model_dump() == AGENCY_COUNTS
        actor.agency_id = None
        assert (await get_admin_overview(actor, session)).model_dump() == NULL_AGENCY_COUNTS


async def test_postgresql_legacy_parent_filter_and_all_visible_client_submitted_label(
    admin_postgres,
):
    f = admin_postgres
    async with f.sessions() as session:
        result = await service(f, session).get_overview(f.principal)
        literal_client_submitted = await session.scalar(
            select(func.count())
            .select_from(PassportSubmissionModel)
            .join(ClientGroupModel, PassportSubmissionModel.group_id == ClientGroupModel.id)
            .where(
                PassportSubmissionModel.status == "client_submitted",
                ClientGroupModel.status.notin_(["archived", "deleted"]),
            )
        )
        assert literal_client_submitted == 4 < result["client_submitted"] == 24
        # Existing predicates include closed/import-only/expired groups and
        # exclude only parent status, not an independent deleted_at predicate.
        closed = next(identifier for identifier, status in f.groups if status == "closed")
        await session.execute(
            update(ClientGroupModel)
            .where(ClientGroupModel.id == closed)
            .values(deleted_at=datetime.now(UTC))
        )
        result = await service(f, session).get_overview(f.principal)
        assert {name: result[name] for name in ADMIN_OVERVIEW_FIELDS} == GLOBAL_COUNTS
        assert (
            result["passport_submissions"] == 48
            and result["pending_review"] == 12
            and result["failed"] == 4
        )
        await session.rollback()


async def test_postgresql_seven_scalar_queries_over_large_private_json_no_hydration(admin_postgres):
    f, statements = admin_postgres, []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())

    def forbidden(*_args):
        raise AssertionError("Admin overview hydrated a private business ORM row")

    async with f.sessions() as session:
        before = await snapshot(f, session)
        event.listen(f.engine.sync_engine, "before_cursor_execute", capture)
        for model in (AgencyModel, ClientGroupModel, PassportSubmissionModel):
            event.listen(model, "load", forbidden)
            event.listen(model, "refresh", forbidden)
        try:
            result = await service(f, session).get_overview(f.principal)
        finally:
            event.remove(f.engine.sync_engine, "before_cursor_execute", capture)
            for model in (AgencyModel, ClientGroupModel, PassportSubmissionModel):
                event.remove(model, "load", forbidden)
                event.remove(model, "refresh", forbidden)
        business = [s for s in statements if s.startswith("select count(")]
        assert (
            len(business) == 7 and len(statements) == 10
        )  # Three live authority queries, no extra UserRepository hydration.
        assert sum("join client_groups" in s for s in business) == 3
        assert not any(
            private in "\n".join(business)
            for private in (
                "client_name",
                "client_email",
                "image_s3_key",
                "extracted_fields",
                "notes",
                "full_name",
                "hashed_password",
            )
        )
        assert not any(s.lstrip().startswith(("insert", "update", "delete")) for s in statements)
        assert "SECRET" not in json.dumps(result) and "PRIVATE" not in json.dumps(result)
        assert await snapshot(f, session) == before


async def test_postgresql_complete_unicode_envelope_bound_is_static_and_preserves_rows(
    admin_postgres,
):
    f = admin_postgres
    async with f.sessions() as session:
        before = await snapshot(f, session)
        settings = f.settings.model_copy(update={"app_revision": "界" * 1600})
        with pytest.raises(AdminOverviewReadError, match="admin_overview_limit") as denied:
            await service(f, session, settings).get_overview(f.principal)
        assert str(denied.value) == "admin_overview_limit"
        assert await snapshot(f, session) == before


@pytest.mark.parametrize(
    "change",
    [
        "revoked",
        "capability",
        "expired",
        "inactive",
        "deleted",
        "role",
        "security_version",
        "wrong_actor",
        "control",
    ],
)
async def test_postgresql_live_authority_precedes_every_business_count(admin_postgres, change):
    f, now = admin_postgres, datetime.now(UTC)
    async with f.sessions() as session:
        principal = f.principal
        if change in {"revoked", "capability", "expired"}:
            values = {
                "revoked": {"revoked_at": now},
                "capability": {"capabilities": []},
                "expired": {
                    "created_at": now - timedelta(days=2),
                    "expires_at": now - timedelta(days=1),
                },
            }[change]
            await session.execute(
                update(MCPGrantModel).where(MCPGrantModel.id == principal.grant_id).values(**values)
            )
        elif change in {"inactive", "deleted", "role"}:
            values = {
                "inactive": {"is_active": False},
                "deleted": {"deleted_at": now},
                "role": {"role": "agency_admin"},
            }[change]
            await session.execute(update(UserModel).where(UserModel.id == f.actor).values(**values))
        elif change == "security_version":
            await session.execute(
                update(UserSecurityStateModel)
                .where(UserSecurityStateModel.user_id == f.actor)
                .values(session_version=2)
            )
        elif change == "control":
            await session.execute(
                update(MCPControlModel).where(MCPControlModel.id == 1).values(enabled=False)
            )
        else:
            principal = replace(principal, user_id=uuid.uuid4())
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            statements.append(statement.lower())

        event.listen(f.engine.sync_engine, "before_cursor_execute", capture)
        try:
            with pytest.raises(MCPAuthError):
                await service(f, session).get_overview(principal)
        finally:
            event.remove(f.engine.sync_engine, "before_cursor_execute", capture)
        assert not any(s.startswith("select count(") for s in statements)
        await session.rollback()
        assert (await service(f, session).get_overview(f.principal))["completeness"] == "complete"


@pytest.mark.parametrize("lock", ["source", "grant"])
async def test_postgresql_blocked_sql_deadline_rolls_back_and_retry_succeeds(
    admin_postgres, monkeypatch, lock
):
    f = admin_postgres
    async with f.sessions() as holder, f.sessions() as reader:
        before = await snapshot(f, reader)
        await reader.rollback()
        if lock == "source":
            await holder.execute(text("LOCK TABLE agencies IN ACCESS EXCLUSIVE MODE"))
        else:
            await holder.execute(
                select(MCPGrantModel.id)
                .where(MCPGrantModel.id == f.principal.grant_id)
                .with_for_update()
            )
        monkeypatch.setattr(admin_overview_reads, "ADMIN_OVERVIEW_TIMEOUT_SECONDS", 0.15)
        with pytest.raises(AdminOverviewReadError, match="admin_overview_busy"):
            await service(f, reader).get_overview(f.principal)
        await reader.rollback()
        await holder.rollback()
        monkeypatch.setattr(admin_overview_reads, "ADMIN_OVERVIEW_TIMEOUT_SECONDS", 10)
        assert (await asyncio.wait_for(service(f, reader).get_overview(f.principal), 3))[
            "completeness"
        ] == "complete"
        assert await snapshot(f, reader) == before


async def test_postgresql_current_identity_locked_through_observation(admin_postgres):
    f = admin_postgres
    async with f.sessions() as reader, f.sessions() as writer:
        await service(f, reader).get_overview(f.principal)
        await writer.execute(text("SET LOCAL lock_timeout = '100ms'"))
        with pytest.raises(DBAPIError) as denied:
            await writer.execute(
                update(UserModel).where(UserModel.id == f.actor).values(is_active=False)
            )
        assert getattr(denied.value.orig, "sqlstate", None) == "55P03"
        await writer.rollback()
        await reader.rollback()
        await writer.execute(
            update(UserModel).where(UserModel.id == f.actor).values(is_active=False)
        )
        await writer.rollback()


async def test_postgresql_cancelled_identity_wait_rollback_retry_and_no_effects(admin_postgres):
    f = admin_postgres
    async with f.sessions() as holder, f.sessions() as reader:
        before = await snapshot(f, reader)
        await reader.rollback()
        await holder.execute(select(UserModel.id).where(UserModel.id == f.actor).with_for_update())
        waiting = asyncio.Event()

        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            if "FOR SHARE OF users" in statement:
                waiting.set()

        event.listen(f.engine.sync_engine, "before_cursor_execute", capture)
        task = asyncio.create_task(service(f, reader).get_overview(f.principal))
        try:
            await asyncio.wait_for(waiting.wait(), 3)
            assert not task.done()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await reader.rollback()
            await holder.rollback()
            assert (await service(f, reader).get_overview(f.principal))[
                "completeness"
            ] == "complete"
            assert await snapshot(f, reader) == before
        finally:
            event.remove(f.engine.sync_engine, "before_cursor_execute", capture)
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
