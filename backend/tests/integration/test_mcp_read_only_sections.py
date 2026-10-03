"""Minimum read-only release through real SDK/HTTP and synthetic authority only."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.group_reads import MCPGroupReadService
from app.core.config.mcp import MCPSettings
from app.domain.mcp_policy import CAPABILITIES
from app.domain.mcp_read_sections import READ_TOOL_SECTIONS, SUPPORTED_READ_SECTIONS
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.models import AuditLogModel, ClientGroupModel
from app.infrastructure.database.session import get_db_session
from app.main import create_application
from app.presentation.api.v1.routes import mcp_admin, mcp_admin_files, mcp_artifacts
from tests.dashboard_session_fixtures import issue_dashboard_access
from tests.integration.test_mcp_authorization import CLIENT, RESOURCE, call_mcp, connect, consent
from tests.integration.test_mcp_authorization import mcp_fixture as mcp_fixture


@pytest.fixture
async def readonly_mcp(mcp_fixture):
    old_client, session, settings, user, security, dashboard = mcp_fixture
    # This suite exercises the explicit empty read policy, independently of
    # the shared fixture's fully allowed observation baseline.
    control = await session.get(MCPControlModel, 1)
    control.allowed_read_sections = []
    await session.flush()
    # An actual formerly authorized broad grant survives this deployment.
    _, tokens = await connect(mcp_fixture, scopes=sorted(CAPABILITIES))
    settings.mcp.read_only_mode = True
    app = create_application(settings, initialize_rate_limit_redis=False)

    async def db():
        yield session

    @asynccontextmanager
    async def factory():
        yield session

    app.dependency_overrides[get_db_session] = db
    app.state.mcp_session_factory = factory
    app.state.mcp_management_audit_session_factory = old_client._transport.app.state.mcp_management_audit_session_factory
    started, stopped = asyncio.Event(), asyncio.Event()

    async def lifespan():
        async with app.state.mcp_http_app.router.lifespan_context(app.state.mcp_http_app):
            started.set()
            await stopped.wait()

    task = asyncio.create_task(lifespan())
    await asyncio.wait_for(started.wait(), 5)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:8000") as client:
            yield client, session, settings, user, security, dashboard, tokens, app
    finally:
        stopped.set()
        await task


def tool_result(response):
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    return result.get("structuredContent") or json.loads(result["content"][0]["text"])


async def save_sections(fixture, sections, revision=1):
    client, _, _, _, _, dashboard, _, _ = fixture
    return await client.put("/api/v1/mcp/read-access", headers={"Authorization": f"Bearer {dashboard}"},
                            json={"allowed_read_sections": sections, "expected_revision": revision})


async def test_sdk_lists_only_explicit_observations_and_metadata_has_effective_authority(readonly_mcp):
    client, session, _, _, _, dashboard, tokens, app = readonly_mcp
    tools = await app.state.mcp_server.list_tools()
    assert {tool.name for tool in tools} == set(READ_TOOL_SECTIONS)
    assert len(tools) == 44
    assert all(tool.annotations.read_only_hint and tool.meta["capability"] == "mcp:read" for tool in tools)
    # This reaches the real SDK tools/list handler with a legacy broad bearer.
    listing = await client.post("/mcp", headers={
        "Authorization": f"Bearer {tokens['access_token']}", "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-11-25",
    }, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    assert {row["name"] for row in listing.json()["result"]["tools"]} == {
        name for name, required in READ_TOOL_SECTIONS.items() if not required
    }
    status = tool_result(await call_mcp(client, tokens["access_token"]))
    assert status["read_only_mode"] is True and status["capabilities"] == ["mcp:read"]
    assert status["allowed_read_sections"] == [] and status["export_families"] == []
    assert status["export_source_row_limit"] == status["export_source_byte_limit"] == 0
    assert "No creation" in app.state.mcp_server.instructions
    inventory = (await client.get("/api/v1/admin/mcp/inventory", headers={"Authorization": f"Bearer {dashboard}"})).json()
    assert inventory["file_transports"] == [] and inventory["effective_capabilities"] == ["mcp:read"]
    assert all(row["required_read_sections"] == sorted(READ_TOOL_SECTIONS[row["name"]]) for row in inventory["tools"])
    overview = (await client.get("/api/v1/admin/mcp", headers={"Authorization": f"Bearer {dashboard}"})).json()
    assert overview["capabilities"] == overview["defined_capabilities"] == ["mcp:read"]
    grants = (await client.get("/api/v1/admin/mcp/connections", headers={"Authorization": f"Bearer {dashboard}"})).json()
    assert grants["items"][0]["effective_capabilities"] == ["mcp:read"]
    grant = await session.scalar(select(MCPGrantModel))
    assert set(grant.capabilities) == CAPABILITIES  # Stored grant never silently widened/narrowed.


@pytest.mark.parametrize("name", [
    "create_group", "prepare_passport_excel", "inspect_excel_export_options", "inspect_operation",
    "inspect_whatsapp_intent", "inspect_gc_push", "acknowledge_my_notification", "inspect_contact_workbook",
])
async def test_former_broad_tools_are_unavailable_and_do_not_change_business(readonly_mcp, name):
    client, session, _, _, _, _, tokens, _ = readonly_mcp
    before = await session.scalar(select(func.count()).select_from(ClientGroupModel))
    denied = await call_mcp(client, tokens["access_token"], name=name)
    assert denied.status_code == 200 and ("error" in denied.json() or denied.json()["result"].get("isError"))
    assert await session.scalar(select(func.count()).select_from(ClientGroupModel)) == before
    assert await session.scalar(select(func.count()).select_from(AuditLogModel).where(
        AuditLogModel.action == "mcp.tool.invalid_request", AuditLogModel.result == "denied")) == 1


@pytest.mark.parametrize("method,path", [
    ("GET", "/mcp/artifacts/authority"),
    ("GET", "/mcp/artifacts/gcmcp_fixture"),
    ("GET", "/mcp/artifacts/gcmcp_fixture/content"),
    ("POST", "/mcp/artifacts/gcmcp_fixture/delivery"),
    ("POST", "/mcp/artifacts/uploads"),
    ("POST", "/mcp/contact-imports/uploads"),
    ("GET", "/mcp/whatsapp-media/authority"),
    ("GET", "/mcp/whatsapp-media/gcmcp_fixture"),
    ("POST", "/mcp/whatsapp-media/uploads"),
    ("POST", "/mcp/whatsapp-media/00000000-0000-0000-0000-000000000001/recover"),
])
async def test_file_routes_deny_before_any_service_or_bytes(readonly_mcp, method, path, monkeypatch):
    client, session, _, _, _, _, tokens, _ = readonly_mcp
    service = AsyncMock(side_effect=AssertionError("File service must not run"))
    monkeypatch.setattr(mcp_artifacts, "_service", service)
    response = await client.request(method, path, headers={"Authorization": f"Bearer {tokens['access_token']}"}, content=b"unread synthetic bytes")
    assert response.status_code == 403, response.text
    assert "insufficient_scope" in response.text
    service.assert_not_called()
    assert await session.scalar(select(func.count()).select_from(AuditLogModel).where(
        AuditLogModel.action == "mcp.artifact_access_denied", AuditLogModel.result == "denied")) == 1


@pytest.mark.parametrize("path,module", [
    ("/api/v1/admin/mcp/operations", mcp_admin),
    ("/api/v1/admin/mcp/artifacts", mcp_admin_files),
])
async def test_legacy_dashboard_workflow_and_file_controls_deny_before_projection(readonly_mcp, path, module, monkeypatch):
    client, _, _, _, _, dashboard, _, _ = readonly_mcp
    query = Mock(side_effect=AssertionError("Deferred MCP metadata must not be queried"))
    monkeypatch.setattr(module, "select", query)
    response = await client.get(path, headers={"Authorization": f"Bearer {dashboard}"})
    assert response.status_code == 403, response.text
    assert "unavailable in this read-only deployment" in response.text
    query.assert_not_called()


async def test_current_section_denial_reenable_and_dependency_revocation_precede_service(readonly_mcp, monkeypatch):
    client, session, _, _, _, _, tokens, _ = readonly_mcp
    service = AsyncMock(return_value={"items": [], "has_more": False, "next_cursor": None})
    monkeypatch.setattr(MCPGroupReadService, "list_groups", service)
    denied = tool_result(await call_mcp(client, tokens["access_token"], name="list_groups"))
    assert denied["error"] == "access_denied" and "Review MCP settings" in denied["message"]
    assert denied["required_sections"] == ["all_groups", "old_data", "whatsapp"]
    service.assert_not_awaited()
    needed = sorted(READ_TOOL_SECTIONS["list_groups"])
    enabled = await save_sections(readonly_mcp, needed)
    assert enabled.status_code == 200 and enabled.json()["revision"] == 2
    accepted = tool_result(await call_mcp(client, tokens["access_token"], name="list_groups"))
    assert accepted["items"] == []
    assert service.await_count == 1
    # A different request updates DB state; existing bearer/connection is rechecked.
    removed = await save_sections(readonly_mcp, ["all_groups", "old_data"], revision=2)
    assert removed.status_code == 200
    denied_again = tool_result(await call_mcp(client, tokens["access_token"], name="list_groups"))
    assert denied_again["error"] == "access_denied" and service.await_count == 1
    status = tool_result(await call_mcp(client, tokens["access_token"]))
    assert status["allowed_read_sections"] == ["all_groups", "old_data"]
    audits = list(await session.scalars(select(AuditLogModel).where(AuditLogModel.action == "mcp.tool.list_groups")))
    assert [row.result for row in audits] == ["denied", "success", "denied"]
    assert audits[-1].metadata_json["failure_category"] == "read_section_denied"


async def test_dashboard_catalog_and_dynamic_authority_via_real_sdk_http(readonly_mcp):
    client, session, _, _, _, _, tokens, _ = readonly_mcp
    token = tokens["access_token"]
    catalog = tool_result(await call_mcp(client, token, name="list_dashboard_read_views",
        arguments={"view": "platform_settings"}))
    assert catalog["views"][0]["required_sections"] == ["settings"]
    assert catalog["views"][0]["enabled"] is False
    denied = tool_result(await call_mcp(client, token, name="read_dashboard_view",
        arguments={"view": "platform_settings"}))
    assert denied["error"] == "access_denied" and denied["required_sections"] == ["settings"]
    assert (await save_sections(readonly_mcp, ["settings"])).status_code == 200
    result = tool_result(await call_mcp(client, token, name="read_dashboard_view",
        arguments={"view": "platform_settings"}))
    assert result["view"] == "platform_settings" and result["source"] == "reviewed_dashboard_read"
    assert result["read_access_revision"] == 2
    tracking = tool_result(await call_mcp(client, token, name="read_dashboard_view",
        arguments={"view": "whatsapp_tracking", "parameters": {"group_id": "not-a-uuid"}}))
    assert tracking["error"] == "access_denied" and tracking["required_sections"] == ["all_groups", "whatsapp"]
    attempts = list(await session.scalars(select(AuditLogModel).where(AuditLogModel.action == "mcp.tool.read_dashboard_view")))
    assert [row.result for row in attempts] == ["denied", "success", "denied"]
    assert attempts[-1].metadata_json["failure_category"] == "read_section_denied"


async def test_phone_comparison_sdk_read_and_section_denial(readonly_mcp):
    import uuid

    from app.infrastructure.database.models import (
        AgencyModel,
        ClientGroupWhatsAppBroadcastLinkModel,
        WhatsAppBroadcastGroupModel,
    )

    client, session, _, _, _, _, tokens, _ = readonly_mcp
    agency = AgencyModel(id=uuid.uuid4(), name="Comparison", email="compare@example.test")
    session.add(agency)
    await session.flush()
    group = ClientGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Comparison", token="private")
    broadcast = WhatsAppBroadcastGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Comparison")
    session.add_all([group, broadcast])
    await session.flush()
    session.add(ClientGroupWhatsAppBroadcastLinkModel(id=uuid.uuid4(), agency_id=agency.id,
        client_group_id=group.id, broadcast_group_id=broadcast.id))
    await session.commit()
    await save_sections(readonly_mcp, ["all_groups", "whatsapp"])
    args = {"group_id": str(group.id)}
    result = tool_result(await call_mcp(client, tokens["access_token"], name="list_submission_phone_differences", arguments=args))
    assert result["items"] == [] and result["counts"]["compared_match_pairs"] == 0
    assert result["completeness"] == "complete" and result["read_access_revision"] == 2
    await save_sections(readonly_mcp, ["all_groups"], revision=2)
    denied = tool_result(await call_mcp(client, tokens["access_token"], name="list_submission_phone_differences", arguments=args))
    assert denied["error"] == "access_denied" and "whatsapp" in denied["required_sections"]


async def test_phone_comparison_rejects_deferred_business_write(readonly_mcp, monkeypatch):
    from app.infrastructure.database.models import UserModel
    from app.presentation.mcp import phone_difference_read_tools

    client, session, _, user, _, _, tokens, _ = readonly_mcp
    await save_sections(readonly_mcp, ["all_groups", "whatsapp"])
    user_id, original = user.id, user.full_name

    async def regressed(self, *, user_id, **kwargs):
        row = await self.session.get(UserModel, user_id)
        row.full_name = "Forbidden business edit"
        return {"items": []}

    monkeypatch.setattr(phone_difference_read_tools.MCPPhoneDifferenceReadService, "read", regressed)
    result = tool_result(await call_mcp(client, tokens["access_token"], name="list_submission_phone_differences",
        arguments={"group_id": str(user_id)}))
    assert result["error"] == "operation_failed"
    assert await session.scalar(select(UserModel.full_name).where(UserModel.id == user_id)) == original


async def test_dashboard_dispatch_cannot_inject_authority_or_select_arbitrary_code(readonly_mcp):
    client, _, _, _, _, _, tokens, _ = readonly_mcp
    await save_sections(readonly_mcp, sorted(SUPPORTED_READ_SECTIONS))
    for view, parameters in (("os.system", {}), ("platform_settings", {"current_user": {"role": "super_admin"}}),
        ("platform_settings", {"session": "spoof"}), ("platform_settings", {"sql": "DELETE FROM users"})):
        result = tool_result(await call_mcp(client, tokens["access_token"], name="read_dashboard_view",
            arguments={"view": view, "parameters": parameters}))
        assert result["error"] in {"unknown_dashboard_view", "invalid_dashboard_read"}


async def test_dashboard_rejects_unflushed_business_changes_before_outer_commit(readonly_mcp, monkeypatch):
    client, session, _, user, _, _, tokens, _ = readonly_mcp
    await save_sections(readonly_mcp, ["settings"])
    from app.infrastructure.database.models import UserModel
    from app.presentation.mcp import dashboard_read_tools

    user_id = user.id
    original = user.full_name

    async def regressed(current_user, session):
        row = await session.get(UserModel, current_user.id)
        row.full_name = "Tampered deferred write"
        return {"result": "read"}

    monkeypatch.setattr(dashboard_read_tools, "dashboard_handler", lambda _: regressed)
    result = tool_result(await call_mcp(client, tokens["access_token"], name="read_dashboard_view",
        arguments={"view": "platform_settings"}))
    assert result["error"] == "operation_failed"
    assert await session.scalar(select(UserModel.full_name).where(UserModel.id == user_id)) == original


@pytest.mark.parametrize("name", ["get_dashboard_summary", "get_admin_overview", "get_passport_analytics_summary", "list_organization_directory", "list_gc_app_records", "list_whatsapp_broadcasts", "list_submission_phone_differences"])
async def test_shared_summary_cannot_bypass_a_deselected_dependency(readonly_mcp, name):
    client, _, _, _, _, _, tokens, app = readonly_mcp
    # Call the audited real wrapper with a callback sentinel, independent of input schema.
    from mcp.server.auth.middleware.auth_context import AuthenticatedUser, auth_context_var
    from mcp.server.auth.provider import AccessToken

    from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
    from app.presentation.mcp.invocation import invoke_read
    callback = AsyncMock(return_value={"should_not_be_seen": True})
    required = READ_TOOL_SECTIONS[name]
    await save_sections(readonly_mcp, sorted(required - {"all_groups"}))
    token = AccessToken(token=tokens["access_token"], client_id=CLIENT, scopes=["mcp:read"], resource=RESOURCE)
    marker = auth_context_var.set(AuthenticatedUser(token))
    try:
        result = await invoke_read(app, app.state.settings, MCPToolPolicy(name, MCPCapability.READ, frozenset({"read"})), callback)
    finally:
        auth_context_var.reset(marker)
    assert result["error"] == "access_denied" and "all_groups" in result["required_sections"]
    callback.assert_not_awaited()


async def test_unknown_read_wrapper_and_missing_grant_read_fail_before_callback(readonly_mcp):
    from mcp.server.auth.middleware.auth_context import AuthenticatedUser, auth_context_var
    from mcp.server.auth.provider import AccessToken

    from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
    from app.presentation.mcp.invocation import invoke_read

    _, session, settings, _, _, _, tokens, app = readonly_mcp
    await save_sections(readonly_mcp, sorted(SUPPORTED_READ_SECTIONS))
    callback = AsyncMock(return_value={"must_not_be_seen": True})
    token = AccessToken(token=tokens["access_token"], client_id=CLIENT, scopes=["mcp:read"], resource=RESOURCE)
    marker = auth_context_var.set(AuthenticatedUser(token))
    try:
        unknown = await invoke_read(app, settings, MCPToolPolicy("unreviewed_observation", MCPCapability.READ, frozenset({"read"})), callback)
        assert unknown["error"] == "access_denied"
        grant = await session.scalar(select(MCPGrantModel))
        grant.capabilities = ["mcp:export"]
        await session.commit()
        missing_read = await invoke_read(app, settings, MCPToolPolicy("list_groups", MCPCapability.READ, frozenset({"read"})), callback)
        assert missing_read["error"] == "access_denied"
    finally:
        auth_context_var.reset(marker)
    callback.assert_not_awaited()


@pytest.mark.parametrize("name", ["connection_status", "list_groups"])
async def test_read_control_lock_precedes_grant_access_and_remains_through_callback(readonly_mcp, name, monkeypatch):
    from mcp.server.auth.middleware.auth_context import AuthenticatedUser, auth_context_var
    from mcp.server.auth.provider import AccessToken

    from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
    from app.presentation.mcp.invocation import invoke_read

    _, session, settings, _, _, _, tokens, app = readonly_mcp
    await save_sections(readonly_mcp, sorted(SUPPORTED_READ_SECTIONS))
    original_scalar = session.scalar
    statements = []

    async def observe_scalar(statement, *args, **kwargs):
        statements.append(str(statement.compile(dialect=postgresql.dialect())))
        return await original_scalar(statement, *args, **kwargs)

    monkeypatch.setattr(session, "scalar", observe_scalar)

    async def callback(active_session, _principal):
        assert active_session is session and session.in_transaction()
        # The first authority query locks the global control, even for metadata.
        assert "mcp_control.enabled" in statements[0] and "FOR SHARE" in statements[0]
        assert all("mcp_grants" not in statement for statement in statements[:1])
        return {"observed": True}

    token = AccessToken(token=tokens["access_token"], client_id=CLIENT, scopes=["mcp:read"], resource=RESOURCE)
    marker = auth_context_var.set(AuthenticatedUser(token))
    try:
        result = await invoke_read(app, settings, MCPToolPolicy(name, MCPCapability.READ, frozenset({"read"})), callback)
    finally:
        auth_context_var.reset(marker)
    assert result["observed"] is True
    assert not session.in_transaction()  # Read and audit completed in one commit.


async def test_management_revision_validation_and_deployment_ceiling(readonly_mcp):
    client, session, settings, _, _, dashboard, tokens, _ = readonly_mcp
    headers = {"Authorization": f"Bearer {dashboard}"}
    initial = await client.get("/api/v1/mcp/read-access", headers=headers)
    assert initial.status_code == 200 and initial.json()["revision"] == 1
    catalog = {row["id"]: row for row in initial.json()["sections"]}
    assert {key for key, value in catalog.items() if value["supported"]} == SUPPORTED_READ_SECTIONS
    assert all(catalog[key]["supported"] for key in ["my_tour", "audit_logs", "settings"])
    assert not catalog["codex_access"]["supported"]
    assert catalog["codex_access"]["metadata_only"] is True
    assert (await save_sections(readonly_mcp, sorted(SUPPORTED_READ_SECTIONS))).status_code == 200
    stale = await save_sections(readonly_mcp, [], revision=1)
    assert stale.status_code == 409
    assert (await save_sections(readonly_mcp, ["codex_access"], revision=2)).status_code == 422
    extra = await client.put("/api/v1/mcp/read-access", headers=headers,
                             json={"allowed_read_sections": [], "expected_revision": 2, "read_only_mode": False})
    assert extra.status_code == 422 and settings.mcp.read_only_mode is True
    current = await client.get("/api/v1/mcp/read-access", headers=headers)
    assert current.json()["allowed_read_sections"] == sorted(SUPPORTED_READ_SECTIONS)
    forbidden = await client.post("/api/v1/admin/mcp/authorize", headers=headers, json=consent())
    assert forbidden.status_code == 400 and forbidden.json()["error"] == "invalid_scope"
    grant = await session.scalar(select(MCPGrantModel))
    expand = await client.patch(f"/api/v1/admin/mcp/connections/{grant.id}", headers=headers,
                               json={"name": "still read", "capabilities": ["mcp:read", "mcp:export"]})
    assert expand.status_code == 409
    for capability in CAPABILITIES - {"mcp:read"}:
        with pytest.raises(MCPAuthError, match="insufficient_scope"):
            await MCPAuthorizationService(session, settings).verify_access(tokens["access_token"], capability)
    metadata = (await client.get("/.well-known/oauth-authorization-server")).json()
    assert metadata["scopes_supported"] == ["mcp:read"]


@pytest.mark.parametrize("method", ["GET", "PUT"])
@pytest.mark.parametrize("boundary", ["anonymous", "mcp_bearer", "nonadmin", "stale_mfa", "cookie_csrf"])
async def test_section_management_requires_dashboard_superadmin_csrf_and_recent_mfa(readonly_mcp, method, boundary):
    client, _, _, user, _, dashboard, tokens, _ = readonly_mcp
    headers = {"Authorization": f"Bearer {dashboard}"}
    if boundary == "anonymous":
        headers = {}
    elif boundary == "mcp_bearer":
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    elif boundary == "nonadmin":
        user.role = "agency_staff"
    elif boundary == "stale_mfa":
        session = readonly_mcp[1]
        stale, _ = await issue_dashboard_access(session, user.id, "super_admin", session_version=1,
            authentication_methods=("pwd", "totp"), mfa_authenticated_at=datetime.now(UTC) - timedelta(minutes=11))
        headers = {"Authorization": f"Bearer {stale}"}
    else:
        client.cookies.set("access_token", dashboard)
        headers = {"Origin": "https://attacker.invalid"}
    response = await client.request(method, "/api/v1/mcp/read-access", headers=headers,
                                    **({"json": {"allowed_read_sections": ["all_groups"], "expected_revision": 1}} if method == "PUT" else {}))
    assert response.status_code in {401, 403}, response.text
    control = await readonly_mcp[1].scalar(select(MCPControlModel))
    assert control.allowed_read_sections == [] and control.read_access_revision == 1


def test_read_only_mode_is_deployment_owned_and_defaults_compatible(monkeypatch):
    monkeypatch.delenv("MCP_READ_ONLY_MODE", raising=False)
    assert MCPSettings(_env_file=None).read_only_mode is False
    monkeypatch.setenv("MCP_READ_ONLY_MODE", "true")
    configured = MCPSettings(_env_file=None, enabled_capabilities=sorted(CAPABILITIES))
    assert configured.read_only_mode is True and configured.effective_capabilities == ["mcp:read"]
