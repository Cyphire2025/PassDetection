from contextlib import asynccontextmanager

import pytest
from mcp import Client, types

from gc_mcp_connector.config import Config
from gc_mcp_connector.file_tools import DEFINITIONS
from gc_mcp_connector.proxy import RemoteProxy


def tool(name, capability="mcp:read", read=True):
    return types.Tool(
        name=name,
        input_schema={"type": "object"},
        meta={"capability": capability},
        annotations=types.ToolAnnotations(read_only_hint=read),
    )


class Remote:
    def __init__(self):
        self.tools = [
            tool("connection_status"),
            tool("list_groups"),
            tool("create_group", "mcp:change", False),
            tool("prepare_excel_export", "mcp:export", False),
            tool("undeclared", None),
            tool("false_read", read=False),
        ]
        self.calls = []

    async def list_tools(self, *, params):
        return types.ListToolsResult(tools=self.tools)

    async def call_tool(self, name, **kwargs):
        self.calls.append((name, kwargs))
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="Existing data")],
            structured_content={"observed": True},
        )


def proxy(remote):
    @asynccontextmanager
    async def session():
        yield remote

    return RemoteProxy(Config("https://app.test"), None, session, read_only=True)


@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_read_only_sdk_exposes_existing_reads_and_no_file_tools(mode):
    remote = Remote()
    async with Client(proxy(remote).server(), mode=mode) as client:
        listing = await client.list_tools()
        assert [item.name for item in listing.tools] == ["connection_status", "list_groups"]
        assert "read-only" in client.instructions
        result = await client.call_tool("list_groups", {"search": "Existing"})
        assert result.structured_content == {"observed": True}
        assert remote.calls == [
            (
                "list_groups",
                {
                    "arguments": {"search": "Existing"},
                    "input_responses": None,
                    "request_state": None,
                    "allow_input_required": True,
                },
            )
        ]


@pytest.mark.parametrize(
    "name",
    ["create_group", "prepare_excel_export", "undeclared", "false_read", "unknown", *DEFINITIONS],
)
async def test_direct_calls_cannot_bypass_read_only_discovery(name):
    remote = Remote()
    result = await proxy(remote).call_tool(None, types.CallToolRequestParams(name=name))
    assert result.is_error and "no action was dispatched" in result.content[0].text
    assert remote.calls == []


async def test_read_tool_removed_after_discovery_is_not_dispatched():
    remote = Remote()
    selected = proxy(remote)
    assert len((await selected.list_tools(None, None)).tools) == 2
    remote.tools = [tool("connection_status")]
    result = await selected.call_tool(None, types.CallToolRequestParams(name="list_groups"))
    assert result.is_error and remote.calls == []


async def test_bounded_paginated_lookup_preserves_current_read_authority():
    remote = Remote()
    cursors = []

    async def listing(*, params):
        cursor = params.cursor if params else None
        cursors.append(cursor)
        return types.ListToolsResult(
            tools=[tool("list_groups")] if cursor else [], next_cursor=None if cursor else "second"
        )

    remote.list_tools = listing
    result = await proxy(remote).call_tool(None, types.CallToolRequestParams(name="list_groups"))
    assert not result.is_error and cursors == [None, "second"]


async def test_repeating_cursor_fails_closed_without_dispatch():
    remote = Remote()
    cursors = []

    async def listing(*, params):
        cursors.append(params.cursor if params else None)
        return types.ListToolsResult(tools=[], next_cursor="repeated")

    remote.list_tools = listing
    result = await proxy(remote).call_tool(None, types.CallToolRequestParams(name="list_groups"))
    assert result.is_error and cursors == [None, "repeated"] and remote.calls == []
