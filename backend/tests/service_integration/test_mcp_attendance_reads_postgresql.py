"""Retained synthetic PostgreSQL attendance read proof; no runtime/capacity claim."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import Request, Response
from sqlalchemy import URL, event, func, insert, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.mcp import attendance_reads
from app.application.mcp.attendance_reads import AttendanceReadError, MCPAttendanceReadService
from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.credentials import MCPAuthError
from app.core.config.mcp import MCPSettings
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AgencyModel,
    AttendanceCloseoutCheckpointModel,
    AttendanceRecordModel,
    AttendanceRuntimeRegistrationModel,
    AttendanceSessionModel,
    AttendanceSessionRuntimeParticipantModel,
    AuditLogModel,
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
    PassportExportHistoryModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.repositories import attendance_closeout_repository
from app.infrastructure.repositories.attendance_dashboard_repository import (
    AttendanceDashboardRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes.tour_operations_attendance_dashboard import (
    get_group_attendance_missing_passengers,
    get_group_attendance_summary,
)
from tests.integration.test_mcp_operations import seed_identity
from tests.postgresql_schema import create_isolated_postgresql_tables

pytestmark = [pytest.mark.service_integration, pytest.mark.skipif(
    os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required")]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def attendance_postgres(test_settings, record_testsuite_property):
    host, database = os.environ.get("POSTGRES_HOST", "localhost"), os.environ["POSTGRES_DB"]
    if host not in {"127.0.0.1", "localhost"} or not database.startswith("passdetection_ci_"):
        pytest.fail("Attendance proof requires the dedicated loopback CI database")
    schema = "manual_review_" + uuid.uuid4().hex
    record_testsuite_property("retained_attendance_postgresql_schema", schema)
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
            await session.commit()
        yield SimpleNamespace(engine=engine, sessions=sessions, settings=settings, schema=schema)
    finally:
        await engine.dispose()  # Retain UUID schema and every committed fixture.


def activity(f, *, group=None, **changes):
    identifier = uuid.uuid4()
    return dict(id=identifier, canonical_session_id=identifier, agency_id=f.agency,
        group_id=group or f.group, name="Synthetic " + identifier.hex, normalized_name=identifier.hex,
        status="active", created_by_user_id=f.actor, created_at=f.stamp, updated_at=f.stamp,
        started_at=f.stamp) | changes


@pytest_asyncio.fixture
async def attendance_cohort(attendance_postgres):
    f, now = attendance_postgres, datetime.now(UTC)
    async with f.sessions() as session:
        actor, grants, _ = await seed_identity(session, f.settings, email=f"{uuid.uuid4()}@example.test")
        agencies = [AgencyModel(id=uuid.uuid4(), name="Synthetic attendance", email=f"{uuid.uuid4()}@example.test") for _ in range(2)]
        session.add_all(agencies)
        await session.flush()
        actor.agency_id, grants[0].capabilities = agencies[0].id, ["mcp:read"]
        groups = [ClientGroupModel(id=uuid.uuid4(), agency_id=agencies[int(index == 2)].id,
            name="Synthetic group", token=uuid.uuid4().hex, status="active", created_by_user_id=actor.id) for index in range(3)]
        coordinators = [UserModel(id=uuid.uuid4(), agency_id=agencies[0].id, email=f"{uuid.uuid4()}@example.test",
            full_name="Synthetic coordinator", hashed_password="unused", role="agency_coordinator", is_active=True) for _ in range(2)]
        session.add_all([*groups, *coordinators])
        await session.flush()
        data = SimpleNamespace(**vars(f), actor=actor.id, agency=agencies[0].id, foreign_agency=agencies[1].id,
            group=groups[0].id, empty_group=groups[1].id, foreign_group=groups[2].id,
            coordinators=[row.id for row in coordinators], stamp=now - timedelta(hours=1))
        canonical = activity(data)
        await session.execute(insert(AttendanceSessionModel), [canonical])
        alias = activity(data, canonical_session_id=canonical["id"])
        await session.execute(insert(AttendanceSessionModel), [alias])
        passengers = [dict(id=uuid.uuid4(), agency_id=data.agency, group_id=data.group,
            client_name="50%_off\\name" if index == 3 else f"Synthetic person {index}",
            client_email="PRIVATE@example.test", image_s3_key="PRIVATE-OBJECT",
            extracted_fields={"PRIVATE-JSON": "x" * 10000}, status=state, created_at=now, updated_at=now)
            for index, state in enumerate(("confirmed", "client_submitted", "ai_approved", "staff_approved", "confirmed", "confirmed", "needs_review"))]
        await session.execute(insert(PassportSubmissionModel), passengers)
        await session.execute(insert(CoordinatorGroupAssignmentModel), [dict(id=uuid.uuid4(), agency_id=data.agency,
            group_id=data.group, coordinator_user_id=row.id, active=True, assigned_at=data.stamp - timedelta(hours=1)) for row in coordinators])
        await session.execute(insert(AttendanceRecordModel), [dict(id=uuid.uuid4(), agency_id=data.agency,
            session_id=sid, passenger_id=pid, coordinator_user_id=coordinators[index % 2].id,
            scanned_at=now + timedelta(seconds=index), sync_source="online", client_event_id=uuid.uuid4().hex,
            device_id="PRIVATE-DEVICE", created_at=now) for index, (sid, pid) in enumerate([
                (canonical["id"], passengers[0]["id"]), (alias["id"], passengers[0]["id"]), (alias["id"], passengers[1]["id"])])])
        runtime = AttendanceRuntimeRegistrationModel(id=uuid.uuid4(), agency_id=data.agency,
            coordinator_user_id=coordinators[0].id, runtime_kind="pwa", runtime_identifier_hash="a" * 64,
            status="active", registered_at=data.stamp, expires_at=now + timedelta(days=1))
        session.add(runtime)
        await session.flush()
        session.add(AttendanceCloseoutCheckpointModel(id=uuid.uuid4(), agency_id=data.agency,
            session_id=canonical["id"], coordinator_user_id=coordinators[0].id, runtime_registration_id=runtime.id,
            pending_count=0, sending_count=0, retryable_count=0, needs_review_count=0,
            unreviewed_rejected_count=0, oldest_pending_age_seconds=None, reported_at=now))
        await session.commit()
        grant = grants[0]
        data.principal = MCPPrincipal(grant.id, actor.id, grant.client_id, ("mcp:read",), grant.expires_at, grant.resource)
        data.activity, data.alias = canonical["id"], alias["id"]
        data.passengers, data.runtime = [row["id"] for row in passengers], runtime.id
    return data


def service(f, session):
    return MCPAttendanceReadService(session, f.settings)


async def summary(f, session):
    return await service(f, session).summary(f.principal, group_id=f.group)


async def missing(f, session, revision, **changes):
    return await service(f, session).missing(f.principal, **(dict(group_id=f.group,
        session_id=f.activity, snapshot_revision=revision, page_size=2) | changes))


@contextmanager
def scalar_sources(engine):
    statements = []
    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement.lower())
    def forbidden(*_args):
        raise AssertionError("Attendance read hydrated a private business ORM row")
    models = (AttendanceSessionModel, AttendanceCloseoutCheckpointModel, AttendanceRuntimeRegistrationModel,
              AttendanceRecordModel, PassportSubmissionModel, ClientGroupModel)
    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    for model in models:
        event.listen(model, "load", forbidden)
        event.listen(model, "refresh", forbidden)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
        for model in models:
            event.remove(model, "load", forbidden)
            event.remove(model, "refresh", forbidden)


async def snapshot(session):
    models = (AttendanceSessionModel, AttendanceRecordModel, AttendanceCloseoutCheckpointModel,
              AttendanceRuntimeRegistrationModel, AttendanceSessionRuntimeParticipantModel,
              CoordinatorGroupAssignmentModel, PassportSubmissionModel)
    rows = [(await session.execute(select(*model.__table__.columns).order_by(model.id))).all() for model in models]
    counts = [await session.scalar(select(func.count()).select_from(model)) for model in (
        AuditLogModel, MCPArtifactModel, MCPOperationModel, PassportExportHistoryModel)]
    return rows, counts


async def test_postgresql_website_parity_canonical_alias_and_no_business_effects(attendance_cohort):
    f = attendance_cohort
    async with f.sessions() as session:
        before = await snapshot(session)
        with scalar_sources(f.engine) as statements:
            actual = await summary(f, session)
            revision = actual["sessions"][0]["revision"]
            page = await missing(f, session, revision)
        assert len(actual["sessions"]) == 1
        assert actual["sessions"][0]["present_count"] == 2 and actual["sessions"][0]["missing_count"] == 4
        assert actual["snapshot_revision"] != revision
        assert all("PRIVATE" not in json.dumps(value) for value in (actual, page))
        assert not any(query.lstrip().startswith(("insert", "update", "delete")) for query in statements)
        source_sql = "\n".join(query for query in statements if "from attendance_" in query or "from passport_" in query)
        for private in ("runtime_identifier_hash", "native_mobile_session_id", "device_id", "image_s3_key", "extracted_fields", "client_email"):
            assert private not in source_sql
        assert await snapshot(session) == before
        actor = await UserRepository(session).get_by_id(f.actor)
        request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""})
        web = await get_group_attendance_summary(f.group, request, Response(), actor, session)
        expected = web.model_dump(mode="json")
        normalized = json.loads(json.dumps(expected).replace("Z\"", "+00:00\""))
        assert actual["sessions"] == normalized["sessions"] and actual["snapshot_revision"] == expected["revision"]
        web_page = await get_group_attendance_missing_passengers(f.group, f.activity, revision, None, 2, None, actor, session)
        assert page["items"] == web_page.model_dump(mode="json")["items"]
        assert page["has_more"] and page["completeness"] == "partial"


async def test_postgresql_missing_all_pages_search_and_empty_activity_group(attendance_cohort):
    f = attendance_cohort
    async with f.sessions() as session:
        revision = (await summary(f, session))["sessions"][0]["revision"]
        first = await missing(f, session, revision)
        second = await missing(f, session, revision, cursor=first["next_cursor"])
        ids = [row["passenger_id"] for row in first["items"] + second["items"]]
        assert ids == sorted(map(str, f.passengers[2:6])) and len(set(ids)) == 4
        assert not second["has_more"] and second["next_cursor"] is None and second["completeness"] == "complete"
        filtered = await missing(f, session, revision, search="  50%_off\\name  ")
        assert [row["passenger_id"] for row in filtered["items"]] == [str(f.passengers[3])]
        empty = await service(f, session).summary(f.principal, group_id=f.empty_group)
        assert empty["sessions"] == [] and empty["completeness"] == "complete"
        with pytest.raises(AttendanceReadError, match="attendance_activity_unavailable"):
            await missing(f, session, revision, session_id=f.alias)


async def test_postgresql_empty_roster_activity_retains_its_update_timestamp(attendance_cohort):
    f = attendance_cohort
    async with f.sessions() as session:
        empty = activity(f, group=f.empty_group)
        await session.execute(insert(AttendanceSessionModel), [empty])
        result = await service(f, session).summary(f.principal, group_id=f.empty_group)
        row = result["sessions"][0]
        assert row["present_count"] == row["missing_count"] == 0
        assert row["last_canonical_update_at"] == f.stamp.isoformat()
        assert row["coordinators"] == [] and row["closeout"]["ready"] is False
        page = await service(f, session).missing(f.principal, group_id=f.empty_group,
            session_id=empty["id"], snapshot_revision=row["revision"])
        assert page["items"] == [] and page["next_cursor"] is None and page["completeness"] == "complete"
        await session.rollback()


async def test_postgresql_committed_scan_conflicts_then_refreshes(attendance_cohort):
    f = attendance_cohort
    async with f.sessions() as session:
        revision = (await summary(f, session))["sessions"][0]["revision"]
        first = await missing(f, session, revision)
        await session.rollback()
        async with f.sessions() as writer:
            await writer.execute(insert(AttendanceRecordModel), [dict(id=uuid.uuid4(), agency_id=f.agency,
                session_id=f.activity, passenger_id=f.passengers[2], coordinator_user_id=f.coordinators[0],
                scanned_at=datetime.now(UTC), sync_source="online", client_event_id=uuid.uuid4().hex)])
            await writer.commit()
        with pytest.raises(AttendanceReadError, match="attendance_snapshot_changed"):
            await missing(f, session, revision, cursor=first["next_cursor"])
        revised = (await summary(f, session))["sessions"][0]
        assert revised["revision"] != revision and revised["present_count"] == 3
        assert (await missing(f, session, revised["revision"], page_size=10))["has_more"] is False


async def test_postgresql_scan_committing_between_revision_checks_rejects_page(attendance_cohort, monkeypatch):
    f = attendance_cohort
    original = AttendanceDashboardRepository.missing_passengers
    async def racing(repository, **kwargs):
        result = await original(repository, **kwargs)
        async with f.sessions() as writer:
            await writer.execute(insert(AttendanceRecordModel), [dict(id=uuid.uuid4(), agency_id=f.agency,
                session_id=f.activity, passenger_id=f.passengers[3], coordinator_user_id=f.coordinators[0],
                scanned_at=datetime.now(UTC), sync_source="online", client_event_id=uuid.uuid4().hex)])
            await writer.commit()
        return result
    async with f.sessions() as session:
        revision = (await summary(f, session))["sessions"][0]["revision"]
        monkeypatch.setattr(AttendanceDashboardRepository, "missing_passengers", racing)
        with pytest.raises(AttendanceReadError, match="attendance_snapshot_changed"):
            await missing(f, session, revision)


@pytest.mark.parametrize("change", ["revoked", "capability", "inactive", "role", "no_agency", "wrong_actor", "foreign_group", "deleted_group"])
async def test_postgresql_current_authority_scope_and_lifecycle(attendance_cohort, change):
    f = attendance_cohort
    async with f.sessions() as session:
        principal, group = f.principal, f.group
        if change in {"revoked", "capability"}:
            values = {"revoked_at": datetime.now(UTC)} if change == "revoked" else {"capabilities": []}
            await session.execute(update(MCPGrantModel).where(MCPGrantModel.id == principal.grant_id).values(**values))
        elif change in {"inactive", "role", "no_agency"}:
            values = {"inactive": {"is_active": False}, "role": {"role": "agency_staff"}, "no_agency": {"agency_id": None}}[change]
            await session.execute(update(UserModel).where(UserModel.id == f.actor).values(**values))
        elif change == "wrong_actor":
            principal = replace(principal, user_id=f.coordinators[0])
        elif change == "foreign_group":
            group = f.foreign_group
        else:
            await session.execute(update(ClientGroupModel).where(ClientGroupModel.id == f.group).values(status="deleted"))
        with scalar_sources(f.engine) as statements, pytest.raises((MCPAuthError, AttendanceReadError)):
            await service(f, session).summary(principal, group_id=group)
        assert not any("from attendance_" in query for query in statements)
        await session.rollback()
        assert len((await summary(f, session))["sessions"]) == 1


@pytest.mark.parametrize("binding", ["page", "search", "revision", "session", "group", "signature"])
async def test_postgresql_missing_cursor_query_bindings(attendance_cohort, binding):
    f = attendance_cohort
    async with f.sessions() as session:
        revision = (await summary(f, session))["sessions"][0]["revision"]
        first = await missing(f, session, revision)
        changes = {"page": {"page_size": 3}, "search": {"search": "name"}, "revision": {"snapshot_revision": "f" * 32},
            "session": {"session_id": f.alias}, "group": {"group_id": f.empty_group},
            "signature": {"cursor": first["next_cursor"] + "x"}}[binding]
        with pytest.raises(AttendanceReadError, match="attendance_invalid_query"):
            await missing(f, session, revision, **({"cursor": first["next_cursor"]} | changes))


async def test_postgresql_cursor_rejects_another_current_grant_actor(attendance_cohort):
    f = attendance_cohort
    async with f.sessions() as session:
        revision = (await summary(f, session))["sessions"][0]["revision"]
        first = await missing(f, session, revision)
        actor, grants, _ = await seed_identity(session, f.settings, email=f"{uuid.uuid4()}@example.test")
        actor.agency_id, grants[0].capabilities = f.agency, ["mcp:read"]
        await session.flush()
        grant = grants[0]
        principal = MCPPrincipal(grant.id, actor.id, grant.client_id, ("mcp:read",), grant.expires_at, grant.resource)
        with pytest.raises(AttendanceReadError, match="attendance_invalid_query"):
            await service(f, session).missing(principal, group_id=f.group, session_id=f.activity,
                snapshot_revision=revision, page_size=2, cursor=first["next_cursor"])
        await session.rollback()


async def test_postgresql_retained_scan_and_current_roster_counts_remain_distinct(attendance_cohort):
    f = attendance_cohort
    async with f.sessions() as session:
        session.add(PassportRosterResolutionModel(id=uuid.uuid4(), agency_id=f.agency,
            client_group_id=f.group, submission_id=f.passengers[0], resolution_type="rejected",
            status="active", resolved_by_user_id=f.actor))
        await session.flush()
        result = await summary(f, session)
        row = result["sessions"][0]
        assert row["present_count"] == 2 and row["missing_count"] == 3
        current = await missing(f, session, row["revision"], page_size=10)
        assert len(current["items"]) == 4
        assert result["count_semantics"] and current["count_semantics"]
        assert await session.scalar(select(func.count()).select_from(AttendanceRecordModel).where(
            AttendanceRecordModel.session_id.in_([f.activity, f.alias]))) == 3
        await session.rollback()


async def add_coordinators(session, f, group, count, *, name="Synthetic coordinator"):
    ids = [uuid.uuid4() for _ in range(count)]
    await session.execute(insert(UserModel), [dict(id=identifier, agency_id=f.agency, email=f"{identifier}@example.test",
        full_name=name, hashed_password="unused", role="agency_coordinator", is_active=True) for identifier in ids])
    await session.execute(insert(CoordinatorGroupAssignmentModel), [dict(id=uuid.uuid4(), agency_id=f.agency,
        group_id=group, coordinator_user_id=identifier, active=True, assigned_at=f.stamp) for identifier in ids])


async def test_postgresql_actual_100_101_activity_admission_without_full_orm(attendance_cohort):
    f = attendance_cohort
    async with f.sessions() as session:
        await session.execute(insert(AttendanceSessionModel), [activity(f, group=f.empty_group) for _ in range(100)])
        with scalar_sources(f.engine):
            accepted = await service(f, session).summary(f.principal, group_id=f.empty_group)
        assert len(accepted["sessions"]) == 100 and accepted["maximum_activities"] == 100
        await session.execute(insert(AttendanceSessionModel), [activity(f, group=f.empty_group)])
        with scalar_sources(f.engine) as statements, pytest.raises(AttendanceReadError, match="attendance_read_limit"):
            await service(f, session).summary(f.principal, group_id=f.empty_group)
        assert not any("from coordinator_group_assignments" in query for query in statements)
        await session.rollback()


async def test_postgresql_actual_5000_5001_source_bound_precedes_classification(attendance_cohort, monkeypatch):
    f = attendance_cohort
    async with f.sessions() as session:
        await session.execute(insert(AttendanceSessionModel), [activity(f, group=f.empty_group)])
        await add_coordinators(session, f, f.empty_group, 5000)
        allowed = await service(f, session).summary(f.principal, group_id=f.empty_group)
        assert allowed["completeness"] == "partial" and allowed["sessions"][0]["coordinator_count"] == 5000
        assert len(allowed["sessions"][0]["coordinators"]) == 25
        await add_coordinators(session, f, f.empty_group, 1)
        def forbidden(*_args, **_kwargs):
            raise AssertionError("Over-budget rows reached Python closeout classification")
        monkeypatch.setattr(attendance_closeout_repository, "classify_attendance_closeout", forbidden)
        with scalar_sources(f.engine), pytest.raises(AttendanceReadError, match="attendance_read_limit"):
            await service(f, session).summary(f.principal, group_id=f.empty_group)
        await session.rollback()


async def test_postgresql_derived_work_product_rejected_before_classification(attendance_cohort, monkeypatch):
    f = attendance_cohort
    async with f.sessions() as session:
        await session.execute(insert(AttendanceSessionModel), [activity(f, group=f.empty_group) for _ in range(100)])
        await add_coordinators(session, f, f.empty_group, 101)
        def forbidden(*_args, **_kwargs):
            raise AssertionError("Over-budget work reached classification")
        monkeypatch.setattr(attendance_closeout_repository, "classify_attendance_closeout", forbidden)
        with pytest.raises(AttendanceReadError, match="attendance_read_limit"):
            await service(f, session).summary(f.principal, group_id=f.empty_group)
        await session.rollback()


async def test_postgresql_unicode_whole_response_budget_preserves_source(attendance_cohort):
    f = attendance_cohort
    async with f.sessions() as session:
        await session.execute(insert(AttendanceSessionModel), [activity(f, group=f.empty_group) for _ in range(100)])
        await add_coordinators(session, f, f.empty_group, 25, name="😀" * 255)
        with scalar_sources(f.engine), pytest.raises(AttendanceReadError, match="attendance_read_limit"):
            await service(f, session).summary(f.principal, group_id=f.empty_group)
        await session.rollback()
        assert (await service(f, session).summary(f.principal, group_id=f.empty_group))["sessions"] == []


@pytest.mark.parametrize("lock", ["source", "grant"])
async def test_postgresql_blocked_sql_deadline_then_rollback_retry(attendance_cohort, monkeypatch, lock):
    f = attendance_cohort
    async with f.sessions() as holder, f.sessions() as reader:
        before = await snapshot(reader)
        await reader.rollback()
        if lock == "source":
            await holder.execute(text("LOCK TABLE attendance_sessions IN ACCESS EXCLUSIVE MODE"))
        else:
            await holder.execute(select(MCPGrantModel.id).where(MCPGrantModel.id == f.principal.grant_id).with_for_update())
        monkeypatch.setattr(attendance_reads, "READ_TIMEOUT_SECONDS", 0.15)
        with pytest.raises(AttendanceReadError, match="attendance_read_busy"):
            await summary(f, reader)
        await reader.rollback()
        await holder.rollback()
        monkeypatch.setattr(attendance_reads, "READ_TIMEOUT_SECONDS", 5)
        assert len((await asyncio.wait_for(summary(f, reader), 3))["sessions"]) == 1
        assert await snapshot(reader) == before


async def test_postgresql_external_cancellation_releases_authority_transaction(attendance_cohort):
    f = attendance_cohort
    async with f.sessions() as holder, f.sessions() as reader:
        await holder.execute(select(UserModel.id).where(UserModel.id == f.actor).with_for_update())
        waiting = asyncio.Event()
        def capture(_conn, _cursor, statement, _params, _context, _many):
            if "FOR SHARE OF users" in statement:
                waiting.set()
        event.listen(f.engine.sync_engine, "before_cursor_execute", capture)
        task = asyncio.create_task(summary(f, reader))
        try:
            await asyncio.wait_for(waiting.wait(), 3)
            assert not task.done()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await reader.rollback()
            await holder.rollback()
            assert len((await asyncio.wait_for(summary(f, reader), 3))["sessions"]) == 1
        finally:
            event.remove(f.engine.sync_engine, "before_cursor_execute", capture)
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
