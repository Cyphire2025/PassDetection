"""Office read tools through the authenticated MCP SDK ASGI transport."""

from __future__ import annotations

import uuid

import pytest

from app.infrastructure.database.menu_models import MenuCategoryModel
from app.infrastructure.database.models import AgencyModel, ClientGroupModel, RoomingHotelModel
from app.presentation.mcp.operations_read_tools import register_operations_read_tools
from tests.integration.test_mcp_authorization import call_mcp, connect
from tests.integration.test_mcp_authorization import mcp_fixture as mcp_fixture


@pytest.mark.asyncio
async def test_office_tools_http_envelope_schema_and_scope(mcp_fixture):
    client, session, settings, _, _, _ = mcp_fixture
    app = client._transport.app
    if "list_tour_records" not in [tool.name for tool in await app.state.mcp_server.list_tools()]:
        register_operations_read_tools(app.state.mcp_server, app, settings)
    agency = AgencyModel(id=uuid.uuid4(), name="Office", email="SECRET_CONTACT@example.test")
    session.add(agency)
    await session.flush()
    group = ClientGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Office group", token="SECRET_TOKEN", import_only=True)
    category = MenuCategoryModel(id=uuid.uuid4(), agency_id=agency.id, name="Menu", normalized_name="menu")
    session.add_all([group, category])
    await session.flush()
    session.add(RoomingHotelModel(id=uuid.uuid4(), group_id=group.id, agency_id=agency.id, hotel_name="Hotel"))
    await session.flush()
    _, tokens = await connect(mcp_fixture)
    requests = [
        ("list_tour_records", {"group_id": str(group.id), "kind": "activities"}, 0),
        ("list_rooming_records", {"group_id": str(group.id), "kind": "hotels"}, 1),
        ("list_menu_records", {"agency_id": str(agency.id), "kind": "categories"}, 1),
        ("list_organization_directory", {"agency_id": str(agency.id), "kind": "agencies"}, 1),
    ]
    for name, arguments, expected in requests:
        response = await call_mcp(client, tokens["access_token"], name=name, arguments=arguments)
        assert response.status_code == 200 and "SECRET" not in response.text
        assert not response.json()["result"].get("isError")
        data = response.json()["result"]["structuredContent"]
        assert len(data["items"]) == expected
        assert data["environment"] == settings.app_env and data["observed_at"] and data["audit_id"]
        assert data["completeness"] == "complete" and data["consistency"]["snapshot_guaranteed"] is False
    for arguments in ({"kind": "../../files"}, {"kind": "agencies", "page_size": 101}):
        response = await call_mcp(client, tokens["access_token"], name="list_organization_directory", arguments=arguments)
        assert response.json()["result"].get("isError") is True
    missing = await call_mcp(client, tokens["access_token"], name="list_menu_records",
                             arguments={"kind": "entries", "plan_id": str(uuid.uuid4())})
    assert missing.json()["result"]["structuredContent"]["error"] == "invalid_office_query"
    _, denied_token = await connect(mcp_fixture, scopes=["mcp:diagnose"])
    denied = await call_mcp(client, denied_token["access_token"], name="list_menu_records", arguments={"kind": "categories"})
    assert denied.json()["result"]["structuredContent"]["error"] == "access_denied"
