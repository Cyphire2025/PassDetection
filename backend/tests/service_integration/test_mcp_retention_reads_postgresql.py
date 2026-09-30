"""Retained, isolated PostgreSQL schedule reads; no purge or workload qualification."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import URL, event, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.mcp import retention_reads
from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.retention_reads import (
    MCPPassportRetentionReadService,
    RetentionReadError,
)
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
from app.presentation.api.v1.routes.admin import get_group_passport_retention
from tests.integration.test_mcp_operations import seed_identity
from tests.postgresql_schema import create_isolated_postgresql_tables

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"
    ),
]
PAST = datetime(2001, 1, 2, 3, 4, 5, tzinfo=UTC)
FUTURE = datetime(2099, 12, 31, 23, 59, 59, tzinfo=UTC)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def retention_postgres(test_settings, record_testsuite_property):
    host, database = os.environ.get("POSTGRES_HOST", "localhost"), os.environ["POSTGRES_DB"]
    if host not in {"127.0.0.1", "localhost"} or not database.startswith("passdetection_ci_"):
        pytest.fail("Retention proof requires the dedicated loopback CI database")
    schema = "manual_review_" + uuid.uuid4().hex
    record_testsuite_property("retained_retention_postgresql_schema", schema)
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
                "timezone": "UTC",
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
            grants[0].capabilities = ["mcp:read"]
            agencies = [
                AgencyModel(
                    id=uuid.uuid4(),
                    name="PRIVATE synthetic agency",
                    email=f"{uuid.uuid4()}@example.test",
                    is_active=active,
                )
                for active in (True, False)
            ]
            session.add_all(agencies)
            await session.flush()
            cases = {
                "active": (0, "active", None, None, False),
                "closed": (0, "closed", PAST, 1, False),
                "archived": (0, "archived", FUTURE, 3650, False),
                "deleted_held": (1, "deleted", None, 90, True),
                "inactive_agency": (1, "active", FUTURE, 7, False),
                "legacy_date_only": (0, "closed", PAST, None, False),
            }
            groups = {}
            for name, (index, status, purge_at, days, held) in cases.items():
                group = ClientGroupModel(
                    id=uuid.uuid4(),
                    agency_id=agencies[index].id,
                    name="PRIVATE group",
                    token=uuid.uuid4().hex,
                    status=status,
                    passport_purge_at=purge_at,
                    passport_retention_days_applied=days,
                    deleted_at=PAST if status == "deleted" else None,
                    passport_legal_hold=held,
                    passport_legal_hold_reason="PRIVATE retired evidence" if held else None,
                    passport_legal_hold_set_at=PAST if held else None,
                    notes="PRIVATE" + "界" * (128 * 1024),
                    upload_configuration={"PRIVATE": "no file access"},
                )
                session.add(group)
                groups[name] = group
            await session.flush()
            session.add(
                PassportSubmissionModel(
                    id=uuid.uuid4(),
                    group_id=groups["deleted_held"].id,
                    agency_id=agencies[1].id,
                    client_name="PRIVATE retained passport",
                    image_s3_key="PRIVATE/storage",
                    status="confirmed",
                    extracted_fields={"PRIVATE": "界" * (128 * 1024)},
                )
            )
            principal = MCPPrincipal(
                grants[0].id,
                actor.id,
                grants[0].client_id,
                ("mcp:read",),
                grants[0].expires_at,
                grants[0].resource,
            )
            await session.commit()
        yield SimpleNamespace(
            engine=engine,
            sessions=sessions,
            schema=schema,
            settings=settings,
            principal=principal,
            actor=actor.id,
            agency=agencies[0].id,
            other_agency=agencies[1].id,
            groups={key: group.id for key, group in groups.items()},
            cases=cases,
        )
    finally:
        # Every synthetic table, row and schema is retained. No public-state mutation.
        await engine.dispose()


def service(f, session, settings=None):
    return MCPPassportRetentionReadService(session, settings or f.settings)


async def snapshot(session):
    hashes = []
    for table in ("client_groups", "passport_submissions"):
        hashes.append(
            await session.scalar(
                text(
                    f"SELECT md5(coalesce(string_agg(to_jsonb(t)::text, '' ORDER BY id), '')) FROM {table} t"
                )
            )
        )
    counts = []
    for model in (
        MCPOperationModel,
        MCPArtifactModel,
        PassportExportHistoryModel,
        WhatsAppMessageLogModel,
        AuditLogModel,
    ):
        counts.append(await session.scalar(select(func.count()).select_from(model)))
    return hashes, counts


@pytest.mark.parametrize(
    "name", ["active", "closed", "archived", "deleted_held", "inactive_agency", "legacy_date_only"]
)
async def test_postgresql_canonical_schedule_parity_includes_retained_groups(
    retention_postgres, name
):
    f = retention_postgres
    async with f.sessions() as session:
        before = await snapshot(session)
        actor = await UserRepository(session).get_by_id(f.actor)
        assert actor.agency_id is None  # Superadmin's no-agency identity remains globally scoped.
        website = await get_group_passport_retention(f.groups[name], actor, session)
        result = await service(f, session).get_schedule(f.principal, group_id=f.groups[name])
        assert result["group_id"] == str(website.group_id)
        assert result["passport_retention_days_applied"] == website.passport_retention_days_applied
        assert result["passport_purge_at"] == (
            website.passport_purge_at.isoformat() if website.passport_purge_at is not None else None
        )
        index, _, purge_at, days, _ = f.cases[name]
        assert result["agency_id"] == str(f.agency if index == 0 else f.other_agency)
        assert result["passport_retention_days_applied"] == days
        assert result["passport_purge_at"] == (purge_at.isoformat() if purge_at else None)
        assert result["scope"] == "explicit_group" and result["completeness"] == "complete"
        assert result["maximum_response_bytes"] == 8192
        assert "does not prove that a purge occurred" in result["notice"]
        assert "PRIVATE" not in json.dumps(result) and "passport_legal_hold" not in result
        assert await snapshot(session) == before


async def test_postgresql_website_own_agency_and_null_scope_unchanged(retention_postgres):
    f = retention_postgres
    async with f.sessions() as session:
        actor = await UserRepository(session).get_by_id(f.actor)
        actor.role, actor.agency_id = UserRole.AGENCY_ADMIN, f.agency
        assert (
            await get_group_passport_retention(f.groups["active"], actor, session)
        ).group_id == f.groups["active"]
        for agency_id, group_id in (
            (f.agency, f.groups["inactive_agency"]),
            (None, f.groups["active"]),
        ):
            actor.agency_id = agency_id
            with pytest.raises(HTTPException) as denied:
                await get_group_passport_retention(group_id, actor, session)
            assert denied.value.status_code == 404


async def test_postgresql_only_four_source_scalars_no_private_hydration_or_effects(
    retention_postgres,
):
    f, statements = retention_postgres, []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement.lower())

    def forbidden(*_args):
        raise AssertionError("Retention read hydrated private business ORM")

    async with f.sessions() as session:
        before = await snapshot(session)
        event.listen(f.engine.sync_engine, "before_cursor_execute", capture)
        for model in (ClientGroupModel, PassportSubmissionModel):
            event.listen(model, "load", forbidden)
            event.listen(model, "refresh", forbidden)
        try:
            await service(f, session).get_schedule(f.principal, group_id=f.groups["deleted_held"])
        finally:
            event.remove(f.engine.sync_engine, "before_cursor_execute", capture)
            for model in (ClientGroupModel, PassportSubmissionModel):
                event.remove(model, "load", forbidden)
                event.remove(model, "refresh", forbidden)
        business = [s for s in statements if "from client_groups" in s]
        assert len(statements) == 4 and len(business) == 1
        assert business[0].split("\nfrom")[0].strip() == (
            "select client_groups.id, client_groups.agency_id, client_groups.passport_purge_at, "
            "client_groups.passport_retention_days_applied"
        )
        assert "for share of client_groups" in business[0]
        assert not any("passport_submissions" in s for s in statements)
        assert not any(s.lstrip().startswith(("insert", "update", "delete")) for s in statements)
        assert await snapshot(session) == before


async def test_postgresql_missing_group_and_complete_unicode_envelope_fail_closed(
    retention_postgres,
):
    f = retention_postgres
    async with f.sessions() as session:
        with pytest.raises(RetentionReadError, match="^retention_schedule_unavailable$"):
            await service(f, session).get_schedule(f.principal, group_id=uuid.uuid4())
        settings = f.settings.model_copy(update={"app_revision": "界" * 1400})
        with pytest.raises(RetentionReadError, match="^retention_read_limit$"):
            await service(f, session, settings).get_schedule(
                f.principal, group_id=f.groups["active"]
            )
        assert (await service(f, session).get_schedule(f.principal, group_id=f.groups["active"]))[
            "completeness"
        ] == "complete"


@pytest.mark.parametrize(
    "change",
    [
        "revoked",
        "expired",
        "capability",
        "inactive",
        "deleted",
        "role",
        "security_version",
        "mfa",
        "credential",
        "wrong_actor",
        "control",
        "rollout",
    ],
)
async def test_postgresql_live_authority_precedes_schedule_query(retention_postgres, change):
    f, now, statements = retention_postgres, datetime.now(UTC), []
    async with f.sessions() as session:
        principal, settings = f.principal, f.settings
        if change in {"revoked", "expired", "capability"}:
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
        elif change in {"security_version", "mfa", "credential"}:
            values = {
                "security_version": {"session_version": 2},
                "mfa": {
                    "mfa_enabled_at": None,
                    "mfa_secret_ciphertext": None,
                    "mfa_last_counter": None,
                },
                "credential": {"credential_state": "invited"},
            }[change]
            await session.execute(
                update(UserSecurityStateModel)
                .where(UserSecurityStateModel.user_id == f.actor)
                .values(**values)
            )
        elif change == "control":
            await session.execute(
                update(MCPControlModel).where(MCPControlModel.id == 1).values(enabled=False)
            )
        elif change == "rollout":
            settings = settings.model_copy(
                update={
                    "mcp": settings.mcp.model_copy(update={"enabled_capabilities": ["mcp:export"]})
                }
            )
        else:
            principal = replace(principal, user_id=uuid.uuid4())

        def capture(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement.lower())

        event.listen(f.engine.sync_engine, "before_cursor_execute", capture)
        try:
            with pytest.raises(MCPAuthError):
                await service(f, session, settings).get_schedule(
                    principal, group_id=f.groups["active"]
                )
        finally:
            event.remove(f.engine.sync_engine, "before_cursor_execute", capture)
        assert not any("from client_groups" in s for s in statements)
        await session.rollback()
        assert (await service(f, session).get_schedule(f.principal, group_id=f.groups["active"]))[
            "completeness"
        ] == "complete"


@pytest.mark.parametrize("lock", ["source", "grant", "identity"])
async def test_postgresql_actual_lock_deadline_rollback_then_retry(
    retention_postgres, monkeypatch, lock
):
    f = retention_postgres
    async with f.sessions() as holder, f.sessions() as reader:
        before = await snapshot(reader)
        await reader.rollback()
        model, key = {
            "source": (ClientGroupModel, f.groups["active"]),
            "grant": (MCPGrantModel, f.principal.grant_id),
            "identity": (UserModel, f.actor),
        }[lock]
        await holder.execute(select(model.id).where(model.id == key).with_for_update())
        monkeypatch.setattr(retention_reads, "RETENTION_READ_TIMEOUT_SECONDS", 0.1)
        with pytest.raises(RetentionReadError, match="^retention_read_busy$"):
            await service(f, reader).get_schedule(f.principal, group_id=f.groups["active"])
        await reader.rollback()
        await holder.rollback()
        monkeypatch.setattr(retention_reads, "RETENTION_READ_TIMEOUT_SECONDS", 5)
        assert (await service(f, reader).get_schedule(f.principal, group_id=f.groups["active"]))[
            "completeness"
        ] == "complete"
        assert await snapshot(reader) == before


async def test_postgresql_shared_schedule_lock_blocks_writer_until_transaction_end(
    retention_postgres,
):
    f = retention_postgres
    async with f.sessions() as reader, f.sessions() as writer:
        original = await service(f, reader).get_schedule(f.principal, group_id=f.groups["closed"])
        await writer.execute(text("SET LOCAL lock_timeout = '100ms'"))
        statement = (
            update(ClientGroupModel)
            .where(ClientGroupModel.id == f.groups["closed"])
            .values(passport_purge_at=FUTURE)
        )
        with pytest.raises(DBAPIError) as blocked:
            await writer.execute(statement)
        assert getattr(blocked.value.orig, "sqlstate", None) == "55P03"
        await writer.rollback()
        await reader.rollback()
        await writer.execute(statement)
        assert (
            await writer.scalar(
                select(ClientGroupModel.passport_purge_at).where(
                    ClientGroupModel.id == f.groups["closed"]
                )
            )
            == FUTURE
        )
        await writer.rollback()
        assert (
            await service(f, reader).get_schedule(f.principal, group_id=f.groups["closed"])
        ) == original


async def test_postgresql_external_cancellation_leaves_rollback_retry_safe(retention_postgres):
    f, reached = retention_postgres, asyncio.Event()
    async with f.sessions() as holder, f.sessions() as reader:
        before = await snapshot(reader)
        await reader.rollback()
        await holder.execute(
            select(ClientGroupModel.id)
            .where(ClientGroupModel.id == f.groups["active"])
            .with_for_update()
        )

        def capture(_conn, _cursor, statement, _params, _context, _many):
            if "FROM client_groups" in statement and "FOR SHARE" in statement:
                reached.set()

        event.listen(f.engine.sync_engine, "before_cursor_execute", capture)
        task = asyncio.create_task(
            service(f, reader).get_schedule(f.principal, group_id=f.groups["active"])
        )
        try:
            await asyncio.wait_for(reached.wait(), 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            event.remove(f.engine.sync_engine, "before_cursor_execute", capture)
        await reader.rollback()
        await holder.rollback()
        assert (await service(f, reader).get_schedule(f.principal, group_id=f.groups["active"]))[
            "completeness"
        ] == "complete"
        assert await snapshot(reader) == before


async def test_postgresql_committed_revocation_wins_waiting_read_before_business_lookup(
    retention_postgres,
):
    f, reached, statements = retention_postgres, asyncio.Event(), []
    async with f.sessions() as session:
        actor, grants, _ = await seed_identity(
            session, f.settings, email=f"race-{uuid.uuid4()}@example.test"
        )
        grants[0].capabilities = ["mcp:read"]
        principal = MCPPrincipal(
            grants[0].id,
            actor.id,
            grants[0].client_id,
            ("mcp:read",),
            grants[0].expires_at,
            grants[0].resource,
        )
        await session.commit()
    async with f.sessions() as revoker, f.sessions() as reader:
        before = await snapshot(reader)
        await reader.rollback()
        await revoker.execute(
            update(MCPGrantModel)
            .where(MCPGrantModel.id == principal.grant_id)
            .values(revoked_at=datetime.now(UTC))
        )

        def capture(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement.lower())
            if "FROM mcp_grants" in statement and "FOR UPDATE" in statement:
                reached.set()

        event.listen(f.engine.sync_engine, "before_cursor_execute", capture)
        task = asyncio.create_task(
            service(f, reader).get_schedule(principal, group_id=f.groups["active"])
        )
        try:
            await asyncio.wait_for(reached.wait(), 3)
            await revoker.commit()
            with pytest.raises(MCPAuthError):
                await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            event.remove(f.engine.sync_engine, "before_cursor_execute", capture)
        assert not any("from client_groups" in item for item in statements)
        await reader.rollback()
        assert await snapshot(reader) == before
