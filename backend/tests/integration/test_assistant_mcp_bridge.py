"""Real SQL, SDK registry and existing MCP authorization; no external services."""

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI, Request
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.types import ToolAnnotations
from sqlalchemy import func, select

from app.application.assistant.contracts import AssistantError
from app.application.assistant.settings_contracts import (
    AssistantConfiguration,
    AssistantSettingsUpdate,
)
from app.application.mcp.operations import MCPDatabaseOperation, MCPOperationService
from app.domain.entities.entities import UserRole
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.assistant.settings_store import save_settings
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel, MCPTokenModel
from app.infrastructure.database.models import AgencyModel, AuditLogModel
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.assistant import mcp_bridge, reads
from app.presentation.mcp.invocation import invoke_read
from app.presentation.mcp.server import ReviewedMCPServer
from tests.integration.test_mcp_operations import create_agency, seed_identity
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture


@pytest.fixture
async def linked(operations_fixture, monkeypatch):
    session, settings, model, grants, _ = operations_fixture
    grants[0].capabilities = ["mcp:read", "mcp:change"]
    await session.commit()
    actor = await UserRepository(session).get_by_id(model.id)

    @asynccontextmanager
    async def sessions():
        yield session

    monkeypatch.setattr(mcp_bridge, "AsyncSessionFactory", sessions)
    monkeypatch.setattr(reads, "AsyncSessionFactory", sessions)
    monkeypatch.setattr(mcp_bridge, "get_settings", lambda: settings)
    app = FastAPI()
    app.state.mcp_session_factory = sessions
    server = ReviewedMCPServer("Synthetic existing MCP")

    @server.tool(annotations=ToolAnnotations(read_only_hint=True), meta={"capability": "mcp:read"})
    async def connection_status() -> dict:
        async def operation(db, principal):
            return {"grant_id": str(principal.grant_id), "agencies": await db.scalar(select(func.count()).select_from(AgencyModel))}
        return await invoke_read(app, settings, MCPToolPolicy("connection_status", MCPCapability.READ, frozenset({"read"})), operation)

    @server.tool(annotations=ToolAnnotations(read_only_hint=False), meta={"capability": "mcp:change"})
    async def create_group(name: str, idempotency_key: str) -> dict:
        token = get_access_token()
        assert token is not None
        policy = MCPToolPolicy("create_group", MCPCapability.CHANGE, frozenset({"create"}))
        return await MCPOperationService(session, settings, [MCPDatabaseOperation(policy, create_agency)]).execute(
            access_token=token.token, operation_name="create_group", idempotency_key=idempotency_key, payload={"name": name})

    app.state.mcp_server = server
    config = AssistantConfiguration(mcp_connection_id=grants[0].id)
    await save_settings(session, actor, AssistantSettingsUpdate(expected_revision=0, configuration=config))
    bridge = mcp_bridge.MCPAssistantBridge(Request({"type": "http", "app": app}), actor)
    return session, settings, actor, grants, config, bridge


async def test_default_discovery_reads_existing_connection_and_cleans_private_token(linked):
    session, _, _, grants, _, bridge = linked
    before = await session.scalar(select(func.count()).select_from(MCPTokenModel))
    visible = await bridge.discover()
    assert [tool["name"] for tool in visible["tools"]] == ["connection_status"]
    assert visible["write_enabled"] is False
    result = await bridge.call("connection_status", "{}")
    assert "grant_id" in result["result"], result
    assert result["result"]["grant_id"] == str(grants[0].id)
    assert result["result"]["agencies"] == 0
    assert await session.scalar(select(func.count()).select_from(MCPTokenModel)) == before
    assert await session.scalar(select(func.count()).select_from(MCPGrantModel)) == 2
    assert await session.scalar(select(func.count()).select_from(AuditLogModel)) >= 2
    assert get_access_token() is None
    assert "gcmcp_access_" not in json.dumps(result)


