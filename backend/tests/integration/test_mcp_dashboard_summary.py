"""Actual SQL and SDK/HTTP dashboard parity, authority and bounded read effects."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event, func, select

from app.application.mcp import dashboard_reads
from app.application.mcp.dashboard_reads import MCPDashboardReadService
from app.application.use_cases.dashboard.get_dashboard_stats_use_case import (
    GetDashboardStatsUseCase,
)
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES, UserRole
from app.domain.value_objects.dashboard_summary import DashboardProjectionLimitError
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    ManagerGroupAccessModel,
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
from tests.integration.test_mcp_authorization import (
    call_mcp,
    connect,
)
from tests.integration.test_mcp_authorization import (
    mcp_fixture as mcp_fixture,
)


@pytest.fixture
async def dashboard_data(mcp_fixture):
    client, session, settings, user, security, dashboard = mcp_fixture
    agency = AgencyModel(id=uuid.uuid4(), name="Dashboard agency", email="dashboard@example.test")
    other = AgencyModel(id=uuid.uuid4(), name="Other", email="other@example.test")
    session.add_all([agency, other])
    await session.flush()
    user.agency_id = agency.id
    staff = UserModel(id=uuid.uuid4(), agency_id=agency.id, email="staff@example.test",
        full_name="Staff", hashed_password="unused", role="agency_staff", is_active=True)
    session.add(staff)
    await session.flush()
    groups = {}
    for name, status in [("owned", "active"), ("assigned", "active"), ("unassigned", "active"),
                         ("closed", "closed"), ("archived", "archived"), ("deleted", "deleted"),
                         ("empty_expired", "active"), ("other", "active")]:
        group = ClientGroupModel(id=uuid.uuid4(), agency_id=other.id if name == "other" else agency.id,
            name=name, token=uuid.uuid4().hex, status=status,
            created_by_user_id=staff.id if name == "owned" else user.id,
            return_date=(datetime.now(UTC)-timedelta(days=30)).date() if name == "empty_expired" else None,
            deleted_at=datetime.now(UTC) if name == "deleted" else None)
        groups[name] = group
        session.add(group)
    await session.flush()
    session.add(ManagerGroupAccessModel(id=uuid.uuid4(), manager_id=staff.id,
        group_id=groups["assigned"].id, agency_id=agency.id))
    stamp = datetime(2026, 9, 1, tzinfo=UTC)
    submissions = []
    specs = [("owned", state) for state in OFFICE_VISIBLE_PASSPORT_STATUS_VALUES]
    specs += [("assigned", "client_submitted"), ("unassigned", "submitted"),
              ("closed", "needs_review"), ("archived", "confirmed"), ("deleted", "confirmed"),
              ("owned", "review_required"), ("owned", "pending_upload"), ("other", "confirmed")]
    for index, (group_name, state) in enumerate(specs, 1):
        row = PassportSubmissionModel(id=uuid.UUID(f"aaaaaaaa-0000-0000-0000-{index:012x}"), agency_id=groups[group_name].agency_id,
            group_id=groups[group_name].id, client_name=f"Person {index}", client_email=f"person{index}@example.test",
            image_s3_key="private/document-key", status=state, overall_confidence=0.9,
            created_at=stamp if index <= 6 else stamp-timedelta(days=1),
            extracted_fields={"PRIVATE-JSON": "x" * 20000})
        submissions.append(row)
        session.add(row)
    await session.commit()
    return SimpleNamespace(client=client, session=session, settings=settings, user=user, security=security,
        dashboard=dashboard, agency=agency, other=other, staff=staff, groups=groups, submissions=submissions,
        fixture=mcp_fixture)


async def read_summary(f):
    return await MCPDashboardReadService(f.session, cursor_secret=f.settings.app_secret_key).get_summary(f.user.id)


async def assert_no_business_effects(session):
    for model in (MCPOperationModel, MCPArtifactModel, PassportExportHistoryModel, WhatsAppMessageLogModel):
        assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_http_summary_matches_actual_website_and_fixed_tied_timestamp_preview(dashboard_data):
    f = dashboard_data
    _, tokens = await connect(f.fixture)
    before = await f.session.scalar(select(func.count()).select_from(PassportSubmissionModel))
    response = await f.client.get("/api/v1/dashboard/stats", headers={"Authorization": f"Bearer {f.dashboard}"})
    assert response.status_code == 200, response.text
    website = response.json()
    assert {key: website[key] for key in ("total_passports", "pending_review", "confirmed", "active_links")} == {
        "total_passports": 11, "pending_review": 6, "confirmed": 3, "active_links": 4}
    assert [item["id"] for item in website["recent_submissions"]] == [str(uuid.UUID(f"aaaaaaaa-0000-0000-0000-{i:012x}")) for i in (6, 5, 4, 3, 2)]
    response = await call_mcp(f.client, tokens["access_token"], name="get_dashboard_summary", arguments={})
    result = response.json()["result"]["structuredContent"]
    for row in website["recent_submissions"]:
        row["created_at"] = row["created_at"].removesuffix("Z").removesuffix("+00:00") + "+00:00"
    assert {key: result[key] for key in website} == website
    assert result["agency_id"] == str(f.agency.id) and result["recent_submissions_limit"] == 5
    assert result["consistency"]["snapshot_guaranteed"] is False and result["completeness"] == "complete"
    assert {"observed_at", "environment", "revision", "audit_id"} <= result.keys()
    assert "PRIVATE-JSON" not in json.dumps(result) and "private/document-key" not in json.dumps(result)
    tool = next(item for item in await f.client._transport.app.state.mcp_server.list_tools() if item.name == "get_dashboard_summary")
    assert tool.meta == {"capability": "mcp:read"} and tool.annotations.read_only_hint
    assert tool.input_schema["properties"] == {} and tool.annotations.destructive_hint is False
    assert "get_dashboard_summary" not in f.client._transport.app.state.mcp_operations
    audit = await f.session.get(AuditLogModel, uuid.UUID(result["audit_id"]))
    assert audit.result == "success" and audit.metadata_json == {"capability": "mcp:read", "failure_category": None}
    assert await f.session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == before
    await assert_no_business_effects(f.session)


@pytest.mark.parametrize("role,counts", [
    (UserRole.AGENCY_ADMIN, (10, 6, 3, 4)), (UserRole.AGENCY_MANAGER, (10, 6, 3, 4)),
    (UserRole.AGENCY_STAFF, (7, 4, 3, 2)),
])
async def test_shared_website_projection_preserves_role_archive_and_assignment_scope(dashboard_data, role, counts):
    f = dashboard_data
    f.staff.role = role.value
    await f.session.commit()
    actor = await UserRepository(f.session).get_by_id(f.staff.id)
    repository = PassportSubmissionRepository(f.session)
    created = actor.id if role == UserRole.AGENCY_STAFF else None
    legacy = await repository.list_by_agency(f.agency.id, limit=5, status_filter="client_submitted",
        exclude_archived_groups=True, created_by_user_id=created, visible_to_user=actor)
    result = await GetDashboardStatsUseCase(repository, ClientGroupRepository(f.session)).execute(
        f.agency.id, created_by_user_id=created, visible_to_user=actor)
    assert (result.total_passports, result.pending_review, result.confirmed, result.active_links) == counts
    assert [row.id for row in result.recent_submissions] == [row.id for row in legacy]
    assert [row.client_name for row in result.recent_submissions] == [row.client_name for row in legacy]


async def test_no_agency_returns_zero_without_reading_business_tables(dashboard_data):
    f = dashboard_data
    f.user.agency_id = None
    await f.session.commit()
    statements = []
    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())
    engine = f.session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = await read_summary(f)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert result["agency_id"] is None and result["recent_submissions"] == []
    assert all(result[key] == 0 for key in ("total_passports", "pending_review", "confirmed", "active_links"))
    assert not any("passport_submissions" in statement or "client_groups" in statement for statement in statements)
    _, tokens = await connect(f.fixture)
    website = await f.client.get("/api/v1/dashboard/stats", headers={"Authorization": f"Bearer {f.dashboard}"})
    response = await call_mcp(f.client, tokens["access_token"], name="get_dashboard_summary", arguments={})
    body = response.json()["result"]["structuredContent"]
    assert {key: body[key] for key in website.json()} == website.json()


async def test_projection_loads_no_passport_or_group_orm_and_exactly_six_columns(dashboard_data):
    f = dashboard_data
    statements = []
    def forbidden(*_args):
        raise AssertionError("Dashboard loaded a full business ORM row")
    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())
    for model in (PassportSubmissionModel, ClientGroupModel):
        event.listen(model, "load", forbidden)
        event.listen(model, "refresh", forbidden)
    engine = f.session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        await read_summary(f)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
        for model in (PassportSubmissionModel, ClientGroupModel):
            event.remove(model, "load", forbidden)
            event.remove(model, "refresh", forbidden)
    business = [statement for statement in statements if "passport_submissions" in statement or "client_groups" in statement]
    assert len(business) == 5
    preview = business[-1]
    assert "substr(" in preview and "limit" in preview and "created_at desc" in preview and ".id desc" in preview
    assert not any(column in preview for column in ("extracted_fields", "confirmed_fields", "image_s3_key", "staff_metadata"))
    assert not any(statement.lstrip().startswith(("insert", "update", "delete")) for statement in statements)


@pytest.mark.parametrize("field", ["client_name", "client_email"])
async def test_oversized_retained_projection_is_bounded_and_explicit(dashboard_data, field):
    f = dashboard_data
    setattr(f.submissions[5], field, "PRIVATE-" + "界" * 10000)
    await f.session.commit()
    with pytest.raises(DashboardProjectionLimitError):
        await read_summary(f)
    _, tokens = await connect(f.fixture)
    response = await call_mcp(f.client, tokens["access_token"], name="get_dashboard_summary", arguments={})
    result = response.json()["result"]["structuredContent"]
    assert result["error"] == "dashboard_summary_limit" and result["completeness"] == "unavailable"
    assert "recent_submissions" not in result and "PRIVATE" not in json.dumps(result) and "界" not in json.dumps(result)
    await assert_no_business_effects(f.session)


async def test_deadline_returns_static_failure_and_no_partial_counts(dashboard_data, monkeypatch):
    f = dashboard_data
    _, tokens = await connect(f.fixture)
    actor = await UserRepository(f.session).get_by_id(f.user.id)
    async def current_actor(*_args, **_kwargs):
        return actor
    async def slow(*_args, **_kwargs):
        await asyncio.sleep(10)
    # Isolate the timeout at the blocked count. Cancelling an SQLite driver
    # call discards its connection and therefore its entire in-memory database;
    # retained PostgreSQL qualification covers actual query cancellation.
    monkeypatch.setattr(MCPDashboardReadService, "_actor", current_actor)
    monkeypatch.setattr(dashboard_reads, "DASHBOARD_READ_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(PassportSubmissionRepository, "count_by_agency", slow)
    response = await call_mcp(f.client, tokens["access_token"], name="get_dashboard_summary", arguments={})
    result = response.json()["result"]["structuredContent"]
    assert result["error"] == "operation_failed" and "total_passports" not in result
    audit = await f.session.get(AuditLogModel, uuid.UUID(result["audit_id"]))
    assert audit.metadata_json["failure_category"] == "timeout"
    await assert_no_business_effects(f.session)


async def test_response_budget_failure_is_explicit_and_never_partial(dashboard_data, monkeypatch):
    f = dashboard_data
    _, tokens = await connect(f.fixture)
    monkeypatch.setattr(dashboard_reads, "MAX_DASHBOARD_RESPONSE_BYTES", 1)
    response = await call_mcp(f.client, tokens["access_token"], name="get_dashboard_summary", arguments={})
    body = response.json()["result"]["structuredContent"]
    assert body["error"] == "dashboard_summary_limit" and body["completeness"] == "unavailable"
    assert "total_passports" not in body and "recent_submissions" not in body
    await assert_no_business_effects(f.session)


@pytest.mark.parametrize("change", ["revoked", "narrowed", "role", "inactive", "deleted", "session", "disabled"])
async def test_current_authority_denies_before_reading_dashboard(dashboard_data, monkeypatch, change):
    f = dashboard_data
    _, tokens = await connect(f.fixture)
    grant = await f.session.scalar(select(MCPGrantModel))
    if change == "revoked":
        grant.revoked_at = datetime.now(UTC)
    elif change == "narrowed":
        grant.capabilities = ["mcp:export"]
    elif change == "role":
        f.user.role = "agency_admin"
    elif change == "inactive":
        f.user.is_active = False
    elif change == "deleted":
        f.user.deleted_at = datetime.now(UTC)
    elif change == "session":
        f.security.session_version += 1
    else:
        (await f.session.get(MCPControlModel, 1)).enabled = False
    await f.session.commit()
    async def forbidden(*_args, **_kwargs):
        raise AssertionError("Unauthorized dashboard query")
    monkeypatch.setattr(PassportSubmissionRepository, "count_by_agency", forbidden)
    response = await call_mcp(f.client, tokens["access_token"], name="get_dashboard_summary", arguments={})
    if response.status_code != 401:
        result = response.json()["result"]["structuredContent"]
        assert result["error"] == "access_denied" and "total_passports" not in result
    await assert_no_business_effects(f.session)
