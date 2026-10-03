"""Native discovery uses saved device, section and OAuth policy together."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from mcp.server.auth.provider import AccessToken
from mcp.types import ListToolsResult, Tool

from app.domain.mcp_read_sections import READ_TOOL_SECTIONS
from app.infrastructure.database.mcp_models import MCPControlModel
from app.presentation.mcp.permission_listing import PermissionListingMiddleware
from app.presentation.mcp.server import ReviewedMCPServer
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture


def tools():
    return ListToolsResult(tools=[Tool(name=name, input_schema={"type": "object"},
                                      meta={"capability": capability}) for name, capability in (
        ("connection_status", "mcp:read"),
        ("read_dashboard_view", "mcp:read"),
        ("create_group", "mcp:change"),
        ("create_menu_category", "mcp:change"),
        ("create_workforce_account", "mcp:change"),
        ("create_native_upload", "mcp:upload"),
        ("create_native_download", "mcp:export"),
        ("inspect_native_transfer", "mcp:upload"),
        ("list_dashboard_write_workflows", "mcp:change"),
        ("inspect_operation", "original_operation_capability"),
        ("unreviewed_business_read", "mcp:read"),
        ("unreviewed_effect", "mcp:change"),
    )])


async def listing(fixture, monkeypatch):
    session, settings, actor, grants, tokens = fixture
    app = FastAPI()

    @asynccontextmanager
    async def sessions():
        yield session

    app.state.mcp_session_factory = sessions
    monkeypatch.setattr("app.presentation.mcp.permission_listing.get_access_token", lambda: AccessToken(
        token=tokens[0], client_id=grants[0].client_id, scopes=grants[0].capabilities,
        subject=str(actor.id), resource=settings.mcp.resource,
        claims={"grant_id": str(grants[0].id)}))

    async def response(ctx):
        return tools()

    result = await PermissionListingMiddleware(app, settings)(SimpleNamespace(method="tools/list"), response)
    return {tool.name for tool in result.tools}


async def test_read_and_write_are_independent_and_unknown_adapters_hidden(operations_fixture, monkeypatch):
    fixture = operations_fixture
    grant = fixture[3][0]
    grant.capabilities = ["mcp:read", "mcp:change", "mcp:upload", "mcp:export"]
    await fixture[0].commit()
    visible = await listing(fixture, monkeypatch)
    assert {"connection_status", "create_group", "create_menu_category", "create_native_upload",
            "create_native_download", "inspect_native_transfer", "create_workforce_account"} <= visible
    assert not {"unreviewed_business_read", "unreviewed_effect"} & visible
    grant.read_enabled = False
    await fixture[0].commit()
    visible = await listing(fixture, monkeypatch)
    assert not set(READ_TOOL_SECTIONS) & visible
    assert "create_group" in visible
    grant.read_enabled, grant.write_enabled = True, False
    await fixture[0].commit()
    assert await listing(fixture, monkeypatch) == {"connection_status", "read_dashboard_view"}


async def test_section_scope_intersection_and_export_only_transfer_inspection(operations_fixture, monkeypatch):
    fixture = operations_fixture
    grant = fixture[3][0]
    grant.capabilities = ["mcp:change"]
    grant.allowed_write_sections = ["group_links"]
    await fixture[0].commit()
    assert await listing(fixture, monkeypatch) == {
        "create_group", "list_dashboard_write_workflows", "inspect_operation"}
    grant.capabilities, grant.allowed_write_sections = ["mcp:export"], ["exports"]
    await fixture[0].commit()
    assert await listing(fixture, monkeypatch) == {
        "create_native_download", "inspect_native_transfer", "inspect_operation"}


@pytest.mark.parametrize("change", ["device", "global_write", "release_read_only", "section", "tool"])
async def test_policy_narrowing_is_reflected_on_next_native_discovery(operations_fixture, monkeypatch, change):
    fixture = operations_fixture
    grant = fixture[3][0]
    grant.capabilities = ["mcp:change"]
    grant.allowed_write_sections = ["menu"]
    control = await fixture[0].get(MCPControlModel, 1)
    if change == "device":
        grant.enabled = False
    elif change == "global_write":
        control.write_enabled = False
    elif change == "release_read_only":
        fixture[1].mcp.read_only_mode = True
    elif change == "section":
        control.allowed_write_sections = []
    else:
        control.allowed_write_tools = []
    await fixture[0].commit()
    assert "create_menu_category" not in await listing(fixture, monkeypatch)


async def test_registry_admits_only_reviewed_effect_or_read_names():
    server = ReviewedMCPServer("reviewed registry")

    @server.tool(meta={"capability": "mcp:change"})
    async def arbitrary_http_action(url: str):
        return {}

    @server.tool(meta={"capability": "mcp:read"})
    async def unpublished_admin_record():
        return {}

    @server.tool(meta={"capability": "mcp:change"})
    async def create_group():
        return {}

    assert [tool.name for tool in await server.list_tools()] == ["create_group"]