async def test_ai_toggle_admits_only_existing_write_scope_and_idempotency(linked):
    session, _, actor, grants, config, bridge = linked
    control = await session.get(MCPControlModel, 1)
    before_policy = (list(grants[0].capabilities), grants[0].write_enabled, list(control.allowed_write_tools))
    args = json.dumps({"name": "Synthetic AI request", "idempotency_key": "assistant-test-request-001"})
    with pytest.raises(AssistantError, match="not permitted"):
        await bridge.call("create_group", args)
    assert await session.scalar(select(func.count()).select_from(AgencyModel)) == 0
    await save_settings(session, actor, AssistantSettingsUpdate(expected_revision=1, configuration=config.model_copy(update={"mcp_write_enabled": True})))
    assert "create_group" in {tool["name"] for tool in (await bridge.discover())["tools"]}
    first = await bridge.call("create_group", args)
    repeated = await bridge.call("create_group", args)
    assert "operation_id" in first["result"], first
    assert first["result"]["operation_id"] == repeated["result"]["operation_id"]
    assert await session.scalar(select(func.count()).select_from(AgencyModel)) == 1
    assert before_policy == (list(grants[0].capabilities), grants[0].write_enabled, list(control.allowed_write_tools))
    await save_settings(session, actor, AssistantSettingsUpdate(expected_revision=2, configuration=config))
    with pytest.raises(AssistantError, match="not permitted"):
        await bridge.call("create_group", args)


@pytest.mark.parametrize("restriction", ["grant_write", "global_write", "scope", "sections", "tool"])
async def test_ai_write_cannot_expand_mcp_permissions(linked, restriction):
    session, _, actor, grants, config, bridge = linked
    await save_settings(session, actor, AssistantSettingsUpdate(expected_revision=1, configuration=config.model_copy(update={"mcp_write_enabled": True})))
    control = await session.get(MCPControlModel, 1)
    if restriction == "grant_write":
        grants[0].write_enabled = False
    elif restriction == "global_write":
        control.write_enabled = False
    elif restriction == "scope":
        grants[0].capabilities = ["mcp:read"]
    elif restriction == "sections":
        grants[0].allowed_write_sections = []
    else:
        control.allowed_write_tools = []
    await session.commit()
    assert "create_group" not in {tool["name"] for tool in (await bridge.discover())["tools"]}
    with pytest.raises(AssistantError):
        await bridge.call("create_group", '{"name":"blocked","idempotency_key":"blocked-request-001"}')
    assert await session.scalar(select(func.count()).select_from(AgencyModel)) == 0


async def test_revocation_and_effective_role_are_rechecked_after_discovery(linked):
    session, _, actor, grants, _, bridge = linked
    assert (await bridge.discover())["tools"]
    grants[0].revoked_at = datetime.now(UTC)
    await session.commit()
    with pytest.raises(AssistantError) as denied:
        await bridge.call("connection_status", "{}")
    assert denied.value.status == 403
    bridge.user = replace(actor, role=UserRole.AGENCY_ADMIN, actual_role=UserRole.SUPER_ADMIN)
    with pytest.raises(AssistantError):
        await bridge.discover()


async def test_ambiguous_connection_requires_selection_and_unknown_tools_fail_closed(linked):
    session, _, actor, _, config, bridge = linked
    await save_settings(session, actor, AssistantSettingsUpdate(expected_revision=1, configuration=config.model_copy(update={"mcp_connection_id": None})))
    with pytest.raises(AssistantError) as ambiguous:
        await bridge.discover()
    assert ambiguous.value.code == "mcp_connection_required"
    with pytest.raises(AssistantError) as denied:
        await bridge.dispatch("execute_sql", {"sql": "DELETE FROM users"})
    assert denied.value.code == "query_rejected"


async def test_another_administrator_cannot_borrow_the_selected_grant(linked):
    session, settings, _, _, _, bridge = linked
    other, _, _ = await seed_identity(session, settings, email="second-ai-owner@example.test")
    await session.commit()
    bridge.user = await UserRepository(session).get_by_id(other.id)
    with pytest.raises(AssistantError) as denied:
        await bridge.call("connection_status", "{}")
    assert denied.value.status == 403


async def test_failed_invocation_removes_credential_and_resets_auth_context(linked, monkeypatch):
    session, _, _, _, _, bridge = linked
    before = await session.scalar(select(func.count()).select_from(MCPTokenModel))
    async def fail(*args):
        assert get_access_token() is not None
        raise RuntimeError("private provider detail")
    monkeypatch.setattr(bridge.request.app.state.mcp_server, "call_tool", fail)
    with pytest.raises(AssistantError) as failed:
        await bridge.call("connection_status", "{}")
    assert "private provider" not in failed.value.message
    assert get_access_token() is None
    assert await session.scalar(select(func.count()).select_from(MCPTokenModel)) == before
