"""Canonical analytics SQL/HTTP/SDK parity; PostgreSQL owns DATE timezone proof."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.dialects.postgresql import DATE
from sqlalchemy.dialects.sqlite.base import SQLiteCompiler

from app.application.mcp import analytics_reads
from app.application.mcp.analytics_reads import AnalyticsReadError, MCPPassportAnalyticsReadService
from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError
from app.application.use_cases.passports.passport_analytics import GetPassportAnalyticsSummary
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES, UserRole
from app.domain.value_objects.passport_analytics import PassportAnalyticsSummary
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_models import MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportExportHistoryModel,
    PassportSubmissionModel,
)
from app.infrastructure.repositories.passport_analytics_repository import (
    PassportAnalyticsRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes.analytics import get_analytics_summary
from tests.integration.test_mcp_authorization import call_mcp, connect
from tests.integration.test_mcp_authorization import mcp_fixture as mcp_fixture


@pytest.fixture
async def analytics_data(mcp_fixture, monkeypatch):
    # SQLite CAST(timestamp AS DATE) returns only an integer year. This test-only
    # dialect shim renders date(timestamp); production retains PostgreSQL CAST.
    original_cast = SQLiteCompiler.visit_cast

    def sqlite_date(compiler, clause, **kwargs):
        if isinstance(clause.type, DATE):
            return "date(" + compiler.process(clause.clause, **kwargs) + ")"
        return original_cast(compiler, clause, **kwargs)

    monkeypatch.setattr(SQLiteCompiler, "visit_cast", sqlite_date)
    client, session, settings, user, security, dashboard = mcp_fixture
    agencies = [
        AgencyModel(id=uuid.uuid4(), name="PRIVATE", email=f"{uuid.uuid4()}@example.test")
        for _ in range(2)
    ]
    session.add_all(agencies)
    await session.flush()
    user.agency_id = agencies[0].id
    groups = [
        ClientGroupModel(
            id=uuid.uuid4(),
            agency_id=agency.id,
            name="PRIVATE group",
            token=uuid.uuid4().hex,
            status="active",
            created_by_user_id=user.id,
        )
        for agency in agencies
    ]
    session.add_all(groups)
    await session.flush()
    now = datetime.now(UTC)
    values = [-0.2, 0.74, 0.75, 0.899, 0.8995, 0.9, 1.2, None]
    passports = []
    for index, confidence in enumerate(values):
        passports.append(
            PassportSubmissionModel(
                id=uuid.uuid4(),
                agency_id=agencies[index % 2].id,
                client_name="PRIVATE",
                client_email="PRIVATE@example.test",
                image_s3_key="PRIVATE-OBJECT",
                extracted_fields={"PRIVATE": "x" * 20000},
                overall_confidence=confidence,
                status=OFFICE_VISIBLE_PASSPORT_STATUS_VALUES[
                    index % len(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES)
                ],
                created_at=now - timedelta(days=2),
                updated_at=now,
            )
        )
    passports.extend(
        [
            PassportSubmissionModel(
                id=uuid.uuid4(),
                agency_id=agencies[1].id,
                client_name="PRIVATE future",
                image_s3_key="private",
                status="confirmed",
                overall_confidence=0.5,
                created_at=now + timedelta(days=400),
            ),
            PassportSubmissionModel(
                id=uuid.uuid4(),
                agency_id=agencies[0].id,
                client_name="PRIVATE old",
                image_s3_key="private",
                status="confirmed",
                overall_confidence=0.5,
                created_at=now - timedelta(days=400),
            ),
            PassportSubmissionModel(
                id=uuid.uuid4(),
                agency_id=agencies[0].id,
                client_name="PRIVATE excluded",
                image_s3_key="private",
                status="pending_upload",
                overall_confidence=0.5,
                created_at=now,
            ),
        ]
    )
    for passport in passports:
        passport.group_id = next(
            group.id for group in groups if group.agency_id == passport.agency_id
        )
    session.add_all(passports)
    await session.commit()
    _, tokens = await connect(mcp_fixture)
    principal = await MCPAuthorizationService(session, settings).verify_access(
        tokens["access_token"]
    )
    await session.commit()
    return SimpleNamespace(
        client=client,
        session=session,
        settings=settings,
        user=user,
        security=security,
        dashboard=dashboard,
        agencies=agencies,
        groups=groups,
        passports=passports,
        values=values,
        now=now,
        tokens=tokens,
        principal=principal,
    )


def service(f):
    return MCPPassportAnalyticsReadService(f.session, f.settings)


async def test_actual_http_sdk_canonical_global_parity_and_confidence_gap(analytics_data):
    f = analytics_data
    web = await f.client.get(
        "/api/v1/analytics/summary", headers={"Authorization": f"Bearer {f.dashboard}"}
    )
    assert web.status_code == 200, web.text
    value = (
        await call_mcp(
            f.client, f.tokens["access_token"], name="get_passport_analytics_summary", arguments={}
        )
    ).json()["result"]["structuredContent"]
    assert {key: value[key] for key in web.json()} == web.json()
    assert sum(value["status_counts"].values()) == 9
    assert value["confidence_buckets"] == {"high": 2, "medium": 2, "low": 3, "missing": 1}
    assert sum(value["confidence_buckets"].values()) == 8  # 0.8995 is deliberately unbucketed.
    assert value["average_confidence"] == round(
        sum(x for x in f.values if x is not None) / 8 + 0.5 / 8, 3
    )
    assert len(value["submissions_by_day"]) == 2 and value["window_end"] is None
    assert value["agency_scope"] == "all_agencies" and value["days"] == 30
    assert not value["consistency"]["atomic_snapshot_guaranteed"]
    assert "PRIVATE" not in json.dumps(value)
    tools = {
        tool.name: tool for tool in await f.client._transport.app.state.mcp_server.list_tools()
    }
    tool = tools["get_passport_analytics_summary"]
    assert tool.meta == {"capability": "mcp:read"} and tool.annotations.read_only_hint
    assert set(tool.input_schema["properties"]) == {"days"}
    assert "get_passport_analytics_summary" not in f.client._transport.app.state.mcp_operations


async def test_superadmin_without_agency_retains_cross_agency_summary(analytics_data):
    f = analytics_data
    f.user.agency_id = None
    await f.session.commit()
    value = await service(f).summary(f.principal)
    assert sum(value["status_counts"].values()) == 9 and value["agency_scope"] == "all_agencies"


async def test_empty_global_window_returns_zero_buckets_and_null_average(analytics_data):
    f = analytics_data
    for passport in f.passports:
        passport.status = "pending_upload"
    await f.session.commit()
    value = await service(f).summary(f.principal)
    assert value["status_counts"] == value["submissions_by_day"] == {}
    assert value["confidence_buckets"] == {"high": 0, "medium": 0, "low": 0, "missing": 0}
    assert value["average_confidence"] is None and value["completeness"] == "complete"


async def test_inactive_agencies_and_retained_deleted_groups_are_not_new_filters(analytics_data):
    f = analytics_data
    for agency in f.agencies:
        agency.is_active = False
    for group in f.groups:
        group.status = "deleted"
        group.deleted_at = datetime.now(UTC)
    await f.session.commit()
    value = await service(f).summary(f.principal)
    assert sum(value["status_counts"].values()) == 9


async def test_shared_website_non_superadmin_own_agency_and_empty_scope(analytics_data):
    f = analytics_data
    actor = await UserRepository(f.session).get_by_id(f.user.id)
    actor.role = UserRole.AGENCY_ADMIN
    own = await get_analytics_summary(current_user=actor, session=f.session, days=30)
    assert sum(own.status_counts.values()) == 4
    actor.agency_id = None
    empty = await get_analytics_summary(current_user=actor, session=f.session, days=30)
    assert empty.model_dump() == {
        "status_counts": {},
        "confidence_buckets": {},
        "submissions_by_day": {},
        "average_confidence": None,
    }


@pytest.mark.parametrize(
    "days,expected", [(0, 1), (-100000, 1), (366, 365), (100000, 365), (30, 30)]
)
async def test_day_clamp_matches_website_and_keeps_future_rows(analytics_data, days, expected):
    f = analytics_data
    value = await service(f).summary(f.principal, days=days)
    web = await get_analytics_summary(
        current_user=await UserRepository(f.session).get_by_id(f.user.id),
        session=f.session,
        days=days,
    )
    assert {key: value[key] for key in web.model_dump()} == web.model_dump()
    assert value["days"] == expected
    assert (f.now - datetime.fromisoformat(value["window_start"])).days in {expected - 1, expected}
    assert any(day > f.now.date().isoformat() for day in value["submissions_by_day"])


async def test_exact_lower_boundary_and_no_upper_bound_use_case(analytics_data):
    f = analytics_data
    captured = []

    class Reader:
        async def aggregate(self, *, since, agency_id):
            captured.append((since, agency_id))
            return PassportAnalyticsSummary(
                {}, {"high": 0, "medium": 0, "low": 0, "missing": 0}, {}, None
            )

    actor = await UserRepository(f.session).get_by_id(f.user.id)
    result, since, days = await GetPassportAnalyticsSummary(Reader()).execute(actor, 30, now=f.now)
    assert (
        captured == [(f.now - timedelta(days=30), None)] and since == captured[0][0] and days == 30
    )
    assert result.average_confidence is None


@pytest.mark.parametrize(
    "state", ["role", "inactive", "deleted", "revoked", "capability", "security", "principal"]
)
async def test_current_authority_denied(analytics_data, state):
    f = analytics_data
    grant = await f.session.get(MCPGrantModel, f.principal.grant_id)
    if state == "role":
        f.user.role = "agency_admin"
    if state == "inactive":
        f.user.is_active = False
    if state == "deleted":
        f.user.deleted_at = datetime.now(UTC)
    if state == "revoked":
        grant.revoked_at = datetime.now(UTC)
    if state == "capability":
        grant.capabilities = ["mcp:export"]
    if state == "security":
        f.security.session_version += 1
    await f.session.commit()
    principal = replace(f.principal, user_id=uuid.uuid4()) if state == "principal" else f.principal
    with pytest.raises(MCPAuthError):
        await service(f).summary(principal)


async def test_only_three_scalar_analytics_queries_no_private_columns_or_effects(analytics_data):
    f = analytics_data
    statements = []

    def capture(_c, _cur, statement, *_args):
        statements.append(statement.lower())

    def forbid(*args):
        raise AssertionError("Passport ORM hydration is forbidden")

    event.listen(f.session.get_bind(), "before_cursor_execute", capture)
    event.listen(PassportSubmissionModel, "load", forbid)
    event.listen(PassportSubmissionModel, "refresh", forbid)
    try:
        await service(f).summary(f.principal)
    finally:
        event.remove(f.session.get_bind(), "before_cursor_execute", capture)
        event.remove(PassportSubmissionModel, "load", forbid)
        event.remove(PassportSubmissionModel, "refresh", forbid)
    queries = [q for q in statements if "from passport_submissions" in q]
    assert len(queries) == 3 and "limit" in queries[-1]
    for field in (
        "extracted_fields",
        "confirmed_fields",
        "client_name",
        "client_email",
        "image_s3_key",
        "passport_submissions.id",
    ):
        assert not any(field in q for q in queries)
    assert not any(q.lstrip().startswith(("insert", "update", "delete")) for q in statements)
    for model in (MCPOperationModel, MCPArtifactModel, PassportExportHistoryModel):
        assert await f.session.scalar(select(func.count()).select_from(model)) == 0


async def test_actual_day_materialization_has_sentinel_and_website_default_unbounded(
    analytics_data,
):
    f = analytics_data
    for i in range(365):
        f.session.add(
            PassportSubmissionModel(
                id=uuid.uuid4(),
                agency_id=f.agencies[0].id,
                group_id=f.groups[0].id,
                client_name="PRIVATE",
                image_s3_key="private",
                status="confirmed",
                created_at=f.now + timedelta(days=500 + i),
            )
        )
    await f.session.commit()
    with pytest.raises(AnalyticsReadError, match="analytics_read_limit"):
        await service(f).summary(f.principal)
    actor = await UserRepository(f.session).get_by_id(f.user.id)
    value, _, _ = await GetPassportAnalyticsSummary(PassportAnalyticsRepository(f.session)).execute(
        actor
    )
    assert len(value.submissions_by_day) == 367


@pytest.mark.parametrize(
    "field,value",
    [
        ("average_confidence", float("nan")),
        ("average_confidence", float("inf")),
        ("status_counts", {"confirmed": 1 << 63}),
        ("confidence_buckets", {"high": -1}),
        ("submissions_by_day", {"2026-09-30": True}),
    ],
)
async def test_unsafe_aggregate_values_rejected_statically(
    analytics_data, monkeypatch, field, value
):
    f = analytics_data
    data = dict(
        status_counts={}, confidence_buckets={}, submissions_by_day={}, average_confidence=None
    )
    data[field] = value

    async def injected(*args, **kwargs):
        return PassportAnalyticsSummary(**data)

    monkeypatch.setattr(PassportAnalyticsRepository, "aggregate", injected)
    with pytest.raises(AnalyticsReadError, match="analytics_read_limit"):
        await service(f).summary(f.principal)


async def test_full_response_budget_accounts_for_common_envelope(analytics_data, monkeypatch):
    f = analytics_data
    ordinary = await service(f).summary(f.principal)
    exact_service_size = len(json.dumps(ordinary, ensure_ascii=True).encode())
    monkeypatch.setattr(analytics_reads, "MAX_RESPONSE_BYTES", exact_service_size + 10)
    with pytest.raises(AnalyticsReadError, match="analytics_read_limit"):
        await service(f).summary(f.principal)


async def test_timeout_returns_static_sdk_error_and_no_counts(analytics_data, monkeypatch):
    f = analytics_data
    monkeypatch.setattr(analytics_reads, "READ_TIMEOUT_SECONDS", 0.1)

    async def stalled(*args, **kwargs):
        await asyncio.sleep(2)

    monkeypatch.setattr(PassportAnalyticsRepository, "aggregate", stalled)
    value = (
        await call_mcp(
            f.client, f.tokens["access_token"], name="get_passport_analytics_summary", arguments={}
        )
    ).json()["result"]["structuredContent"]
    assert value["error"] == "analytics_read_busy" and value["completeness"] == "unavailable"
    assert not {"status_counts", "confidence_buckets", "submissions_by_day"} & value.keys()


async def test_sdk_noninteger_is_rejected_and_no_mutation_authority(analytics_data):
    f = analytics_data
    response = await call_mcp(
        f.client,
        f.tokens["access_token"],
        name="get_passport_analytics_summary",
        arguments={"days": "invalid"},
    )
    assert response.json()["result"]["isError"]
    with pytest.raises(AnalyticsReadError, match="analytics_invalid_query"):
        await service(f).summary(f.principal, days=True)
