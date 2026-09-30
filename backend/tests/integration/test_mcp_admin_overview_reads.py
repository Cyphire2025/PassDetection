"""Canonical scalar parity, all-or-nothing bounds and mandatory authority."""

import asyncio
import json
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, func, select

from app.application.mcp import admin_overview_reads
from app.application.mcp.admin_overview_reads import (
    AdminOverviewReadError,
    MCPAdminOverviewReadService,
)
from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.credentials import MCPAuthError
from app.application.use_cases.admin_overview import ADMIN_OVERVIEW_FIELDS
from app.domain.entities.entities import UserRole
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportExportHistoryModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.repositories.admin_overview_repository import AdminOverviewRepository
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes import admin
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture
from tests.mcp_admin_overview_fixtures import (
    AGENCY_COUNTS,
    GLOBAL_COUNTS,
    NULL_AGENCY_COUNTS,
    seed_admin_overview,
)


@pytest.fixture
async def overview(operations_fixture):
    f = operations_fixture
    data = await seed_admin_overview(f[0], f[2])
    f[3][0].capabilities = ["mcp:read"]
    await f[0].commit()
    return f, data


def principal(f):
    grant = f[3][0]
    return MCPPrincipal(grant.id, f[2].id, grant.client_id, tuple(grant.capabilities), grant.expires_at, grant.resource)


async def test_global_parity_all_statuses_retained_parents_and_no_agency(overview):
    f, data = overview
    for agency_id in (None, data.agencies[0].id, data.agencies[1].id):
        f[2].agency_id = agency_id
        await f[0].flush()
        actor = await UserRepository(f[0]).get_by_id(f[2].id)
        web = await admin.get_admin_overview(actor, f[0])
        actual = await MCPAdminOverviewReadService(f[0], f[1]).get_overview(principal(f))
        assert {name: actual[name] for name in ADMIN_OVERVIEW_FIELDS} == web.model_dump() == GLOBAL_COUNTS
        assert actual["scope"] == "platform_global" and actual["completeness"] == "complete"
        assert actual["consistency"] == {"mode": "live_multi_query", "snapshot_guaranteed": False}
        assert not any(marker in json.dumps(actual) for marker in ("SECRET", "PRIVATE", str(f[2].id)))
    for model in (MCPOperationModel, MCPArtifactModel, PassportExportHistoryModel):
        assert await f[0].scalar(select(func.count()).select_from(model)) == 0


async def test_website_agency_admin_scope_including_exact_null_semantics(overview):
    f, data = overview
    actor = await UserRepository(f[0]).get_by_id(f[2].id)
    actor.role = UserRole.AGENCY_ADMIN
    for agency in data.agencies:
        actor.agency_id = agency.id
        assert (await admin.get_admin_overview(actor, f[0])).model_dump() == AGENCY_COUNTS
    actor.agency_id = None
    assert (await admin.get_admin_overview(actor, f[0])).model_dump() == NULL_AGENCY_COUNTS


async def test_shared_repository_is_exactly_seven_scalar_queries_no_private_hydration(overview):
    f, _ = overview
    statements, hydrated = [], []
    models = (AgencyModel, UserModel, ClientGroupModel, PassportSubmissionModel)
    def capture(_conn, _cursor, sql, *_args):
        statements.append(sql.lower())
    def loaded(*_args):
        hydrated.append(True)
    engine = f[0].bind.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    for model in models:
        event.listen(model, "load", loaded)
        event.listen(model, "refresh", loaded)
    try:
        assert await AdminOverviewRepository(f[0]).overview(role=UserRole.SUPER_ADMIN, agency_id=None) == GLOBAL_COUNTS
    finally:
        event.remove(engine, "before_cursor_execute", capture)
        for model in models:
            event.remove(model, "load", loaded)
            event.remove(model, "refresh", loaded)
    assert len(statements) == 7 and all(sql.startswith("select count(*)") for sql in statements)
    assert not hydrated
    assert not any(field in " ".join(statements) for field in
        ("hashed_password", "email", "extracted_fields", "notes", "token", "platform_settings", "image_s3_key"))


async def test_empty_business_tables_return_zero_not_unavailable(operations_fixture):
    f = operations_fixture
    f[3][0].capabilities = ["mcp:read"]
    await f[0].commit()
    result = await MCPAdminOverviewReadService(f[0], f[1]).get_overview(principal(f))
    assert {name: result[name] for name in ADMIN_OVERVIEW_FIELDS} == {name: int(name == "users") for name in ADMIN_OVERVIEW_FIELDS}


@pytest.mark.parametrize("counts", [
    {**GLOBAL_COUNTS, "users": -1}, {**GLOBAL_COUNTS, "users": True}, {**GLOBAL_COUNTS, "users": 2**63},
    {**GLOBAL_COUNTS, "users": 1.0}, {**GLOBAL_COUNTS, "extra_private": "SECRET"}, {"agencies": 2},
])
async def test_invalid_count_or_shape_fails_whole_observation(overview, monkeypatch, counts):
    f, _ = overview
    monkeypatch.setattr(AdminOverviewRepository, "overview", AsyncMock(return_value=counts))
    with pytest.raises(AdminOverviewReadError, match="admin_overview_limit"):
        await MCPAdminOverviewReadService(f[0], f[1]).get_overview(principal(f))


async def test_complete_escaped_envelope_budget_and_valid_max_counter(overview, monkeypatch):
    f, _ = overview
    service = MCPAdminOverviewReadService(f[0], f[1])
    result = await service.get_overview(principal(f))
    monkeypatch.setattr(admin_overview_reads, "MAX_ADMIN_OVERVIEW_RESPONSE_BYTES", len(json.dumps(result).encode()) + 1)
    with pytest.raises(AdminOverviewReadError, match="admin_overview_limit"):
        await service.get_overview(principal(f))
    monkeypatch.setattr(admin_overview_reads, "MAX_ADMIN_OVERVIEW_RESPONSE_BYTES", 8192)
    f[1].app_revision = "界" * 1500
    with pytest.raises(AdminOverviewReadError, match="admin_overview_limit"):
        await service.get_overview(principal(f))
    f[1].app_revision = "1" * 40
    monkeypatch.setattr(AdminOverviewRepository, "overview", AsyncMock(return_value={name: 2**63-1 for name in ADMIN_OVERVIEW_FIELDS}))
    result = await service.get_overview(principal(f))
    assert result["users"] == 2**63-1


@pytest.mark.parametrize("boundary", ["authority", "source"])
async def test_whole_deadline_covers_authority_and_query(overview, monkeypatch, boundary):
    f, _ = overview
    async def slow(*_args, **_kwargs):
        await asyncio.sleep(1)
    monkeypatch.setattr(admin_overview_reads, "ADMIN_OVERVIEW_TIMEOUT_SECONDS", 0.01)
    target = admin_overview_reads.MCPAuthorizationService if boundary == "authority" else AdminOverviewRepository
    monkeypatch.setattr(target, "require_grant" if boundary == "authority" else "overview", slow)
    with pytest.raises(AdminOverviewReadError, match="admin_overview_busy"):
        await MCPAdminOverviewReadService(f[0], f[1]).get_overview(principal(f))


async def test_foreign_principal_denied_before_source_read(overview, monkeypatch):
    f, data = overview
    query = AsyncMock(side_effect=AssertionError("Unauthorized projection"))
    monkeypatch.setattr(AdminOverviewRepository, "overview", query)
    with pytest.raises(MCPAuthError):
        await MCPAdminOverviewReadService(f[0], f[1]).get_overview(replace(principal(f), user_id=data.users[0].id))
    query.assert_not_awaited()
