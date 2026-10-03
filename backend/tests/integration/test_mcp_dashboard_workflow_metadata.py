"""Write discovery describes actual role choices and denies hidden parent groups."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken

from app.infrastructure.database.mcp_models import MCPControlModel
from app.presentation.mcp.dashboard_workflow_tools import register_dashboard_workflow_tools
from tests.integration.test_mcp_dashboard_edits import edits as edits


def server_for(fixture, monkeypatch):
    session, settings, actor, grants, tokens, *_ = fixture
    app, server = FastAPI(), MCPServer("write metadata")

    @asynccontextmanager
    async def sessions():
        yield session

    app.state.mcp_session_factory, app.state.mcp_operations = sessions, {}
    monkeypatch.setattr("app.presentation.mcp.invocation.get_access_token", lambda: AccessToken(
        token=tokens[0], client_id=grants[0].client_id, scopes=grants[0].capabilities,
        subject=str(actor.id), resource=settings.mcp.resource,
        claims={"grant_id": str(grants[0].id)}))
    register_dashboard_workflow_tools(server, app, settings)
    return server


async def test_account_catalog_lists_only_allowed_role_choices_and_dynamic_sections(edits, monkeypatch):
    fixture = edits
    fixture[3][0].allowed_write_sections = ["staff"]
    await fixture[0].commit()
    server = server_for(fixture, monkeypatch)
    arguments = {"section": "staff", "workflow": "create_workforce_account"}
    result = (await server.call_tool("list_dashboard_write_workflows", arguments)).structured_content
    assert result["total"] == 1 and result["workflows"][0]["enabled"] is True
    assert result["workflows"][0]["available_section_choices"] == ["staff"]
    control = await fixture[0].get(MCPControlModel, 1)
    control.allowed_write_sections = ["group_links"]
    await fixture[0].commit()
    denied = (await server.call_tool("list_dashboard_write_workflows", arguments)).structured_content
    assert denied["workflows"][0]["enabled"] is False
    assert denied["workflows"][0]["available_section_choices"] == []


async def test_current_group_revision_is_safe_and_hidden_parent_is_denied(edits, monkeypatch):
    fixture = edits
    group = fixture[7]
    group_id, agency_id = group.id, fixture[5].id
    await fixture[0].commit()
    server = server_for(fixture, monkeypatch)
    arguments = {"workflow": "configure_group_link", "agency_id": str(agency_id), "target_id": str(group_id)}
    result = (await server.call_tool("inspect_dashboard_write", arguments)).structured_content
    assert result["current"]["name"] == "Synthetic group"
    assert len(result["configuration_revision"]) == 64
    assert "token" not in result["current"]
    group.deleted_at = datetime.now(UTC)
    await fixture[0].commit()
    denied = (await server.call_tool("inspect_dashboard_write", arguments)).structured_content
    assert "current" not in denied
    assert denied["error"] == "workflow_resource_unavailable"
