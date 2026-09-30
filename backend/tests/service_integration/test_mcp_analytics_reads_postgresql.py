"""Retained PostgreSQL scalar analytics parity; not production/load qualification."""

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
from sqlalchemy import URL, event, func, insert, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.mcp import analytics_reads
from app.application.mcp.analytics_reads import AnalyticsReadError, MCPPassportAnalyticsReadService
from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.credentials import MCPAuthError
from app.application.use_cases.passports import passport_analytics
from app.core.config.mcp import MCPSettings
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES, UserRole
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
from app.presentation.api.v1.routes.analytics import get_analytics_summary
from tests.integration.test_mcp_operations import seed_identity
from tests.postgresql_schema import create_isolated_postgresql_tables

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"
    ),
]
NOW = datetime(2026, 9, 30, 20, 30, tzinfo=UTC)
FIELDS = ("status_counts", "confidence_buckets", "submissions_by_day", "average_confidence")
CONFIDENCES = (0.9, 0.899, 0.8995, 0.75, 0.749, None, -0.2, 1.2)


class FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


def passport(f, *, stamp=NOW, confidence=0.8, status="confirmed", group=None):
    group_id, agency_id = group or f.groups[0]
    return dict(
        id=uuid.uuid4(),
        agency_id=agency_id,
        group_id=group_id,
        client_name="PRIVATE synthetic passport",
        client_email="private@example.test",
        image_s3_key="PRIVATE/storage/never-read",
        status=status,
        overall_confidence=confidence,
        created_at=stamp,
        extracted_fields={"PRIVATE": "not projected"},
    )


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def analytics_postgres(test_settings, record_testsuite_property):
    host, database = os.environ.get("POSTGRES_HOST", "localhost"), os.environ["POSTGRES_DB"]
    if host not in {"127.0.0.1", "localhost"} or not database.startswith("passdetection_ci_"):
        pytest.fail("Analytics proof requires the dedicated loopback CI database")
    schema = "manual_review_" + uuid.uuid4().hex
    record_testsuite_property("retained_analytics_postgresql_schema", schema)
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
                    name="Synthetic analytics",
                    email=f"{uuid.uuid4()}@example.test",
                    is_active=active,
                )
                for active in (True, False)
            ]
            session.add_all(agencies)
            await session.flush()
            groups = [
                ClientGroupModel(
                    id=uuid.uuid4(),
                    agency_id=agency.id,
                    name="Retained analytics",
                    token=uuid.uuid4().hex,
                    status="active" if index == 0 else "deleted",
                    deleted_at=None if index == 0 else datetime.now(UTC),
                )
                for index, agency in enumerate(agencies)
            ]
            session.add_all(groups)
            await session.flush()
            f = SimpleNamespace(
                engine=engine,
                sessions=sessions,
                settings=settings,
                schema=schema,
                actor=actor.id,
                groups=[(group.id, group.agency_id) for group in groups],
            )
            rows = []
            for index, confidence in enumerate(CONFIDENCES):
                stamp = (
                    NOW - timedelta(days=30)
                    if index == 0
                    else NOW + timedelta(days=400)
                    if index == 7
                    else NOW
                )
                row = passport(
                    f,
                    stamp=stamp,
                    confidence=confidence,
                    status=OFFICE_VISIBLE_PASSPORT_STATUS_VALUES[index % 6],
                    group=f.groups[index % 2],
                )
                if index == 0:
                    row["extracted_fields"] = {"PRIVATE": "界" * (1024 * 1024)}
                rows.append(row)
            f.edge_id = rows[0]["id"]
            rows += [passport(f, stamp=NOW - timedelta(days=30, microseconds=1), confidence=999.0)]
            rows += [
                passport(f, status=status)
                for status in (
                    "uploaded",
                    "pending_upload",
                    "review_required",
                    "failed",
                    "ready_for_client_review",
                )
            ]
            await session.execute(insert(PassportSubmissionModel), rows)
            await session.commit()
            grant = grants[0]
            f.principal = MCPPrincipal(
                grant.id, actor.id, grant.client_id, ("mcp:read",), grant.expires_at, grant.resource
            )
        yield f
    finally:
        await engine.dispose()  # All schema/rows retained; no public table access.


@pytest.fixture(autouse=True)
def freeze_clock_and_forbid_external_io(monkeypatch):
    monkeypatch.setattr(passport_analytics, "datetime", FixedClock)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Analytics cannot contact a provider or storage")

    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(MinioStorageRepository, "__init__", forbidden)


def service(f, session, settings=None):
    return MCPPassportAnalyticsReadService(session, settings or f.settings)


async def snapshot(f, session):
    hashes = (
        await session.execute(
            text(
                f'SELECT id, md5(row_to_json(t)::text) FROM "{f.schema}".passport_submissions t ORDER BY id'
            )
        )
    ).all()
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


