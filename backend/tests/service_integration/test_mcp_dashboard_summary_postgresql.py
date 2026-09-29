"""Retained, isolated PostgreSQL dashboard read proof; not a load qualification."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import URL, event, func, insert, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.mcp import dashboard_reads
from app.application.mcp.dashboard_reads import MCPDashboardReadService
from app.application.use_cases.dashboard.get_dashboard_stats_use_case import (
    GetDashboardStatsUseCase,
)
from app.core.config.mcp import MCPSettings
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES
from app.domain.value_objects.dashboard_summary import DashboardProjectionLimitError
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportExportHistoryModel,
    PassportSubmissionModel,
    UserModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes.dashboard import get_dashboard_stats
from tests.postgresql_schema import create_isolated_postgresql_tables

pytestmark = [pytest.mark.service_integration, pytest.mark.skipif(
    os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required")]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def dashboard_postgres(test_settings, record_testsuite_property):
    host, database = os.environ.get("POSTGRES_HOST", "localhost"), os.environ["POSTGRES_DB"]
    if host not in {"127.0.0.1", "localhost"} or not database.startswith("passdetection_ci_"):
        pytest.fail("Dashboard proof requires a dedicated loopback CI database")
    schema = "manual_review_" + uuid.uuid4().hex
    record_testsuite_property("retained_dashboard_postgresql_schema", schema)
    engine = create_async_engine(URL.create("postgresql+asyncpg", username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"], host=host,
        port=int(os.environ.get("POSTGRES_PORT", "5432")), database=database), poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema, "statement_timeout": "15000", "lock_timeout": "5000"}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await create_isolated_postgresql_tables(connection, schema)
        async with sessions() as session:
            agency, other = [AgencyModel(id=uuid.uuid4(), name=name, email=f"{uuid.uuid4()}@example.test")
                             for name in ("Dashboard PG", "Other PG")]
            session.add_all([agency, other])
            await session.flush()
            actor, no_agency = [UserModel(id=uuid.uuid4(), agency_id=agency_id, role="super_admin",
                email=f"{uuid.uuid4()}@example.test", full_name="Synthetic dashboard", hashed_password="unused", is_active=True)
                for agency_id in (agency.id, None)]
            session.add_all([actor, no_agency])
            groups = {}
            for name in ("active", "closed", "archived", "deleted", "empty", "other"):
                group = ClientGroupModel(id=uuid.uuid4(), agency_id=other.id if name == "other" else agency.id,
                    name=name, token=uuid.uuid4().hex, status="active" if name in {"empty", "other"} else name,
                    return_date=datetime(2020, 1, 1).date() if name == "empty" else None,
                    deleted_at=datetime.now(UTC) if name == "deleted" else None)
                session.add(group)
                groups[name] = group
            await session.flush()
            rows, top_ids = [], []
            stamp = datetime(2026, 9, 1, tzinfo=UTC)
            for name in ("active", "closed", "archived", "deleted", "other"):
                for index, status in enumerate(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES):
                    identifier = uuid.UUID(f"aaaaaaaa-0000-0000-0000-{index:012x}") if name == "active" else uuid.uuid4()
                    if name == "active":
                        top_ids.append(identifier)
                    rows.append({"id": identifier, "agency_id": groups[name].agency_id,
                        "group_id": groups[name].id, "client_name": f"Synthetic {name} {index}",
                        "client_email": "synthetic@example.test", "image_s3_key": "private/never-read",
                        "status": status, "overall_confidence": 0.8,
                        "created_at": stamp if name == "active" else stamp-timedelta(days=1),
                        "extracted_fields": {"PRIVATE-JSON": "x" * (2 * 1024 * 1024) if name == "active" else "hidden"}})
            for index in range(150):
                rows.append({"id": uuid.uuid4(), "agency_id": agency.id, "group_id": groups["archived"].id,
                    "client_name": f"Historical {index}", "client_email": None, "image_s3_key": "private/never-read",
                    "status": "confirmed", "overall_confidence": None, "created_at": stamp, "extracted_fields": None})
            for status in ("uploaded", "pending_upload", "review_required", "failed", "ready_for_client_review"):
                rows.append({"id": uuid.uuid4(), "agency_id": agency.id, "group_id": groups["active"].id,
                    "client_name": "Not office visible", "client_email": None, "image_s3_key": "private/never-read",
                    "status": status, "overall_confidence": None, "created_at": stamp+timedelta(days=1), "extracted_fields": None})
            await session.execute(insert(PassportSubmissionModel), rows)
            await session.commit()
        settings = test_settings.model_copy(update={"mcp": MCPSettings(enabled=True,
            export_source_row_limit=100, export_source_byte_limit=1024 * 1024)})
        yield SimpleNamespace(engine=engine, sessions=sessions, schema=schema, settings=settings,
            actor=actor.id, no_agency=no_agency.id, agency=agency.id, top_ids=top_ids, total_rows=len(rows))
    finally:
        await engine.dispose()


def service(f, session):
    return MCPDashboardReadService(session, cursor_secret=f.settings.app_secret_key)


async def assert_no_effects(session, f):
    assert await session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == f.total_rows
    for model in (MCPOperationModel, MCPArtifactModel, PassportExportHistoryModel, WhatsAppMessageLogModel):
        assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_postgresql_counts_above_export_ceiling_fixed_preview_and_website_parity(dashboard_postgres):
    f = dashboard_postgres
    statements = []
    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement.lower())
    def forbidden(*_args):
        raise AssertionError("Dashboard loaded a full business ORM row")
    async with f.sessions() as session:
        event.listen(f.engine.sync_engine, "before_cursor_execute", capture)
        for model in (PassportSubmissionModel, ClientGroupModel):
            event.listen(model, "load", forbidden)
            event.listen(model, "refresh", forbidden)
        try:
            result = await service(f, session).get_summary(f.actor)
        finally:
            event.remove(f.engine.sync_engine, "before_cursor_execute", capture)
            for model in (PassportSubmissionModel, ClientGroupModel):
                event.remove(model, "load", forbidden)
                event.remove(model, "refresh", forbidden)
        assert (result["total_passports"], result["pending_review"], result["confirmed"], result["active_links"]) == (174, 6, 6, 2)
        assert len(statements) == 7 and not any(statement.lstrip().startswith(("insert", "update", "delete")) for statement in statements)
        preview = statements[-1].split("\nfrom")[0]
        assert "substr(" in preview and not any(name in preview for name in ("extracted_fields", "image_s3_key", "confirmed_fields"))
        assert "limit" in statements[-1] and "created_at desc" in statements[-1] and ".id desc" in statements[-1]
        assert [row["id"] for row in result["recent_submissions"]] == [str(item) for item in reversed(f.top_ids[1:])]
        assert result["consistency"]["snapshot_guaranteed"] is False
        actor = await UserRepository(session).get_by_id(f.actor)
        website = await get_dashboard_stats(actor, GetDashboardStatsUseCase(
            PassportSubmissionRepository(session), ClientGroupRepository(session)))
        expected = website.model_dump(mode="json")
        for row in expected["recent_submissions"]:
            row["created_at"] = row["created_at"].replace("Z", "+00:00")
        assert {key: result[key] for key in expected} == expected
        await assert_no_effects(session, f)


async def test_postgresql_no_agency_uses_only_identity_queries(dashboard_postgres):
    f = dashboard_postgres
    statements = []
    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement.lower())
    async with f.sessions() as session:
        event.listen(f.engine.sync_engine, "before_cursor_execute", capture)
        try:
            result = await service(f, session).get_summary(f.no_agency)
        finally:
            event.remove(f.engine.sync_engine, "before_cursor_execute", capture)
        assert len(statements) == 2 and not any("passport_submissions" in statement or "client_groups" in statement for statement in statements)
        assert result["agency_id"] is None and result["total_passports"] == 0 and result["recent_submissions"] == []


async def test_postgresql_unicode_maximum_fields_are_complete_and_bounded(dashboard_postgres):
    f = dashboard_postgres
    async with f.sessions() as session:
        await session.execute(update(PassportSubmissionModel).where(PassportSubmissionModel.id.in_(f.top_ids)).values(
            client_name="界" * 255, client_email="😀" * 255))
        result = await service(f, session).get_summary(f.actor)
        assert len(result["recent_submissions"]) == 5
        assert all(row["client_name"] == "界" * 255 and row["client_email"] == "😀" * 255 for row in result["recent_submissions"])
        await session.rollback()


async def test_postgresql_nonfinite_confidence_returns_no_partial_summary(dashboard_postgres):
    f = dashboard_postgres
    async with f.sessions() as session:
        await session.execute(update(PassportSubmissionModel).where(PassportSubmissionModel.id == f.top_ids[-1]).values(overall_confidence=float("nan")))
        with pytest.raises(DashboardProjectionLimitError):
            await service(f, session).get_summary(f.actor)
        await session.rollback()
        assert (await service(f, session).get_summary(f.actor))["confirmed"] == 6


async def test_postgresql_blocked_read_deadline_cancels_and_retry_remains_safe(dashboard_postgres, monkeypatch):
    f = dashboard_postgres
    async with f.sessions() as holder, f.sessions() as reader:
        # Only the new retained schema's source table is locked. No global
        # setting, application table, business row or control state is changed.
        await holder.execute(text(f'LOCK TABLE "{f.schema}".passport_submissions IN ACCESS EXCLUSIVE MODE'))
        await reader.execute(text("SELECT 1"))
        monkeypatch.setattr(dashboard_reads, "DASHBOARD_READ_TIMEOUT_SECONDS", 0.1)
        began = time.monotonic()
        with pytest.raises(TimeoutError):
            await service(f, reader).get_summary(f.actor)
        assert time.monotonic()-began < 3
        await reader.rollback()
        await holder.rollback()
        monkeypatch.setattr(dashboard_reads, "DASHBOARD_READ_TIMEOUT_SECONDS", 10)
        result = await asyncio.wait_for(service(f, reader).get_summary(f.actor), 3)
        assert result["total_passports"] == 174
        await assert_no_effects(reader, f)
