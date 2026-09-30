"""OAuth and actual MCP HTTP server prove scope, static errors and no effects."""

import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, func, select

from app.application.mcp import email_overview_reads
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import AuditLogModel
from app.infrastructure.repositories.email_summary_repository import (
    SUMMARY_FIELDS,
    EmailSummaryRepository,
)
from app.presentation.api.v1.routes import email_integration_access
from tests.integration.test_mcp_authorization import call_mcp, connect
from tests.integration.test_mcp_authorization import mcp_fixture as mcp_fixture
from tests.mcp_email_overview_fixtures import seed_email_overview

TOOLS = ("get_email_integration_status", "get_my_email_integration_summary")


@pytest.fixture
async def email_overview(mcp_fixture):
    f = mcp_fixture
    data = await seed_email_overview(f[1], f[3])
    await f[1].commit()
    return f, data


def body(response):
    assert response.status_code == 200
    return response.json()["result"]["structuredContent"]


async def test_authenticated_fixed_status_and_personal_summary_safe_audits(email_overview, monkeypatch):
    f, data = email_overview
    _, tokens = await connect(f, scopes=["mcp:read"])
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Read invoked a provider or queue")
    monkeypatch.setattr(email_integration_access, "_provider_instance", forbidden)
    monkeypatch.setattr(email_integration_access, "_enqueue_connection_sync", forbidden)
    statements = []
    def capture(_conn, _cursor, sql, *_args):
        statements.append(sql.lower())
    event.listen(f[1].bind.sync_engine, "before_cursor_execute", capture)
    try:
        status = body(await call_mcp(f[0], tokens["access_token"], name=TOOLS[0]))
        summary = body(await call_mcp(f[0], tokens["access_token"], name=TOOLS[1]))
    finally:
        event.remove(f[1].bind.sync_engine, "before_cursor_execute", capture)
    assert {name: summary[name] for name in SUMMARY_FIELDS} == data.expected
    assert [row["provider"] for row in status["providers"]] == ["gmail", "outlook"]
    for result in (status, summary):
        assert result["completeness"] == "complete"
        assert result["environment"] == f[2].app_env and result["revision"] == f[2].app_revision
        assert len(json.dumps(result, ensure_ascii=True).encode()) < 8192
        assert not any(text in json.dumps(result) for text in ("SECRET", "PRIVATE", "example.test", str(f[3].id)))
        audit = await f[1].get(AuditLogModel, uuid.UUID(result["audit_id"]))
        assert audit.result == "success" and audit.user_id == f[3].id
        assert audit.metadata_json == {"capability": "mcp:read", "failure_category": None}
    assert not any(sql.startswith(("insert into email_", "update email_", "delete from email_")) for sql in statements)
    assert await f[1].scalar(select(func.count()).select_from(MCPOperationModel)) == 0


async def test_tool_schema_accepts_no_scope_or_action_arguments(email_overview):
    f, _ = email_overview
    _, tokens = await connect(f, scopes=["mcp:read"])
    response = await f[0].post("/mcp", headers={"Authorization": f"Bearer {tokens['access_token']}",
        "Accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    assert response.status_code == 200
    matches = [tool for tool in response.json()["result"]["tools"] if tool["name"] in TOOLS]
    assert len(matches) == 2
    for tool in matches:
        assert tool["inputSchema"]["properties"] == {}
        assert tool["annotations"]["readOnlyHint"] is True and tool["annotations"]["destructiveHint"] is False


@pytest.mark.parametrize("name", TOOLS)
@pytest.mark.parametrize("restriction", ["revoked", "capability", "deployment", "role", "inactive", "deleted", "session", "control"])
async def test_current_authority_denies_before_any_projection(email_overview, monkeypatch, restriction, name):
    f, _ = email_overview
    _, tokens = await connect(f, scopes=["mcp:read"])
    grant = await f[1].scalar(select(MCPGrantModel))
    if restriction == "revoked":
        grant.revoked_at = datetime.now(UTC)
    elif restriction == "capability":
        grant.capabilities = ["mcp:export"]
    elif restriction == "deployment":
        f[2].mcp.enabled_capabilities = ["mcp:export"]
    elif restriction == "role":
        f[3].role = "agency_staff"
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
        raise AssertionError("Unauthorized summary query")
    def no_readiness(*_args, **_kwargs):
        projected.append(True)
        raise AssertionError("Unauthorized configuration projection")
    monkeypatch.setattr(EmailSummaryRepository, "summary", forbidden)
    monkeypatch.setattr(email_overview_reads, "email_readiness", no_readiness)
    response = await call_mcp(f[0], tokens["access_token"], name=name)
    if response.status_code != 401:
        result = body(response)
        assert result["error"] == "access_denied" and result["completeness"] == "unavailable"
    assert not projected


@pytest.mark.parametrize("failure", ["timeout", "oversize", "unexpected"])
async def test_failure_is_static_audited_no_partial_counts_then_retry(email_overview, monkeypatch, failure):
    f, data = email_overview
    _, tokens = await connect(f, scopes=["mcp:read"])
    with monkeypatch.context() as patch:
        if failure == "oversize":
            patch.setattr(email_overview_reads, "MAX_EMAIL_OVERVIEW_RESPONSE_BYTES", 64)
        else:
            async def fail(*_args, **_kwargs):
                raise (TimeoutError("SECRET_SOURCE") if failure == "timeout" else RuntimeError("SECRET_SOURCE"))
            patch.setattr(EmailSummaryRepository, "summary", fail)
        result = body(await call_mcp(f[0], tokens["access_token"], name=TOOLS[1]))
    assert result["error"] == {"timeout": "email_overview_busy", "oversize": "email_overview_limit", "unexpected": "operation_failed"}[failure]
    assert result["completeness"] == "unavailable" and not set(SUMMARY_FIELDS).intersection(result)
    assert "SECRET_SOURCE" not in json.dumps(result)
    audit = await f[1].get(AuditLogModel, uuid.UUID(result["audit_id"]))
    assert audit.result == ("failed" if failure == "unexpected" else "blocked")
    recovered = body(await call_mcp(f[0], tokens["access_token"], name=TOOLS[1]))
    assert {name: recovered[name] for name in SUMMARY_FIELDS} == data.expected
