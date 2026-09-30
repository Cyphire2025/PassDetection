"""Retained isolated PostgreSQL rename read proof, never storage/provider/load."""

import asyncio
import json
import os
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import URL, event, func, insert, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.mcp import rename_reads
from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.rename_reads import MCPRenameReadService, RenameReadBusyError
from app.application.use_cases.document_rename.read_scope import DocumentRenameScopeError
from app.core.config.mcp import MCPSettings
from app.domain.entities.entities import UserRole
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AuditLogModel,
    DocumentRenameBatchModel,
    DocumentRenameItemModel,
    DocumentUploadChunkModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.repositories.document_rename_read_repository import (
    DocumentRenameReadRepository,
    RenameReadLimitError,
    RenameReadUnavailableError,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes import document_rename
from app.presentation.api.v1.routes.document_rename import get_rename_batch, list_rename_batches
from tests.integration.test_mcp_operations import seed_identity
from tests.mcp_rename_fixtures import seed_rename_data
from tests.postgresql_schema import create_isolated_postgresql_tables

pytestmark = [pytest.mark.service_integration, pytest.mark.skipif(
    os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required")]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def rename_postgres(test_settings, record_testsuite_property):
    host, database = os.environ.get("POSTGRES_HOST", "localhost"), os.environ["POSTGRES_DB"]
    if host not in {"127.0.0.1", "localhost"} or not database.startswith("passdetection_ci_"):
        pytest.fail("Rename proof requires the dedicated loopback CI database")
    schema = "manual_review_" + uuid.uuid4().hex
    record_testsuite_property("retained_rename_postgresql_schema", schema)
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
            actor, grants, _tokens = await seed_identity(session, settings)
            data = await seed_rename_data(session, actor)
            grants[0].capabilities = ["mcp:read"]
            for index in range(105):
                session.add(DocumentRenameBatchModel(id=uuid.UUID(f"aaaaaaaa-0000-0000-0000-{index:012x}"),
                    agency_id=data.agencies[0].id, title="Synthetic retained batch",
                    created_at=datetime(2026, 9, 10, tzinfo=UTC)))
            large = DocumentRenameBatchModel(id=uuid.uuid4(), agency_id=data.agencies[0].id,
                title="Bounded canonical batch", total_count=1500, visa_count=1500,
                created_at=datetime(2026, 8, 1, tzinfo=UTC))
            session.add(large)
            await session.flush()
            await session.execute(insert(DocumentRenameItemModel), [dict(id=uuid.uuid4(), batch_id=large.id,
                agency_id=data.agencies[0].id, original_filename=f"Original {index:04d}.pdf",
                renamed_filename=f"Renamed {index:04d}.pdf", storage_key="private/DO-NOT-HYDRATE", detected_type="visa",
                status="renamed", extracted_name="PRIVATE-EXTRACTED-NAME", extracted_passport_number="PRIVATE-PASSPORT",
                extracted_reference="PRIVATE-REFERENCE", reason="Synthetic reason") for index in range(1500)])
            await session.commit()
            principal = MCPPrincipal(grants[0].id, actor.id, grants[0].client_id, tuple(grants[0].capabilities),
                grants[0].expires_at, grants[0].resource)
        yield SimpleNamespace(engine=engine, sessions=sessions, settings=settings,
            principal=principal, data=data, large_id=large.id)
    finally:
        # Keep the private schema and all synthetic committed records for review.
        await engine.dispose()


def service(f, session):
    return MCPRenameReadService(session, f.settings)


async def test_postgresql_batch_pagination_and_canonical_first_window_parity(rename_postgres):
    f = rename_postgres
    async with f.sessions() as session:
        first = await service(f, session).list_batches(f.principal)
        rest = await service(f, session).list_batches(f.principal, cursor=first["next_cursor"])
        assert len(first["items"]) == 100 and len(rest["items"]) == 9
        ids = {row["batch_id"] for row in first["items"] + rest["items"]}
        assert len(ids) == 109 and str(f.data.batches[3].id) not in ids and str(f.large_id) in ids
        actor = await UserRepository(session).get_by_id(f.principal.user_id)
        # Website ties have no secondary order; compare untied older summaries
        # through exact get and preserve the unchanged first-window size.
        assert len(await list_rename_batches(actor, session)) == 100
        actual = await service(f, session).get_batch(f.principal, f.data.batches[0].id, include_extracted_identifiers=True)
        canonical = await get_rename_batch(f.data.batches[0].id, actor, session)
        expected = {str(row.id): row.model_dump(mode="json") for row in canonical.items}
        for row in actual["items"]:
            web = expected[row["id"]]
            assert {key: value for key, value in row.items() if key != "download_metadata_eligible"} == {
                key: value for key, value in web.items() if key != "download_url"}
            assert row["download_metadata_eligible"] == bool(web["download_url"])
        assert actual["total_items"] == 6 and actual["total_count"] == 99
        audits = (await session.scalars(select(AuditLogModel).where(AuditLogModel.action == "document_rename.mcp_identifiers_read"))).all()
        assert len(audits) == 1 and "PRIVATE" not in json.dumps(audits[0].metadata_json)
        await session.commit()


async def test_postgresql_bounded_scalar_item_projection_and_all_1500_reachable(rename_postgres):
    f = rename_postgres
    sql = []
    def capture(_c, _cursor, statement, _params, _context, _many):
        sql.append(statement.lower())
    def forbidden(*args):
        raise AssertionError("Rename read materialized full business ORM")
    async with f.sessions() as session:
        event.listen(f.engine.sync_engine, "before_cursor_execute", capture)
        for model in (DocumentRenameBatchModel, DocumentRenameItemModel):
            event.listen(model, "load", forbidden)
            event.listen(model, "refresh", forbidden)
        try:
            first = await service(f, session).get_batch(f.principal, f.large_id)
        finally:
            event.remove(f.engine.sync_engine, "before_cursor_execute", capture)
            for model in (DocumentRenameBatchModel, DocumentRenameItemModel):
                event.remove(model, "load", forbidden)
                event.remove(model, "refresh", forbidden)
        assert len(sql) == 9
        projected = next(statement for statement in sql if " as storage_present" in statement)
        assert "storage_key !=" in projected and " document_rename_items.storage_key," not in projected
        assert "document_rename_items.extracted_name" not in projected and "limit" in projected
        assert first["total_items"] == 1500 and first["total_pages"] == 15 and len(first["items"]) == 100
        all_ids = {row["id"] for row in first["items"]}
        for page in range(2, 16):
            result = await service(f, session).get_batch(f.principal, f.large_id, page=page)
            assert len(result["items"]) == 100 and result["has_more"] is (page < 15)
            all_ids.update(row["id"] for row in result["items"])
        assert len(all_ids) == 1500
        assert "DO-NOT-HYDRATE" not in json.dumps(first) and "PRIVATE-EXTRACTED" not in json.dumps(first)
        for model in (MCPOperationModel, MCPArtifactModel, DocumentUploadChunkModel):
            assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_postgresql_1501_source_rows_reject_before_any_item_projection(rename_postgres):
    f = rename_postgres
    async with f.sessions() as session:
        session.add(DocumentRenameItemModel(id=uuid.uuid4(), agency_id=f.data.agencies[0].id,
            batch_id=f.large_id, original_filename="Extra", renamed_filename="Extra", storage_key="private/never-read"))
        await session.flush()
        sql = []
        def capture(_c, _cursor, statement, _params, _context, _many):
            sql.append(statement.lower())
        event.listen(f.engine.sync_engine, "before_cursor_execute", capture)
        try:
            with pytest.raises(RenameReadLimitError):
                await service(f, session).get_batch(f.principal, f.large_id)
        finally:
            event.remove(f.engine.sync_engine, "before_cursor_execute", capture)
        assert not any(" as storage_present" in statement for statement in sql)
        await session.rollback()


async def test_postgresql_unicode_enveloped_byte_budget_and_smaller_page(rename_postgres):
    f = rename_postgres
    async with f.sessions() as session:
        await session.execute(update(DocumentRenameItemModel).where(DocumentRenameItemModel.batch_id == f.large_id)
            .values(original_filename="🙂" * 255, renamed_filename="🙂" * 255, reason="🙂" * 255))
        with pytest.raises(RenameReadLimitError):
            await service(f, session).get_batch(f.principal, f.large_id)
        result = await service(f, session).get_batch(f.principal, f.large_id, page_size=10)
        assert len(result["items"]) == 10 and result["has_more"]
        await session.rollback()


async def test_postgresql_foreign_scope_and_item_agency_never_leak(rename_postgres):
    f = rename_postgres
    async with f.sessions() as session:
        with pytest.raises(RenameReadUnavailableError):
            await service(f, session).get_batch(f.principal, f.data.batches[3].id)
        await session.execute(update(DocumentRenameItemModel).where(DocumentRenameItemModel.id == f.data.items[0].id)
            .values(agency_id=f.data.agencies[1].id))
        result = await service(f, session).get_batch(f.principal, f.data.batches[0].id)
        assert result["total_items"] == 5 and str(f.data.items[0].id) not in json.dumps(result)
        await session.rollback()


@pytest.mark.parametrize("lock_kind", ["source", "grant"])
async def test_postgresql_deadline_covers_source_and_authority_locks_then_retry(rename_postgres, monkeypatch, lock_kind):
    f = rename_postgres
    async with f.sessions() as blocker, f.sessions() as caller:
        if lock_kind == "source":
            await blocker.execute(text("LOCK TABLE document_rename_items IN ACCESS EXCLUSIVE MODE"))
        else:
            await blocker.execute(select(MCPGrantModel.id).where(MCPGrantModel.id == f.principal.grant_id).with_for_update())
        monkeypatch.setattr(rename_reads, "RENAME_READ_TIMEOUT_SECONDS", 0.1)
        with pytest.raises(RenameReadBusyError):
            await service(f, caller).get_batch(f.principal, f.large_id, include_extracted_identifiers=True)
        await caller.rollback()
        await blocker.rollback()
        monkeypatch.setattr(rename_reads, "RENAME_READ_TIMEOUT_SECONDS", 10)
        result = await service(f, caller).get_batch(f.principal, f.large_id, page_size=1)
        assert len(result["items"]) == 1


async def test_postgresql_identity_change_waits_for_sensitive_read_transaction(rename_postgres):
    f = rename_postgres
    async with f.sessions() as reader, f.sessions() as writer:
        await service(f, reader).get_batch(f.principal, f.large_id, page_size=1, include_extracted_identifiers=True)
        await writer.execute(text("SET LOCAL lock_timeout = '100ms'"))
        with pytest.raises(DBAPIError):
            await writer.execute(update(UserModel).where(UserModel.id == f.principal.user_id).values(agency_id=f.data.agencies[1].id))
        await writer.rollback()
        await reader.commit()
        await writer.execute(update(UserModel).where(UserModel.id == f.principal.user_id).values(agency_id=f.data.agencies[1].id))
        await writer.rollback()


@pytest.mark.parametrize("change", ["revoked", "capability", "expired", "inactive", "deleted", "role", "security_version", "principal_actor"])
async def test_postgresql_fresh_authority_denies_before_rename_projection(rename_postgres, change):
    f, now = rename_postgres, datetime.now(UTC)
    async with f.sessions() as session:
        principal = f.principal
        if change in {"revoked", "capability", "expired"}:
            values = {"revoked": {"revoked_at": now}, "capability": {"capabilities": []},
                "expired": {"created_at": now - timedelta(days=2), "expires_at": now - timedelta(days=1)}}[change]
            await session.execute(update(MCPGrantModel).where(MCPGrantModel.id == principal.grant_id).values(**values))
        elif change in {"inactive", "deleted", "role"}:
            values = {"inactive": {"is_active": False}, "deleted": {"deleted_at": now}, "role": {"role": "agency_staff"}}[change]
            await session.execute(update(UserModel).where(UserModel.id == principal.user_id).values(**values))
        elif change == "security_version":
            await session.execute(update(UserSecurityStateModel).where(UserSecurityStateModel.user_id == principal.user_id).values(session_version=2))
        else:
            principal = replace(principal, user_id=f.data.staff.id)
        statements = []
        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            statements.append(statement.lower())
        event.listen(f.engine.sync_engine, "before_cursor_execute", capture)
        try:
            with pytest.raises(MCPAuthError):
                await service(f, session).get_batch(principal, f.large_id, page_size=1, include_extracted_identifiers=True)
        finally:
            event.remove(f.engine.sync_engine, "before_cursor_execute", capture)
        assert not any("from document_rename_" in query or query.lstrip().startswith("insert") for query in statements)
        await session.rollback()
        assert len((await service(f, session).get_batch(f.principal, f.large_id, page_size=1))["items"]) == 1


async def test_postgresql_current_agency_and_website_staff_coordinator_semantics(rename_postgres):
    f = rename_postgres
    async with f.sessions() as session:
        # The canonical web read allows retained inactive-agency metadata;
        # preserve that behavior instead of inventing an active-agency filter.
        assert f.data.agencies[0].is_active is False
        staff = await UserRepository(session).get_by_id(f.data.staff.id)
        web = await list_rename_batches(staff, session)
        rows = await DocumentRenameReadRepository(session).batches(staff, staff.agency_id,
            cutoff=datetime.now(UTC), after=None, limit=100)
        assert {str(row.batch_id) for row in web} == {str(row["id"]) for row in rows} == {str(f.data.batches[2].id)}
        staff.role = UserRole.AGENCY_COORDINATOR
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as denied:
            await list_rename_batches(staff, session)
        assert denied.value.status_code == 403
        await session.execute(update(UserModel).where(UserModel.id == f.principal.user_id).values(agency_id=None))
        with pytest.raises(DocumentRenameScopeError):
            await service(f, session).list_batches(f.principal)
        await session.rollback()
        await session.execute(update(UserModel).where(UserModel.id == f.principal.user_id).values(agency_id=f.data.agencies[1].id))
        listing = await service(f, session).list_batches(f.principal)
        assert listing["agency_id"] == str(f.data.agencies[1].id)
        assert [row["batch_id"] for row in listing["items"]] == [str(f.data.batches[3].id)]
        with pytest.raises(RenameReadUnavailableError):
            await service(f, session).get_batch(f.principal, f.large_id)
        await session.rollback()


@pytest.mark.parametrize("binding", ["page_size", "actor", "agency", "signature", "expiry"])
async def test_postgresql_cursor_bound_to_current_actor_scope_and_page(rename_postgres, binding):
    f = rename_postgres
    async with f.sessions() as session:
        reader = service(f, session)
        first = await reader.list_batches(f.principal, page_size=1)
        cursor, principal = first["next_cursor"], f.principal
        if binding == "actor":
            actor, grants, _ = await seed_identity(session, f.settings, email=f"{uuid.uuid4()}@example.test")
            actor.agency_id, grants[0].capabilities = f.data.agencies[0].id, ["mcp:read"]
            await session.flush()
            grant = grants[0]
            principal = MCPPrincipal(grant.id, actor.id, grant.client_id, ("mcp:read",), grant.expires_at, grant.resource)
        elif binding == "agency":
            await session.execute(update(UserModel).where(UserModel.id == principal.user_id).values(agency_id=f.data.agencies[1].id))
        elif binding == "signature":
            cursor += "x"
        elif binding == "expiry":
            state = reader.cursors.read(cursor, dict(query="rename-batches", user_id=principal.user_id,
                agency_id=f.data.agencies[0].id, page_size=1))
            cursor = reader.cursors.encode(state | {"expires": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()})
        with pytest.raises(ValueError):
            await reader.list_batches(principal, page_size=2 if binding == "page_size" else 1, cursor=cursor)
        await session.rollback()


async def test_postgresql_keyset_retains_tie_order_and_excludes_new_rows(rename_postgres):
    f = rename_postgres
    async with f.sessions() as session:
        first = await service(f, session).list_batches(f.principal, page_size=100)
        # A same-session later row is visible to subsequent SQL but excluded by
        # the signed first-page creation cutoff. Roll back after observation.
        later = DocumentRenameBatchModel(id=uuid.uuid4(), agency_id=f.data.agencies[0].id,
            title="Later synthetic row", created_at=datetime.now(UTC) + timedelta(seconds=1))
        session.add(later)
        await session.flush()
        rest = await service(f, session).list_batches(f.principal, page_size=100, cursor=first["next_cursor"])
        rows = first["items"] + rest["items"]
        order = [(datetime.fromisoformat(row["created_at"]), uuid.UUID(row["batch_id"])) for row in rows]
        assert order == sorted(order, reverse=True) and len(rows) == 109
        assert str(later.id) not in {row["batch_id"] for row in rows}
        assert rest["consistency"]["created_before"] == first["consistency"]["created_before"]
        await session.rollback()


async def test_postgresql_default_and_sensitive_reads_preserve_every_business_column(rename_postgres, monkeypatch):
    f = rename_postgres
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Metadata discovery must not initialize storage")
    monkeypatch.setattr(document_rename, "MinioStorageRepository", forbidden)
    async with f.sessions() as session:
        async def snapshot():
            return [(await session.execute(select(*model.__table__.columns).order_by(model.id))).all()
                for model in (DocumentRenameBatchModel, DocumentRenameItemModel, DocumentUploadChunkModel)]
        before = await snapshot()
        audit_count = await session.scalar(select(func.count()).select_from(AuditLogModel))
        ordinary = await service(f, session).get_batch(f.principal, f.data.batches[0].id)
        assert all(row["extracted_name"] is None and row["extracted_passport_number"] is None and row["extracted_reference"] is None for row in ordinary["items"])
        assert await session.scalar(select(func.count()).select_from(AuditLogModel)) == audit_count
        personal = await service(f, session).get_batch(f.principal, f.data.batches[0].id, include_extracted_identifiers=True)
        assert all(row["extracted_name"] == "PRIVATE-EXTRACTED-NAME" for row in personal["items"])
        # Canonical rename downloads accept classifier visa/flight_ticket only;
        # a distribution-lane name is not a supported classifier result.
        assert [row["download_metadata_eligible"] for row in personal["items"]] == [True, True, False, False, False, False]
        assert personal["files_accessed"] == ordinary["files_accessed"] == 0
        assert await snapshot() == before
        assert await session.scalar(select(func.count()).select_from(AuditLogModel)) == audit_count + 1
        for model in (MCPArtifactModel, MCPOperationModel):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
        await session.rollback()


async def test_postgresql_external_cancellation_at_identity_lock_has_no_sensitive_audit(rename_postgres):
    f = rename_postgres
    async with f.sessions() as holder, f.sessions() as reader:
        before = await reader.scalar(select(func.count()).select_from(AuditLogModel))
        await reader.rollback()
        await holder.execute(select(UserModel.id).where(UserModel.id == f.principal.user_id).with_for_update())
        waiting = asyncio.Event()
        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            if "FOR SHARE OF users" in statement:
                waiting.set()
        event.listen(f.engine.sync_engine, "before_cursor_execute", capture)
        task = asyncio.create_task(service(f, reader).get_batch(f.principal, f.large_id, page_size=1, include_extracted_identifiers=True))
        try:
            await asyncio.wait_for(waiting.wait(), 3)
            assert not task.done()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await reader.rollback()
            await holder.rollback()
            assert await reader.scalar(select(func.count()).select_from(AuditLogModel)) == before
            observed = await asyncio.wait_for(service(f, reader).get_batch(f.principal, f.large_id, page_size=1), 3)
            assert len(observed["items"]) == 1
        finally:
            event.remove(f.engine.sync_engine, "before_cursor_execute", capture)
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
