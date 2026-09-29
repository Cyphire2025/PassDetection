"""GC and personal mailbox tools through real authenticated SDK dispatch."""

from __future__ import annotations

import uuid

import pytest

from app.infrastructure.database.email_models import EmailConnectionModel
from app.infrastructure.database.models import AgencyModel, ClientGroupModel
from app.presentation.mcp.content_read_tools import register_content_read_tools
from tests.integration.test_mcp_authorization import call_mcp, connect
from tests.integration.test_mcp_authorization import mcp_fixture as mcp_fixture


@pytest.mark.asyncio
async def test_content_tools_http_scope_envelope_and_schema(mcp_fixture):
    client, session, settings, actor, _, _ = mcp_fixture
    app = client._transport.app
    if "list_gc_app_records" not in [tool.name for tool in await app.state.mcp_server.list_tools()]:
        register_content_read_tools(app.state.mcp_server, app, settings)
    agency = AgencyModel(id=uuid.uuid4(), name="Test", email="fixture@example.test")
    session.add(agency)
    await session.flush()
    group = ClientGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Unconfigured", token="SECRET_TOKEN")
    session.add_all([group, EmailConnectionModel(id=uuid.uuid4(), agency_id=agency.id, owner_user_id=actor.id,
        provider="gmail", provider_account_id="SECRET_PROVIDER", email_address="SECRET_ADDRESS@example.test", access_token_ciphertext=b"SECRET_ACCESS")])
    await session.flush()
    agency_key = str(agency.id)
    _, tokens = await connect(mcp_fixture)
    for name, args, size in [
        ("list_gc_app_records", {"agency_id":str(agency.id), "group_id":str(group.id), "kind":"access"}, 0),
        ("list_gc_notification_records", {"agency_id":str(agency.id), "kind":"batches"}, 0),
        ("list_email_records", {"kind":"connections"}, 1),
    ]:
        response = await call_mcp(client, tokens["access_token"], name=name, arguments=args)
        assert response.status_code == 200 and "SECRET" not in response.text
        data = response.json()["result"]["structuredContent"]
        assert len(data["items"]) == size and data["environment"] == settings.app_env
        assert data["observed_at"] and data["audit_id"] and data["completeness"] == "complete"
    invalid = await call_mcp(client, tokens["access_token"], name="list_email_records", arguments={"kind":"../../../credentials"})
    assert invalid.json()["result"].get("isError") is True
    missing = await call_mcp(client, tokens["access_token"], name="list_email_records", arguments={"kind":"messages", "connection_id":str(uuid.uuid4())})
    assert missing.json()["result"]["structuredContent"]["error"] == "invalid_content_query"
    _, narrowed = await connect(mcp_fixture, scopes=["mcp:diagnose"])
    denied = await call_mcp(client, narrowed["access_token"], name="list_gc_notification_records", arguments={"agency_id":agency_key, "kind":"drafts"})
    assert denied.json()["result"]["structuredContent"]["error"] == "access_denied"