async def test_postgresql_canonical_global_scope_gap_average_lower_only_and_retention(
    analytics_postgres,
):
    f = analytics_postgres
    async with f.sessions() as session:
        before = await snapshot(f, session)
        for agency in (None, f.groups[0][1], f.groups[1][1]):
            await session.execute(
                update(UserModel).where(UserModel.id == f.actor).values(agency_id=agency)
            )
            actor = await UserRepository(session).get_by_id(f.actor)
            web = await get_analytics_summary(actor, session, days=30)
            result = await service(f, session).summary(f.principal)
            assert {field: result[field] for field in FIELDS} == web.model_dump()
            assert (
                sum(result["status_counts"].values())
                == sum(result["submissions_by_day"].values())
                == 8
            )
            assert result["confidence_buckets"] == {"high": 2, "medium": 2, "low": 2, "missing": 1}
            assert result["average_confidence"] == round(
                sum(v for v in CONFIDENCES if v is not None) / 7, 3
            )
            assert (
                result["window_start"] == (NOW - timedelta(days=30)).isoformat()
                and result["window_end"] is None
            )
            assert result["agency_scope"] == "all_agencies" and "PRIVATE" not in json.dumps(result)
            assert result["consistency"]["atomic_snapshot_guaranteed"] is False
        actor.role, actor.agency_id = UserRole.AGENCY_ADMIN, f.groups[0][1]
        assert sum((await get_analytics_summary(actor, session)).status_counts.values()) == 4
        actor.agency_id = None
        assert (await get_analytics_summary(actor, session)).model_dump() == dict(
            status_counts={}, confidence_buckets={}, submissions_by_day={}, average_confidence=None
        )
        assert await snapshot(f, session) == before
        await session.rollback()


@pytest.mark.parametrize("days,expected", [(0, 1), (-100, 1), (1, 1), (365, 365), (999, 365)])
async def test_postgresql_website_days_clamp_and_future_date_stays_visible(
    analytics_postgres, days, expected
):
    f = analytics_postgres
    async with f.sessions() as session:
        actor = await UserRepository(session).get_by_id(f.actor)
        web = await get_analytics_summary(actor, session, days)
        result = await service(f, session).summary(f.principal, days=days)
        assert {field: result[field] for field in FIELDS} == web.model_dump()
        assert result["days"] == expected
        assert str((NOW + timedelta(days=400)).date()) in result["submissions_by_day"]


@pytest.mark.parametrize(
    "zone,day",
    [("UTC", "2026-09-30"), ("Asia/Kolkata", "2026-10-01"), ("America/Los_Angeles", "2026-09-30")],
)
async def test_postgresql_date_cast_uses_session_timezone_not_python_utc(
    analytics_postgres, zone, day
):
    f = analytics_postgres
    async with f.sessions() as session:
        await session.execute(text("SELECT set_config('TimeZone', :zone, true)"), {"zone": zone})
        result = await service(f, session).summary(f.principal)
        assert result["submissions_by_day"][day] == 6
        assert result["window_start"] == (NOW - timedelta(days=30)).isoformat()


async def test_postgresql_only_three_scalar_queries_no_private_hydration_or_effects(
    analytics_postgres,
):
    f, statements = analytics_postgres, []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement.lower())

    def forbidden(*_args):
        raise AssertionError("Analytics hydrated a passport/group ORM row")

    async with f.sessions() as session:
        before = await snapshot(f, session)
        event.listen(f.engine.sync_engine, "before_cursor_execute", capture)
        for model in (PassportSubmissionModel, ClientGroupModel):
            event.listen(model, "load", forbidden)
            event.listen(model, "refresh", forbidden)
        try:
            await service(f, session).summary(f.principal)
        finally:
            event.remove(f.engine.sync_engine, "before_cursor_execute", capture)
            for model in (PassportSubmissionModel, ClientGroupModel):
                event.remove(model, "load", forbidden)
                event.remove(model, "refresh", forbidden)
        business = [s for s in statements if "from passport_submissions" in s]
        assert len(business) == 3 and len(statements) == 7
        assert all("count(" in s or "sum(" in s for s in business)
        assert not any(
            private in "\n".join(business)
            for private in (
                "client_name",
                "client_email",
                "image_s3_key",
                "extracted_fields",
                "join client_groups",
            )
        )
        assert (
            "limit" in business[-1]
            and "cast(passport_submissions.created_at as date)" in business[-1]
        )
        assert not any(s.lstrip().startswith(("insert", "update", "delete")) for s in statements)
        assert await snapshot(f, session) == before


async def test_postgresql_actual_366_then_367_distinct_future_days_fail_closed(analytics_postgres):
    f = analytics_postgres
    async with f.sessions() as session:
        await session.execute(
            update(PassportSubmissionModel).values(created_at=NOW - timedelta(days=500))
        )
        await session.execute(
            insert(PassportSubmissionModel),
            [passport(f, stamp=NOW + timedelta(days=i)) for i in range(366)],
        )
        result = await service(f, session).summary(f.principal)
        assert (
            len(result["submissions_by_day"]) == 366
            and sum(result["status_counts"].values()) == 366
        )
        await session.execute(
            insert(PassportSubmissionModel), [passport(f, stamp=NOW + timedelta(days=366))]
        )
        with pytest.raises(AnalyticsReadError, match="analytics_read_limit"):
            await service(f, session).summary(f.principal)
        actor = await UserRepository(session).get_by_id(f.actor)
        assert len((await get_analytics_summary(actor, session)).submissions_by_day) == 367
        await session.rollback()


