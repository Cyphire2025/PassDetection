"""Real OAuth issuance and SDK HTTP boundary for the fixed overview tool."""

import json
import uuid
from datetime import UTC, datetime

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import event, func, select

from app.application.mcp import admin_overview_reads
from app.application.use_cases.admin_overview import ADMIN_OVERVIEW_FIELDS
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AuditLogModel,
    PassportExportHistoryModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.repositories.admin_overview_repository import AdminOverviewRepository
from tests.dashboard_session_fixtures import issue_dashboard_access
from tests.integration.test_mcp_authorization import call_mcp, connect
from tests.integration.test_mcp_authorization import mcp_fixture as mcp_fixture
from tests.mcp_admin_overview_fixtures import AGENCY_COUNTS, GLOBAL_COUNTS, seed_admin_overview

TOOL = "get_admin_overview"


@pytest.fixture
async def overview(mcp_fixture):
    data = await seed_admin_overview(mcp_fixture[1], mcp_fixture[3])
    await mcp_fixture[1].commit()
    return mcp_fixture, data


def body(response):
    assert response.status_code == 200
    return response.json()["result"]["structuredContent"]


async def test_actual_sdk_client_http_transport_after_real_oauth(overview):
    f, _ = overview
    _, tokens = await connect(f, scopes=["mcp:read"])
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=f[0]._transport.app),
        headers={"Authorization": f"Bearer {tokens['access_token']}"}) as http:
        async with Client(streamable_http_client("http://localhost:8000/mcp", http_client=http), mode="legacy") as sdk:
            tools = await sdk.list_tools()
            assert any(tool.name == TOOL for tool in tools.tools)
            response = await sdk.call_tool(TOOL, {})
    assert not response.is_error
    assert {name: response.structured_content[name] for name in ADMIN_OVERVIEW_FIELDS} == GLOBAL_COUNTS


async def test_oauth_sdk_global_counts_and_website_http_parity_no_business_effects(overview):
    f, _ = overview
    _, tokens = await connect(f, scopes=["mcp:read"])
    statements = []
    def capture(_conn, _cursor, sql, *_args):
        statements.append(sql.lower())
    event.listen(f[1].bind.sync_engine, "before_cursor_execute", capture)
    try:
        actual = body(await call_mcp(f[0], tokens["access_token"], name=TOOL))
        web = await f[0].get("/api/v1/admin/overview", headers={"Authorization": f"Bearer {f[5]}"})
    finally:
        event.remove(f[1].bind.sync_engine, "before_cursor_execute", capture)
    assert web.status_code == 200
    assert {name: actual[name] for name in ADMIN_OVERVIEW_FIELDS} == web.json() == GLOBAL_COUNTS
    assert actual["scope"] == "platform_global" and actual["completeness"] == "complete"
    assert actual["environment"] == f[2].app_env and actual["revision"] == f[2].app_revision
    assert len(json.dumps(actual, ensure_ascii=True).encode()) <= 8192
    assert not any(marker in json.dumps(actual) for marker in ("PRIVATE", "SECRET", "example.test", str(f[3].id)))
    audit = await f[1].get(AuditLogModel, uuid.UUID(actual["audit_id"]))
    assert audit.result == "success" and audit.user_id == f[3].id
    assert audit.metadata_json == {"capability": "mcp:read", "failure_category": None}
    for model in (MCPArtifactModel, MCPOperationModel, PassportExportHistoryModel, WhatsAppMessageLogModel):
        assert await f[1].scalar(select(func.count()).select_from(model)) == 0
    assert not any(sql.startswith(("insert into agencies", "update agencies", "delete from agencies",
        "insert into users", "update users", "delete from users", "insert into client_groups", "update client_groups",
        "delete from client_groups", "insert into passport_submissions", "update passport_submissions",
        "delete from passport_submissions")) for sql in statements)


