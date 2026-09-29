"""WhatsApp read tools at the real authenticated SDK/ASGI boundary."""

from __future__ import annotations

import uuid

import pytest

from app.infrastructure.database.models import (
    AgencyModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
)
from app.presentation.mcp.whatsapp_read_tools import register_whatsapp_read_tools
from tests.integration.test_mcp_authorization import call_mcp, connect
from tests.integration.test_mcp_authorization import mcp_fixture as mcp_fixture


@pytest.mark.asyncio
async def test_whatsapp_http_envelope_exact_receipt_and_contact_opt_in(mcp_fixture):
    client, session, settings, _, _, _ = mcp_fixture
    app = client._transport.app
    if "list_whatsapp_broadcasts" not in [tool.name for tool in await app.state.mcp_server.list_tools()]:
        register_whatsapp_read_tools(app.state.mcp_server, app, settings)
    agency = AgencyModel(id=uuid.uuid4(), name="Fixture Agency", email="fixture@example.test")
    session.add(agency)
    await session.flush()
    group = WhatsAppBroadcastGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Fixture")
    session.add(group)
    await session.flush()
    person = WhatsAppBroadcastRecipientModel(id=uuid.uuid4(), agency_id=agency.id,
        broadcast_group_id=group.id, name="Person", phone_number="+919999000000", normalized_phone_number="919999000000")
    session.add(person)
    await session.flush()
    batch = uuid.uuid4()
    session.add(WhatsAppMessageLogModel(id=uuid.uuid4(), agency_id=agency.id, broadcast_group_id=group.id,
        recipient_id=person.id, batch_id=batch, message_type="passport_link", status="submitted"))
    await session.flush()
    _, tokens = await connect(mcp_fixture)
    response = await call_mcp(client, tokens["access_token"], name="list_whatsapp_broadcasts")
    result = response.json()["result"]["structuredContent"]
    assert result["items"][0]["id"] == str(group.id)
    assert result["environment"] == settings.app_env and result["observed_at"] and result["audit_id"]
    audience = await call_mcp(client, tokens["access_token"], name="list_whatsapp_audience",
        arguments={"broadcast_id": str(group.id)})
    assert "919999000000" not in audience.text
    status = await call_mcp(client, tokens["access_token"], name="get_whatsapp_batch",
        arguments={"broadcast_id": str(group.id), "batch_id": str(batch)})
    payload = status.json()["result"]["structuredContent"]
    assert payload["status_counts"]["submitted"] == 1 and payload["confirmed_delivery_count"] == 0
    bad = await call_mcp(client, tokens["access_token"], name="list_whatsapp_audience",
        arguments={"broadcast_id": str(group.id), "kind": "arbitrary_sql"})
    assert bad.json()["result"].get("isError") is True


@pytest.mark.asyncio
async def test_whatsapp_http_denies_non_read_scope_and_live_role_loss(mcp_fixture):
    client, session, settings, user, _, _ = mcp_fixture
    app = client._transport.app
    if "list_whatsapp_broadcasts" not in [tool.name for tool in await app.state.mcp_server.list_tools()]:
        register_whatsapp_read_tools(app.state.mcp_server, app, settings)
    _, no_read = await connect(mcp_fixture, scopes=["mcp:diagnose"])
    denied = await call_mcp(client, no_read["access_token"], name="list_whatsapp_broadcasts")
    assert denied.json()["result"]["structuredContent"]["error"] == "access_denied"
    _, allowed = await connect(mcp_fixture, scopes=["mcp:read"])
    user.role = "agency_admin"
    await session.flush()
    response = await call_mcp(client, allowed["access_token"], name="list_whatsapp_broadcasts")
    assert response.status_code == 401
