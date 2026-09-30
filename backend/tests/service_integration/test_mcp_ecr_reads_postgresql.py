"""Retained synthetic PostgreSQL ECR read proof; no production/capacity claim."""

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
from sqlalchemy import URL, event, func, insert, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.mcp import ecr_reads
from app.application.mcp.artifacts import MCPArtifactService
from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.ecr_reads import ECRReadError, MCPECRReadService
from app.core.config.mcp import MCPSettings
from app.domain.entities.entities import UserRole
from app.infrastructure.database.ecr_models import EcrBatchModel, EcrItemModel
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AgencyModel,
    PassportExportHistoryModel,
    UserModel,
    UserSecurityStateModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.repositories.ecr_read_repository import ECR_COUNT_FIELDS, ECRReadRepository
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes import ecr_checker
from tests.postgresql_schema import create_isolated_postgresql_tables

pytestmark = [pytest.mark.service_integration, pytest.mark.skipif(
    os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required")]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def ecr_postgres(test_settings, record_testsuite_property):
    host, database = os.environ.get("POSTGRES_HOST", "localhost"), os.environ["POSTGRES_DB"]
    if host not in {"127.0.0.1", "localhost"} or not database.startswith("passdetection_ci_"):
        pytest.fail("ECR proof requires a dedicated loopback CI database")
    schema = "manual_review_" + uuid.uuid4().hex
    record_testsuite_property("retained_ecr_postgresql_schema", schema)
    engine = create_async_engine(URL.create("postgresql+asyncpg", username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"], host=host,
        port=int(os.environ.get("POSTGRES_PORT", "5432")), database=database), poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema, "statement_timeout": "15000", "lock_timeout": "5000"}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            # The helper reuses the already installed extension; this lane must
            # not install anything or alter a table in public.
            assert await connection.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='pg_trgm')"))
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await create_isolated_postgresql_tables(connection, schema)
        async with sessions() as session:
            session.add(MCPControlModel(id=1, enabled=True))
            await session.commit()
        settings = test_settings.model_copy(update={"mcp": MCPSettings(enabled=True,
            enabled_capabilities=["mcp:read"], export_families=[])})
        yield SimpleNamespace(engine=engine, sessions=sessions, schema=schema, settings=settings)
    finally:
        await engine.dispose()  # Retain this UUID schema and committed synthetic rows.


def batch(agency, actor, **changes):
    return dict(id=uuid.uuid4(), agency_id=agency, created_by_user_id=actor,
        title="Synthetic ECR", expected_count=1000, status="uploading",
        lease_token=uuid.uuid4(), lease_expires_at=datetime.now(UTC) + timedelta(hours=1),
        created_at=datetime(2026, 1, 1, tzinfo=UTC)) | changes


def item(batch_id, **changes):
    return dict(id=uuid.uuid4(), batch_id=batch_id, client_id=uuid.uuid4(),
        original_filename="synthetic.jpg", content_type="image/jpeg", object_key="PRIVATE-OBJECT",
        sha256="a" * 64, status="queued", result=None, reason=None, model="PRIVATE-MODEL",
        input_tokens=23, output_tokens=7, attempts=1,
        created_at=datetime(2026, 1, 1, tzinfo=UTC)) | changes


@pytest_asyncio.fixture
async def ecr_cohort(ecr_postgres):
    database, now = ecr_postgres, datetime.now(UTC)
    async with database.sessions() as session:
        agencies = [AgencyModel(id=uuid.uuid4(), name="Synthetic ECR", email=f"{uuid.uuid4()}@example.test") for _ in range(2)]
        session.add_all(agencies)
        await session.flush()
        actors = [UserModel(id=uuid.uuid4(), agency_id=agencies[0].id, email=f"{uuid.uuid4()}@example.test",
            full_name="Synthetic ECR actor", hashed_password="unused", role="super_admin", is_active=True) for _ in range(2)]
        session.add_all(actors)
        await session.flush()
        session.add_all([UserSecurityStateModel(user_id=actor.id, session_version=1, credential_state="active",
            mfa_enabled_at=now, mfa_secret_ciphertext="synthetic-not-used") for actor in actors])
        grants = [MCPGrantModel(id=uuid.uuid4(), user_id=actor.id, client_id="global-connects-desktop",
            name="Synthetic ECR read", resource=database.settings.mcp.public_origin + "/mcp",
            capabilities=["mcp:read"], security_version=1, mfa_at=now, created_at=now,
            expires_at=now + timedelta(days=1)) for actor in actors]
        session.add_all(grants)
        batches = [batch(agencies[0].id, actors[0].id), batch(agencies[0].id, actors[1].id),
                   batch(agencies[1].id, actors[0].id)]
        await session.execute(insert(EcrBatchModel), batches)
        pairs = [("queued", None), ("processing", None), ("completed", "ECR"),
                 ("completed", "NA"), ("completed", "NEEDS_REVIEW"), ("failed", None)]
        items = [item(batches[0]["id"], status=status, result=result,
                      reason="Untrusted synthetic text" if result else None) for status, result in pairs]
        await session.execute(insert(EcrItemModel), items)
        await session.commit()
    principals = [MCPPrincipal(grant.id, grant.user_id, grant.client_id, ("mcp:read",), grant.expires_at, grant.resource) for grant in grants]
    return SimpleNamespace(**vars(database), agency=agencies[0].id, other_agency=agencies[1].id,
        actor=actors[0].id, other_actor=actors[1].id, principal=principals[0], other_principal=principals[1],
        batch=batches[0]["id"], peer_batch=batches[1]["id"], foreign_batch=batches[2]["id"],
        items=[row["id"] for row in items])


def service(f, session):
    return MCPECRReadService(session, f.settings)


@contextmanager
def scalar_reads(engine):
    statements = []
    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())
    def forbidden(*_args):
        raise AssertionError("ECR metadata read hydrated a private business ORM row")
    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    for model in (EcrBatchModel, EcrItemModel):
        event.listen(model, "load", forbidden)
        event.listen(model, "refresh", forbidden)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
        for model in (EcrBatchModel, EcrItemModel):
            event.remove(model, "load", forbidden)
            event.remove(model, "refresh", forbidden)


