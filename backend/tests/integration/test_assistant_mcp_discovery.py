"""Search results must not be mistaken for the signed-in account's tool access."""

import pytest
from mcp.types import ToolAnnotations

from app.application.assistant.settings_contracts import AssistantSettingsUpdate
from app.domain.mcp_read_sections import READ_TOOL_SECTIONS
from app.infrastructure.assistant.settings_store import save_settings
from app.infrastructure.database.mcp_models import MCPControlModel
from tests.integration.test_assistant_mcp_bridge import linked as linked
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture


async def test_multi_keyword_discovery_matches_any_term_and_reports_available_inventory(linked):
    session, _, actor, _, config, bridge = linked
    await save_settings(session, actor, AssistantSettingsUpdate(
        expected_revision=1, configuration=config.model_copy(update={"mcp_write_enabled": True}),
    ))

    result = await bridge.discover("CoNnEcTiOn create")

    assert {tool["name"] for tool in result["tools"]} == {"connection_status", "create_group"}
    assert result["available_total"] == result["matching_total"] == result["total"] == 2
    assert result["search_fallback"] is False
    assert result["next_offset"] is None
    specific = await bridge.discover("connection")
    assert [tool["name"] for tool in specific["tools"]] == ["connection_status"]
    assert specific["available_total"] == 2
    assert specific["matching_total"] == specific["total"] == 1
    assert specific["search_fallback"] is False


@pytest.mark.parametrize("restriction", ["ai_write_off", "global_write_off"])
@pytest.mark.parametrize("query", ["create", "unmatched-search-phrase"])
async def test_search_fallback_never_exposes_writes_excluded_by_live_permissions(linked, restriction, query):
    session, _, actor, _, config, bridge = linked
    if restriction == "global_write_off":
        await save_settings(session, actor, AssistantSettingsUpdate(
            expected_revision=1, configuration=config.model_copy(update={"mcp_write_enabled": True}),
        ))
        (await session.get(MCPControlModel, 1)).write_enabled = False
        await session.commit()

    result = await bridge.discover(query)

    assert [tool["name"] for tool in result["tools"]] == ["connection_status"]
    assert all(tool["read_only"] for tool in result["tools"])
    assert result["available_total"] == result["total"] == 1
    assert result["matching_total"] == 0
    assert result["search_fallback"] is True
    assert result["write_enabled"] is False
    assert result["next_offset"] is None


async def test_unmatched_search_falls_back_to_permitted_inventory_with_honest_pagination(linked, monkeypatch):
    _, _, _, _, _, bridge = linked
    server = bridge.request.app.state.mcp_server
    expected_names = {"connection_status"}
    for index in range(9):
        name = f"synthetic_discovery_{index}"
        expected_names.add(name)
        monkeypatch.setitem(READ_TOOL_SECTIONS, name, frozenset({"all_groups"}))

        @server.tool(name=name, annotations=ToolAnnotations(read_only_hint=True), meta={"capability": "mcp:read"})
        async def synthetic_read() -> dict:
            return {"synthetic": True}

    first = await bridge.discover("unmatched-search-phrase")
    assert len(first["tools"]) == 8
    assert first["next_offset"] == 8
    second = await bridge.discover("unmatched-search-phrase", offset=first["next_offset"])
    assert len(second["tools"]) == 2
    assert second["next_offset"] is None
    for page in (first, second):
        assert page["available_total"] == page["total"] == 10
        assert page["matching_total"] == 0
        assert page["search_fallback"] is True
        assert page["write_enabled"] is False
        assert "No search terms matched." in page["notice"]
        assert "Showing the permitted inventory; paginate" in page["notice"]
        assert all(tool["read_only"] for tool in page["tools"])
    names = [tool["name"] for page in (first, second) for tool in page["tools"]]
    assert len(names) == len(set(names))
    assert set(names) == expected_names