@pytest.mark.parametrize("confidence", [float("nan"), float("inf"), float("-inf")])
async def test_postgresql_nonfinite_stored_average_is_static_limit_error(
    analytics_postgres, confidence
):
    f = analytics_postgres
    async with f.sessions() as session:
        await session.execute(insert(PassportSubmissionModel), [passport(f, confidence=confidence)])
        with pytest.raises(AnalyticsReadError, match="analytics_read_limit") as denied:
            await service(f, session).summary(f.principal)
        assert str(denied.value) == "analytics_read_limit"
        await session.rollback()


async def test_postgresql_empty_source_and_complete_unicode_envelope_budget(analytics_postgres):
    f = analytics_postgres
    async with f.sessions() as session:
        settings = f.settings.model_copy(update={"app_revision": "界" * 12000})
        with pytest.raises(AnalyticsReadError, match="analytics_read_limit"):
            await service(f, session, settings).summary(f.principal)
        await session.execute(
            update(PassportSubmissionModel).values(created_at=NOW - timedelta(days=500))
        )
        result = await service(f, session).summary(f.principal)
        assert {field: result[field] for field in FIELDS} == dict(
            status_counts={},
            confidence_buckets={"high": 0, "medium": 0, "low": 0, "missing": 0},
            submissions_by_day={},
            average_confidence=None,
        )
        await session.rollback()


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
async def test_postgresql_live_authority_before_any_global_analytics_query(
    analytics_postgres, change
):
    f, now = analytics_postgres, datetime.now(UTC)
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
                "role": {"role": "agency_staff"},
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

        def capture(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement.lower())

        event.listen(f.engine.sync_engine, "before_cursor_execute", capture)
        try:
            with pytest.raises(MCPAuthError):
                await service(f, session).summary(principal)
        finally:
            event.remove(f.engine.sync_engine, "before_cursor_execute", capture)
        assert not any("from passport_submissions" in s for s in statements)
        await session.rollback()
        assert (await service(f, session).summary(f.principal))["completeness"] == "complete"


@pytest.mark.parametrize("lock", ["source", "grant"])
async def test_postgresql_real_sql_deadline_rollback_then_retry(
    analytics_postgres, monkeypatch, lock
):
    f = analytics_postgres
    async with f.sessions() as holder, f.sessions() as reader:
        before = await snapshot(f, reader)
        await reader.rollback()
        if lock == "source":
            await holder.execute(text("LOCK TABLE passport_submissions IN ACCESS EXCLUSIVE MODE"))
        else:
            await holder.execute(
                select(MCPGrantModel.id)
                .where(MCPGrantModel.id == f.principal.grant_id)
                .with_for_update()
            )
        monkeypatch.setattr(analytics_reads, "READ_TIMEOUT_SECONDS", 0.15)
        with pytest.raises(AnalyticsReadError, match="analytics_read_busy"):
            await service(f, reader).summary(f.principal)
        await reader.rollback()
        await holder.rollback()
        monkeypatch.setattr(analytics_reads, "READ_TIMEOUT_SECONDS", 5)
        assert (await asyncio.wait_for(service(f, reader).summary(f.principal), 3))[
            "completeness"
        ] == "complete"
        assert await snapshot(f, reader) == before


async def test_postgresql_identity_lock_and_cancelled_wait_release_without_effects(
    analytics_postgres,
):
    f = analytics_postgres
    async with f.sessions() as reader, f.sessions() as writer:
        await service(f, reader).summary(f.principal)
        await writer.execute(text("SET LOCAL lock_timeout = '100ms'"))
        with pytest.raises(DBAPIError) as denied:
            await writer.execute(
                update(UserModel).where(UserModel.id == f.actor).values(is_active=False)
            )
        assert getattr(denied.value.orig, "sqlstate", None) == "55P03"
        await writer.rollback()
        await reader.rollback()
        before = await snapshot(f, reader)
        await reader.rollback()
        await writer.execute(select(UserModel.id).where(UserModel.id == f.actor).with_for_update())
        waiting = asyncio.Event()

        def capture(_conn, _cursor, statement, _params, _context, _many):
            if "FOR SHARE OF users" in statement:
                waiting.set()

        event.listen(f.engine.sync_engine, "before_cursor_execute", capture)
        task = asyncio.create_task(service(f, reader).summary(f.principal))
        try:
            await asyncio.wait_for(waiting.wait(), 3)
            assert not task.done()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await reader.rollback()
            await writer.rollback()
            assert (await service(f, reader).summary(f.principal))["completeness"] == "complete"
            assert await snapshot(f, reader) == before
        finally:
            event.remove(f.engine.sync_engine, "before_cursor_execute", capture)
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