@pytest.mark.parametrize("role,expected_status", [("agency_admin", 200), ("agency_staff", 403)])
async def test_website_role_dependency_preserved(overview, role, expected_status):
    f, data = overview
    f[3].role, f[3].agency_id = role, data.agencies[0].id
    await f[1].flush()
    token, _ = await issue_dashboard_access(f[1], f[3].id, role, session_version=1,
        authentication_methods=("pwd", "totp"), mfa_authenticated_at=datetime.now(UTC))
    await f[1].commit()
    response = await f[0].get("/api/v1/admin/overview", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == expected_status
    if expected_status == 200:
        # Moving the existing actor into this agency adds it to that user count.
        assert response.json() == {**AGENCY_COUNTS, "users": AGENCY_COUNTS["users"] + 1}


async def test_tool_has_no_scope_override_and_readonly_annotations(overview):
    f, _ = overview
    _, tokens = await connect(f, scopes=["mcp:read"])
    response = await f[0].post("/mcp", headers={"Authorization": f"Bearer {tokens['access_token']}",
        "Accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    assert response.status_code == 200
    tool = next(item for item in response.json()["result"]["tools"] if item["name"] == TOOL)
    assert tool["inputSchema"]["properties"] == {}
    assert tool["annotations"] == {"readOnlyHint": True, "destructiveHint": False,
        "idempotentHint": True, "openWorldHint": False}


@pytest.mark.parametrize("restriction", ["revoked", "capability", "deployment", "role", "inactive", "deleted", "session", "control"])
async def test_fresh_authority_denies_before_any_counts(overview, monkeypatch, restriction):
    f, _ = overview
    _, tokens = await connect(f, scopes=["mcp:read"])
    grant = await f[1].scalar(select(MCPGrantModel))
    if restriction == "revoked":
        grant.revoked_at = datetime.now(UTC)
    elif restriction == "capability":
        grant.capabilities = ["mcp:export"]
    elif restriction == "deployment":
        f[2].mcp.enabled_capabilities = ["mcp:export"]
    elif restriction == "role":
        f[3].role = "agency_admin"
    elif restriction == "inactive":
        f[3].is_active = False
    elif restriction == "deleted":
        f[3].deleted_at = datetime.now(UTC)
    elif restriction == "session":
        f[4].session_version += 1
    else:
        (await f[1].get(MCPControlModel, 1)).enabled = False
    await f[1].commit()
    projected = []
    async def forbidden(*_args, **_kwargs):
        projected.append(True)
        raise AssertionError("Unauthorized aggregate query")
    monkeypatch.setattr(AdminOverviewRepository, "overview", forbidden)
    response = await call_mcp(f[0], tokens["access_token"], name=TOOL)
    if response.status_code != 401:
        actual = body(response)
        assert actual["error"] == "access_denied" and actual["completeness"] == "unavailable"
    assert not projected


@pytest.mark.parametrize("failure", ["timeout", "oversize", "unexpected"])
async def test_static_failure_audited_no_partial_counts_then_same_read_recovers(overview, monkeypatch, failure):
    f, _ = overview
    _, tokens = await connect(f, scopes=["mcp:read"])
    with monkeypatch.context() as patch:
        if failure == "oversize":
            patch.setattr(admin_overview_reads, "MAX_ADMIN_OVERVIEW_RESPONSE_BYTES", 64)
        else:
            async def fail(*_args, **_kwargs):
                raise (TimeoutError("SECRET_SOURCE") if failure == "timeout" else RuntimeError("SECRET_SOURCE"))
            patch.setattr(AdminOverviewRepository, "overview", fail)
        actual = body(await call_mcp(f[0], tokens["access_token"], name=TOOL))
    assert actual["error"] == {"timeout": "admin_overview_busy", "oversize": "admin_overview_limit", "unexpected": "operation_failed"}[failure]
    assert actual["completeness"] == "unavailable" and not set(ADMIN_OVERVIEW_FIELDS).intersection(actual)
    assert "SECRET_SOURCE" not in json.dumps(actual)
    audit = await f[1].get(AuditLogModel, uuid.UUID(actual["audit_id"]))
    assert audit.result == ("failed" if failure == "unexpected" else "blocked")
    recovered = body(await call_mcp(f[0], tokens["access_token"], name=TOOL))
    assert {name: recovered[name] for name in ADMIN_OVERVIEW_FIELDS} == GLOBAL_COUNTS