async def effects(session):
    snapshots = [(await session.execute(select(*model.__table__.columns).order_by(model.id))).all()
                 for model in (EcrBatchModel, EcrItemModel)]
    counts = [await session.scalar(select(func.count()).select_from(model)) for model in (
        MCPArtifactModel, MCPOperationModel, PassportExportHistoryModel, WhatsAppMessageLogModel)]
    return snapshots, counts


@pytest.fixture(autouse=True)
def no_storage(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("ECR metadata reads must not initialize storage")
    monkeypatch.setattr(MCPArtifactService, "storage", property(forbidden))
    monkeypatch.setattr(ecr_checker, "MinioStorageRepository", forbidden)


async def test_postgresql_web_scope_counters_scalar_projection_and_no_effects(ecr_cohort):
    f = ecr_cohort
    async with f.sessions() as session:
        before = await effects(session)
        with scalar_reads(f.engine) as statements:
            listing = await service(f, session).list_batches(f.principal)
            detail = await service(f, session).get_batch(f.principal, batch_id=f.batch)
        queries = [query for query in statements if "from ecr_" in query]
        assert queries and not any(query.lstrip().startswith(("insert", "update", "delete")) for query in statements)
        for forbidden in ("object_key", "sha256", "lease_token", "lease_expires_at", "input_tokens", "output_tokens", "attempts", "ecr_items.model"):
            assert not any(forbidden in query for query in queries)
        assert "PRIVATE-" not in json.dumps(detail)
        assert detail["batch"] == next(row for row in listing["items"] if row["batch_id"] == str(f.batch))
        assert {key: detail["batch"][key] for key in ECR_COUNT_FIELDS} == dict(
            total_count=6, processed_count=4, ecr_count=1, na_count=1, review_count=1, failed_count=1)
        assert await effects(session) == before
        actor = await UserRepository(session).get_by_id(f.actor)
        web_list = await ecr_checker.list_ecr_batches(actor, session)
        assert sorted(listing["items"], key=lambda row: row["batch_id"]) == sorted(
            [row.model_dump(mode="json") | {"created_at": row.created_at.isoformat()} for row in web_list], key=lambda row: row["batch_id"])
        web_detail = (await ecr_checker.get_ecr_batch(f.batch, actor, session)).model_dump(mode="json")
        assert [{key: value for key, value in row.items() if key != "created_at"} for row in detail["items"]] == web_detail["items"]
        staff = replace(actor, role=UserRole.AGENCY_STAFF)
        scoped = await ECRReadRepository(session).batches(staff, size=50, cutoff=datetime.now(UTC), after=None)
        assert {row["batch_id"] for row in scoped} == {f.batch}
        assert {row.batch_id for row in await ecr_checker.list_ecr_batches(staff, session)} == {f.batch}


async def test_postgresql_tied_batch_walk_exceeds_100_and_freezes_creation_cutoff(ecr_cohort):
    f = ecr_cohort
    async with f.sessions() as session:
        extra = [batch(f.agency, f.actor) for _ in range(105)]
        await session.execute(insert(EcrBatchModel), extra)
        await session.commit()
        first = await service(f, session).list_batches(f.principal, page_size=50)
        cutoff = first["consistency"]["created_before"]
        await session.rollback()
        async with f.sessions() as writer:
            await writer.execute(insert(EcrBatchModel), [batch(f.agency, f.actor, created_at=datetime.now(UTC) + timedelta(seconds=1))])
            await writer.commit()
        found, page = [], first
        while True:
            found.extend(row["batch_id"] for row in page["items"])
            assert page["consistency"]["created_before"] == cutoff
            assert page["completeness"] == ("partial" if page["has_more"] else "complete")
            if not page["has_more"]:
                assert page["next_cursor"] is None
                break
            page = await service(f, session).list_batches(f.principal, page_size=50, cursor=page["next_cursor"])
        expected = [str(row["id"]) for row in extra] + [str(f.batch), str(f.peer_batch)]
        assert found == sorted(expected, reverse=True) and len(set(found)) == 107


async def test_postgresql_ascending_item_pages_live_counters_and_new_item_cutoff(ecr_cohort):
    f = ecr_cohort
    async with f.sessions() as session:
        page = await service(f, session).get_batch(f.principal, batch_id=f.batch, page_size=2)
        first_counts = page["batch"]["total_count"], page["batch"]["processed_count"]
        await session.rollback()
        async with f.sessions() as writer:
            await writer.execute(update(EcrItemModel).where(EcrItemModel.id == f.items[0]).values(status="completed", result="ECR"))
            await writer.execute(insert(EcrItemModel), [item(f.batch, created_at=datetime.now(UTC) + timedelta(seconds=1))])
            await writer.commit()
        found, results = [], set()
        while True:
            found.extend(row["id"] for row in page["items"])
            for row in page["items"]:
                assert (row["status"] == "completed") == (row["result"] is not None)
                results.add(row["result"])
            if not page["has_more"]:
                break
            page = await service(f, session).get_batch(f.principal, batch_id=f.batch, page_size=2, cursor=page["next_cursor"])
        assert found == sorted(map(str, f.items)) and len(set(found)) == 6
        assert first_counts == (6, 4) and page["batch"]["total_count"] == 7 and page["batch"]["processed_count"] == 5
        assert {"ECR", "NA", "NEEDS_REVIEW"} <= results
        assert page["consistency"]["snapshot_guaranteed"] is False


async def test_postgresql_empty_agency_and_empty_batch_are_complete_reads(ecr_cohort):
    f = ecr_cohort
    async with f.sessions() as session:
        empty = await service(f, session).get_batch(f.principal, batch_id=f.peer_batch)
        assert empty["items"] == [] and empty["batch"]["total_count"] == 0
        assert empty["has_more"] is False and empty["completeness"] == "complete"
        agency = AgencyModel(id=uuid.uuid4(), name="Empty ECR", email=f"{uuid.uuid4()}@example.test")
        session.add(agency)
        await session.flush()
        await session.execute(update(UserModel).where(UserModel.id == f.actor).values(agency_id=agency.id))
        result = await service(f, session).list_batches(f.principal)
        assert result["items"] == [] and result["next_cursor"] is None and result["completeness"] == "complete"
        await session.rollback()


@pytest.mark.parametrize("change", ["revoked", "narrowed", "expired", "inactive_user", "role", "no_agency", "inactive_agency", "wrong_actor"])
async def test_postgresql_current_authority_denies_before_business_reads(ecr_cohort, change):
    f, now = ecr_cohort, datetime.now(UTC)
    async with f.sessions() as session:
        principal = f.principal
        if change in {"revoked", "narrowed", "expired"}:
            values = {"revoked": {"revoked_at": now}, "narrowed": {"capabilities": []},
                      "expired": {"created_at": now - timedelta(days=2), "expires_at": now - timedelta(days=1)}}[change]
            await session.execute(update(MCPGrantModel).where(MCPGrantModel.id == principal.grant_id).values(**values))
        elif change in {"inactive_user", "role", "no_agency"}:
            values = {"inactive_user": {"is_active": False}, "role": {"role": "agency_staff"}, "no_agency": {"agency_id": None}}[change]
            await session.execute(update(UserModel).where(UserModel.id == f.actor).values(**values))
        elif change == "inactive_agency":
            await session.execute(update(AgencyModel).where(AgencyModel.id == f.agency).values(is_active=False))
        else:
            principal = replace(principal, user_id=f.other_actor)
        with scalar_reads(f.engine) as statements, pytest.raises(MCPAuthError):
            await service(f, session).list_batches(principal)
        assert not any("from ecr_" in statement for statement in statements)
        await session.rollback()
        assert len((await service(f, session).list_batches(f.principal))["items"]) == 2


async def test_postgresql_changed_actor_agency_changes_visibility_without_override(ecr_cohort):
    f = ecr_cohort
    async with f.sessions() as session:
        with pytest.raises(ECRReadError, match="ecr_batch_unavailable"):
            await service(f, session).get_batch(f.principal, batch_id=f.foreign_batch)
        await session.execute(update(UserModel).where(UserModel.id == f.actor).values(agency_id=f.other_agency))
        current = await service(f, session).list_batches(f.principal)
        assert current["agency_id"] == str(f.other_agency)
        assert [row["batch_id"] for row in current["items"]] == [str(f.foreign_batch)]
        with pytest.raises(ECRReadError, match="ecr_batch_unavailable"):
            await service(f, session).get_batch(f.principal, batch_id=f.batch)
        await session.rollback()


@pytest.mark.parametrize("binding", ["page_size", "actor", "agency", "query", "batch", "signature"])
async def test_postgresql_cursors_bind_query_actor_agency_page_and_batch(ecr_cohort, binding):
    f = ecr_cohort
    async with f.sessions() as session:
        listing = await service(f, session).list_batches(f.principal, page_size=1)
        detail = await service(f, session).get_batch(f.principal, batch_id=f.batch, page_size=1)
        if binding == "agency":
            await session.execute(update(UserModel).where(UserModel.id == f.actor).values(agency_id=f.other_agency))
        with pytest.raises(ECRReadError, match="ecr_read_invalid_request"):
            if binding in {"batch", "query"}:
                await service(f, session).get_batch(f.principal, batch_id=f.peer_batch if binding == "batch" else f.batch,
                    page_size=1, cursor=detail["next_cursor"] if binding == "batch" else listing["next_cursor"])
            else:
                await service(f, session).list_batches(f.other_principal if binding == "actor" else f.principal,
                    page_size=2 if binding == "page_size" else 1,
                    cursor=listing["next_cursor"] + "x" if binding == "signature" else listing["next_cursor"])
        await session.rollback()


async def test_postgresql_maximum_unicode_fields_and_real_response_budget(ecr_cohort):
    f = ecr_cohort
    async with f.sessions() as session:
        await session.execute(update(EcrBatchModel).where(EcrBatchModel.id == f.batch).values(title="😀" * 160))
        await session.execute(update(EcrItemModel).where(EcrItemModel.batch_id == f.batch).values(original_filename="😀" * 255, reason="界" * 255))
        result = await service(f, session).get_batch(f.principal, batch_id=f.batch, page_size=5)
        assert result["batch"]["title"] == "😀" * 160
        assert all(row["original_filename"] == "😀" * 255 and row["reason"] == "界" * 255 for row in result["items"])
        assert len(json.dumps(result, ensure_ascii=True).encode()) <= result["maximum_response_bytes"]
        await session.execute(insert(EcrItemModel), [item(f.batch, original_filename="😀" * 255, reason="😀" * 255) for _ in range(94)])
        with scalar_reads(f.engine), pytest.raises(ECRReadError, match="ecr_read_limit"):
            await service(f, session).get_batch(f.principal, batch_id=f.batch, page_size=100)
        await session.rollback()
        assert len((await service(f, session).get_batch(f.principal, batch_id=f.batch))["items"]) == 6


@pytest.mark.parametrize(("table", "field", "limit"), [("ecr_batches", "title", 160), ("ecr_items", "original_filename", 255), ("ecr_items", "reason", 255)])
async def test_postgresql_oversize_source_is_sentinel_bounded_not_silently_truncated(ecr_cohort, table, field, limit):
    f = ecr_cohort
    async with f.sessions() as session:
        # Simulate legacy schema drift only inside a transaction in our schema.
        # Rollback restores both DDL and fixture text; no source row is removed.
        await session.execute(text(f'ALTER TABLE "{f.schema}".{table} ALTER COLUMN {field} TYPE TEXT'))
        model, identifier = (EcrBatchModel, f.batch) if table == "ecr_batches" else (EcrItemModel, f.items[0])
        await session.execute(update(model).where(model.id == identifier).values(**{field: "😀" * (limit + 1)}))
        with scalar_reads(f.engine) as statements, pytest.raises(ECRReadError, match="ecr_read_limit"):
            await service(f, session).get_batch(f.principal, batch_id=f.batch)
        assert any("substr(" in query and field in query for query in statements)
        await session.rollback()
        assert len((await service(f, session).get_batch(f.principal, batch_id=f.batch))["items"]) == 6


@pytest.mark.parametrize("table", ["ecr_batches", "ecr_items"])
async def test_postgresql_blocked_query_deadline_rolls_back_and_retry_succeeds(ecr_cohort, monkeypatch, table):
    f = ecr_cohort
    async with f.sessions() as holder, f.sessions() as reader:
        before = await effects(reader)
        await reader.rollback()
        await holder.execute(text(f'LOCK TABLE "{f.schema}".{table} IN ACCESS EXCLUSIVE MODE'))
        await reader.execute(text("SELECT 1"))
        monkeypatch.setattr(ecr_reads, "READ_TIMEOUT_SECONDS", 0.15)
        began = time.monotonic()
        with pytest.raises(ECRReadError, match="ecr_read_busy"):
            await service(f, reader).get_batch(f.principal, batch_id=f.batch)
        assert time.monotonic() - began < 3
        await reader.rollback()
        await holder.rollback()
        monkeypatch.setattr(ecr_reads, "READ_TIMEOUT_SECONDS", 5)
        result = await asyncio.wait_for(service(f, reader).get_batch(f.principal, batch_id=f.batch), 3)
        assert result["batch"]["total_count"] == 6 and await effects(reader) == before


async def test_postgresql_external_cancellation_during_authority_wait_releases_transaction(ecr_cohort):
    f = ecr_cohort
    async with f.sessions() as holder, f.sessions() as reader:
        await holder.execute(select(UserModel.id).where(UserModel.id == f.actor).with_for_update())
        waiting = asyncio.Event()
        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            if "FOR SHARE OF users" in statement:
                waiting.set()
        event.listen(f.engine.sync_engine, "before_cursor_execute", capture)
        task = asyncio.create_task(service(f, reader).list_batches(f.principal))
        try:
            await asyncio.wait_for(waiting.wait(), 3)
            assert not task.done()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await reader.rollback()
            await holder.rollback()
            assert len((await asyncio.wait_for(service(f, reader).list_batches(f.principal), 3))["items"]) == 2
        finally:
            event.remove(f.engine.sync_engine, "before_cursor_execute", capture)
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
