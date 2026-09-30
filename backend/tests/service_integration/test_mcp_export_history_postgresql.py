"""Real PostgreSQL, retained synthetic schemas; no production or capacity claim."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import URL, Text, cast, event, func, insert, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.mcp.artifacts import MCPArtifactService
from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.export_history_reads import (
    ExportHistoryReadError,
    MCPExportHistoryReadService,
)
from app.application.mcp.exports import MCPExcelExportService
from app.core.config.mcp import MCPSettings
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    PassportExportHistoryModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    UserModel,
    UserSecurityStateModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes.passport_routes.export_history import (
    get_passport_group_export_history_detail,
    list_passport_group_export_history,
)
from tests.postgresql_schema import create_isolated_postgresql_tables

pytestmark = [pytest.mark.service_integration, pytest.mark.skipif(
    os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required")]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def history_postgres(test_settings, record_testsuite_property):
    host, database = os.environ.get("POSTGRES_HOST", "localhost"), os.environ["POSTGRES_DB"]
    if host not in {"127.0.0.1", "localhost"} or not database.startswith("passdetection_ci_"):
        pytest.fail("History proof requires a dedicated loopback CI database")
    schema = "manual_review_" + uuid.uuid4().hex
    record_testsuite_property("retained_export_history_postgresql_schema", schema)
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
            session.add(MCPControlModel(id=1, enabled=True))
            await session.commit()
        settings = test_settings.model_copy(update={"mcp": MCPSettings(enabled=True,
            enabled_capabilities=["mcp:read"], export_families=[],
            export_source_row_limit=100, export_source_byte_limit=1024 * 1024)})
        yield SimpleNamespace(engine=engine, sessions=sessions, schema=schema, settings=settings)
    finally:
        await engine.dispose()  # Deliberately retain the new schema and all committed fixtures.


@pytest_asyncio.fixture
async def history_cohort(history_postgres):
    database, now = history_postgres, datetime.now(UTC)
    async with database.sessions() as session:
        agencies = [AgencyModel(id=uuid.uuid4(), name="Synthetic history", email=f"{uuid.uuid4()}@example.test") for _ in range(2)]
        session.add_all(agencies)
        await session.flush()
        users = [UserModel(id=uuid.uuid4(), agency_id=agencies[0].id, email=f"{uuid.uuid4()}@example.test",
            full_name="Synthetic history actor", hashed_password="unused", role="super_admin", is_active=True) for _ in range(2)]
        session.add_all(users)
        await session.flush()
        session.add_all([UserSecurityStateModel(user_id=user.id, session_version=1, credential_state="active",
            mfa_enabled_at=now, mfa_secret_ciphertext="synthetic-not-used") for user in users])
        groups = [ClientGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Synthetic history group",
            token=uuid.uuid4().hex, status="active") for agency in agencies]
        empty = ClientGroupModel(id=uuid.uuid4(), agency_id=agencies[0].id, name="Imported-only history",
            token=uuid.uuid4().hex, import_only=True, status="active")
        session.add_all([*groups, empty])
        await session.flush()
        grant = MCPGrantModel(id=uuid.uuid4(), user_id=users[0].id, client_id="global-connects-desktop",
            name="Synthetic history read", resource=database.settings.mcp.public_origin + "/mcp",
            capabilities=["mcp:read"], security_version=1, mfa_at=now, created_at=now,
            expires_at=now + timedelta(days=1))
        session.add(grant)
        people = [submission(agencies[0].id, groups[0].id, status=status)
                  for status in (*OFFICE_VISIBLE_PASSPORT_STATUS_VALUES, "uploaded", "failed", "ready_for_client_review")]
        session.add_all(people)
        await session.flush()
        session.add(PassportRosterResolutionModel(id=uuid.uuid4(), agency_id=agencies[0].id,
            client_group_id=groups[0].id, submission_id=people[1].id,
            resolution_type="rejected", status="active", resolved_by_user_id=users[0].id))
        await session.commit()
    return SimpleNamespace(**vars(database), agency=agencies[0].id, other_agency=agencies[1].id,
        group=groups[0].id, other_group=groups[1].id, imported_group=empty.id,
        actor=users[0].id, other_actor=users[1].id, people=[row.id for row in people],
        principal=MCPPrincipal(grant.id, users[0].id, grant.client_id, ("mcp:read",), grant.expires_at, grant.resource))


def submission(agency_id, group_id, *, status="confirmed"):
    return PassportSubmissionModel(id=uuid.uuid4(), agency_id=agency_id, group_id=group_id,
        client_name="Synthetic current value", client_email="synthetic@example.test", status=status,
        image_s3_key="private/never-accessed", extracted_fields={"unused": "x" * 4096})


async def checkpoint(session, f, *, snapshot=(), exported=None, **changes):
    exported = list(snapshot) if exported is None else list(exported)
    values = dict(id=uuid.uuid4(), agency_id=f.agency, group_id=f.group,
        export_kind="passport_excel", export_mode="incremental", format_version=1,
        snapshot_submission_ids=[str(value) for value in snapshot],
        exported_submission_ids=[str(value) for value in exported],
        exported_people_snapshot=[dict(submission_id=str(value), client_name=f"PRIVATE-SNAPSHOT-{index}",
            client_phone="+919999000001", client_email="private@example.test", passport_number="PRIVATE-P")
            for index, value in enumerate(exported)],
        total_available_count=len(snapshot), exported_count=len(exported), pending_recipient_count=4,
        created_by_user_id=f.actor, actor_email="private-actor@example.test", status="completed",
        created_at=datetime.now(UTC) - timedelta(days=1), completed_at=datetime.now(UTC) - timedelta(seconds=1),
        artifact_metadata={"storage_key": "PRIVATE/never-read", "padding": "x" * (2 * 1024 * 1024)})
    row = PassportExportHistoryModel(**(values | changes))
    session.add(row)
    await session.flush()
    return row


def service(f, session, byte_limit=None):
    settings = f.settings.model_copy(deep=True)
    if byte_limit is not None:
        settings.mcp.export_source_byte_limit = byte_limit
    return MCPExportHistoryReadService(session, settings)


async def listing(f, session, **options):
    return await service(f, session).list_history(f.principal, **(
        dict(agency_id=f.agency, group_id=f.group, kind="passport_excel") | options))


async def detail(f, session, identifier, **options):
    return await service(f, session).get_history(f.principal, **(
        dict(agency_id=f.agency, group_id=f.group, history_id=identifier) | options))


@contextmanager
def observed_read(engine):
    statements = []
    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())
    def forbidden(*_args):
        raise AssertionError("History read hydrated a complete source/history ORM row")
    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    for model in (PassportSubmissionModel, PassportExportHistoryModel, ClientGroupModel):
        event.listen(model, "load", forbidden)
        event.listen(model, "refresh", forbidden)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
        for model in (PassportSubmissionModel, PassportExportHistoryModel, ClientGroupModel):
            event.remove(model, "load", forbidden)
            event.remove(model, "refresh", forbidden)


async def effects(session):
    counts = [await session.scalar(select(func.count()).select_from(model)) for model in (
        PassportSubmissionModel, PassportExportHistoryModel, MCPArtifactModel, MCPOperationModel, WhatsAppMessageLogModel)]
    retained = (await session.execute(select(PassportExportHistoryModel.id,
        func.md5(cast(PassportExportHistoryModel.snapshot_submission_ids, Text)),
        func.md5(cast(PassportExportHistoryModel.exported_people_snapshot, Text)),
        func.md5(cast(PassportExportHistoryModel.artifact_metadata, Text)),
        PassportExportHistoryModel.status, PassportExportHistoryModel.completed_at,
    ).order_by(PassportExportHistoryModel.id))).all()
    return counts, retained


@pytest.fixture(autouse=True)
def no_export_or_file_effects(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("History discovery cannot create an export or initialize storage")
    monkeypatch.setattr(MCPArtifactService, "storage", property(forbidden))
    monkeypatch.setattr(MCPExcelExportService, "prepare", forbidden)


async def test_postgresql_canonical_completed_v1_roster_and_no_source_hydration(history_cohort):
    f = history_cohort
    async with f.sessions() as session:
        expected = await checkpoint(session, f, snapshot=[f.people[0]], exported=[], created_by_user_id=f.other_actor)
        await checkpoint(session, f, status="prepared", completed_at=None)
        await checkpoint(session, f, format_version=2)
        await checkpoint(session, f, export_kind="passport_images")
        await session.commit()
        before = await effects(session)
        with observed_read(f.engine) as statements:
            result = await listing(f, session)
        assert result["current_submission_count"] == 5 and result["total_count"] == 1
        assert result["items"][0]["id"] == str(expected.id)
        assert result["items"][0]["new_submission_count"] == 4
        assert result["items"][0]["exported_count"] == 0 and result["items"][0]["pending_recipient_count"] == 4
        assert result["items"][0]["actor_email"] is None
        assert result["maximum_checkpoint_people"] == 5000 and f.settings.mcp.export_source_row_limit == 100
        assert len(statements) <= 12 and any("octet_length" in query for query in statements)
        assert not any("artifact_metadata" in query or "extracted_fields" in query for query in statements)
        assert not any(query.lstrip().startswith(("insert", "update", "delete")) for query in statements)
        assert await effects(session) == before
        actor = await UserRepository(session).get_by_id(f.actor)
        website = await list_passport_group_export_history(f.group, export_kind="passport_excel", page=1,
            page_size=25, current_user=actor, session=session)
        private = await listing(f, session, include_personal_details=True)
        assert private["items"] == website.model_dump(mode="json")["items"]
        assert private["current_submission_count"] == website.current_submission_count


async def test_postgresql_completion_cutoff_tied_keyset_excludes_late_completion(history_cohort):
    f, stamp = history_cohort, datetime.now(UTC) - timedelta(seconds=10)
    async with f.sessions() as session:
        rows = [await checkpoint(session, f, completed_at=stamp) for _ in range(3)]
        prepared = await checkpoint(session, f, status="prepared", completed_at=None,
                                    created_at=stamp - timedelta(days=10))
        await session.commit()
        prepared_id = prepared.id
        expected_ids = sorted((row.id for row in rows), reverse=True)
        page = await listing(f, session, page_size=1)
        found = [page["items"][0]["id"]]
        initial_cursor = page["next_cursor"]
        await session.rollback()
        # A separate writer completes an older prepared export after the first
        # page. Preparation time cannot make it appear in the established walk.
        async with f.sessions() as writer:
            await writer.execute(update(PassportExportHistoryModel).where(PassportExportHistoryModel.id == prepared_id)
                                 .values(status="completed", completed_at=datetime.now(UTC)))
            await writer.commit()
        while page["next_cursor"]:
            page = await listing(f, session, page_size=1, cursor=page["next_cursor"])
            assert page["total_count"] == 3
            found.extend(row["id"] for row in page["items"])
            await session.rollback()
        assert found == [str(identifier) for identifier in expected_ids]
        assert (await listing(f, session))["total_count"] == 4
        await session.rollback()
        with pytest.raises(ExportHistoryReadError, match="^history_invalid_request$"):
            await listing(f, session, page_size=1, cursor=initial_cursor, include_personal_details=True)


async def test_postgresql_frozen_person_order_availability_and_sensitive_audit_only(history_cohort):
    f, missing = history_cohort, uuid.uuid4()
    async with f.sessions() as session:
        row = await checkpoint(session, f, snapshot=[f.people[0], missing], exported=[missing, f.people[0], f.people[1]])
        await session.commit()
        before = await effects(session)
        with observed_read(f.engine) as statements:
            public = await detail(f, session, row.id)
        assert [item["record_available"] for item in public["items"]] == [False, True, True]
        assert [item["submission_id"] for item in public["items"]] == [str(missing), str(f.people[0]), str(f.people[1])]
        assert "PRIVATE" not in json.dumps(public)
        assert not any("artifact_metadata" in query for query in statements)
        assert await effects(session) == before
        actor = await UserRepository(session).get_by_id(f.actor)
        website = await get_passport_group_export_history_detail(f.group, row.id, page=2, page_size=1,
            current_user=actor, session=session)
        private = await detail(f, session, row.id, page=2, page_size=1, include_personal_details=True)
        assert private["items"] == website.model_dump(mode="json")["items"]
        assert private["items"][0]["client_name"] == "PRIVATE-SNAPSHOT-1"
        assert private["completeness"] == "partial"
        await session.commit()
        assert await effects(session) == before
        audits = list(await session.scalars(select(AuditLogModel).where(AuditLogModel.user_id == f.actor)))
        assert audits and all(row.action == "sensitive_read.authorized" for row in audits)
        assert "PRIVATE" not in str([row.metadata_json for row in audits])


@pytest.mark.parametrize("details", [False, True])
async def test_postgresql_combined_utf8_admission_rejects_before_json_materialization(history_cohort, details):
    f = history_cohort
    async with f.sessions() as session:
        identifiers = [uuid.uuid4() for _ in range(8)]
        rows = [await checkpoint(session, f, snapshot=identifiers) for _ in range(2)]
        if details:
            people = list(rows[0].exported_people_snapshot)
            people[0] = {**people[0], "client_name": "界" * 400_000}
            rows[0].exported_people_snapshot = people
        else:
            rows[0].actor_email = "界" * 150
            rows[1].actor_email = "界" * 150
        await session.commit()
        if not details:
            sizes = list(await session.scalars(select(
                func.octet_length(cast(PassportExportHistoryModel.snapshot_submission_ids, Text))
                + func.octet_length(PassportExportHistoryModel.actor_email)
            ).where(PassportExportHistoryModel.id.in_([row.id for row in rows]))))
            assert all(size < 1024 for size in sizes) and sum(sizes) > 1024
        with observed_read(f.engine) as statements:
            with pytest.raises(ExportHistoryReadError, match="^history_limit$"):
                reader = service(f, session, 1024 * 1024 if details else 1024)
                if details:
                    await reader.get_history(f.principal, agency_id=f.agency, group_id=f.group, history_id=rows[0].id)
                else:
                    await reader.list_history(f.principal, agency_id=f.agency, group_id=f.group,
                                              kind="passport_excel", include_personal_details=True)
        json_column = "exported_people_snapshot" if details else "snapshot_submission_ids"
        assert any("octet_length" in query and json_column in query for query in statements)
        assert not any(json_column in query and "sum(" not in query for query in statements)
        assert not any(query.lstrip().startswith(("insert", "update", "delete")) for query in statements)


async def test_postgresql_exact_roster_ceiling_exceeds_export_limit_and_stops_at_5001(history_cohort):
    f = history_cohort
    async with f.sessions() as session:
        # Five canonical rows already exist. The current minimum release's
        # 100-row generation limit must not truncate history's distinct ceiling.
        values = [{"id": uuid.uuid4(), "agency_id": f.agency, "group_id": f.group, "client_name": "Synthetic",
                   "image_s3_key": "private/unused", "status": "confirmed"} for _ in range(4995)]
        await session.execute(insert(PassportSubmissionModel), values)
        await checkpoint(session, f)
        await session.commit()
        assert (await listing(f, session))["current_submission_count"] == 5000
        await session.rollback()
        session.add(submission(f.agency, f.group))
        await session.commit()
        with observed_read(f.engine) as statements:
            with pytest.raises(ExportHistoryReadError, match="^history_limit$"):
                await listing(f, session)
        assert any("select passport_submissions.id" in query and "limit" in query for query in statements)
        assert not any("passport_export_history" in query for query in statements)


@pytest.mark.parametrize("details", [False, True])
async def test_postgresql_checkpoint_people_ceiling_is_independent_of_byte_budget(history_cohort, details):
    f = history_cohort
    async with f.sessions() as session:
        identifiers = [uuid.uuid4() for _ in range(5001)]
        row = await checkpoint(session, f, snapshot=identifiers, exported=identifiers if details else [])
        await session.commit()
        reader = service(f, session, 16 * 1024 * 1024)
        with pytest.raises(ExportHistoryReadError, match="^history_limit$"):
            if details:
                await reader.get_history(f.principal, agency_id=f.agency, group_id=f.group, history_id=row.id)
            else:
                await reader.list_history(f.principal, agency_id=f.agency, group_id=f.group, kind="passport_excel")


@pytest.mark.parametrize("target", ["history", "group"])
async def test_postgresql_nowait_source_lock_fails_busy_then_clean_retry(history_cohort, target):
    f = history_cohort
    async with f.sessions() as setup:
        row = await checkpoint(setup, f)
        await setup.commit()
    async with f.sessions() as holder, f.sessions() as reader:
        model, identifier = (PassportExportHistoryModel, row.id) if target == "history" else (ClientGroupModel, f.group)
        await holder.execute(select(model.id).where(model.id == identifier).with_for_update())
        began = time.monotonic()
        with pytest.raises(ExportHistoryReadError, match="^history_busy$"):
            await detail(f, reader, row.id)
        assert time.monotonic() - began < 3
        await reader.rollback()
        await holder.rollback()
        assert (await detail(f, reader, row.id))["history_id"] == str(row.id)


async def test_postgresql_cancellation_during_authority_wait_rolls_back_and_retry_succeeds(history_cohort):
    f = history_cohort
    async with f.sessions() as setup:
        row = await checkpoint(setup, f)
        await setup.commit()
    async with f.sessions() as holder, f.sessions() as reader, f.sessions() as observer:
        await holder.execute(select(MCPGrantModel.id).where(MCPGrantModel.id == f.principal.grant_id).with_for_update())
        reader_pid = await reader.scalar(text("SELECT pg_backend_pid()"))
        task = asyncio.create_task(detail(f, reader, row.id))
        try:
            async with asyncio.timeout(3):
                while await observer.scalar(text("SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"),
                                            {"pid": reader_pid}) != "Lock":
                    await observer.rollback()
                    await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await reader.rollback()
            await holder.rollback()
        assert (await detail(f, reader, row.id))["status"] == "completed"


@pytest.mark.parametrize("boundary", ["foreign_scope", "forged_actor", "revoked", "role_lost"])
async def test_postgresql_scope_and_live_authority_precede_checkpoint_materialization(history_cohort, boundary):
    f = history_cohort
    async with f.sessions() as session:
        row = await checkpoint(session, f)
        await session.commit()
        principal, agency = f.principal, f.agency
        if boundary == "foreign_scope":
            agency = f.other_agency
        elif boundary == "forged_actor":
            principal = replace(principal, user_id=f.other_actor)
        elif boundary == "revoked":
            await session.execute(update(MCPGrantModel).where(MCPGrantModel.id == principal.grant_id).values(revoked_at=datetime.now(UTC)))
        else:
            await session.execute(update(UserModel).where(UserModel.id == f.actor).values(role="agency_admin"))
        with observed_read(f.engine) as statements:
            with pytest.raises((MCPAuthError, ExportHistoryReadError)):
                await service(f, session).get_history(principal, agency_id=agency, group_id=f.group, history_id=row.id)
        assert not any("passport_export_history" in query for query in statements)
        await session.rollback()


@pytest.mark.parametrize("status", ["active", "closed", "archived", "deleted"])
async def test_postgresql_retained_group_rules_and_import_only_pending_checkpoint(history_cohort, status):
    f = history_cohort
    async with f.sessions() as session:
        row = await checkpoint(session, f, snapshot=[f.people[0]])
        imported = await checkpoint(session, f, group_id=f.imported_group, export_kind="passport_images")
        await session.execute(update(ClientGroupModel).where(ClientGroupModel.id == f.group).values(
            status=status, deleted_at=datetime.now(UTC) if status == "deleted" else None))
        await session.commit()
        row_id, imported_id = row.id, imported.id
        if status == "deleted":
            with pytest.raises(ExportHistoryReadError, match="^history_unavailable$"):
                await detail(f, session, row_id)
            await session.rollback()
        result = await listing(f, session, include_deleted=status == "deleted")
        assert result["current_submission_count"] == (5 if status in {"active", "closed"} else 0)
        assert (await detail(f, session, row_id, include_deleted=status == "deleted"))["items"][0]["record_available"] is True
        empty = await detail(f, session, imported_id, group_id=f.imported_group)
        assert empty["items"] == [] and empty["exported_count"] == 0 and empty["pending_recipient_count"] == 4
        assert empty["export_kind"] == "passport_images"
