import json
from contextlib import asynccontextmanager

import httpx2
import pytest
from mcp import Client, types

from gc_mcp_connector.config import Config
from gc_mcp_connector.proxy import RemoteProxy


class Remote:
    def __init__(self):
        self.calls = []
        self.fail = False

    async def list_tools(self, *, params):
        self.calls.append(("list", params.cursor if params else None))
        if self.fail:
            raise RuntimeError("secret remote network error")
        return types.ListToolsResult(
            tools=[types.Tool(name="connection_status", input_schema={"type": "object"})],
            next_cursor="next-page",
        )

    async def call_tool(self, name, **kwargs):
        self.calls.append((name, kwargs))
        if self.fail:
            raise RuntimeError("secret remote network error")
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="Connected")],
            structured_content={"observed": True},
        )


def proxy_for(remote):
    @asynccontextmanager
    async def session():
        yield remote

    return RemoteProxy(Config("https://app.test"), None, session)


async def test_sdk_handshake_and_typed_proxy_preserve_tools_pagination_arguments_results():
    remote = Remote()
    async with Client(proxy_for(remote).server(), mode="legacy") as client:
        listing = await client.list_tools()
        assert listing.tools[0].name == "connection_status"
        assert listing.next_cursor == "next-page"
        result = await client.call_tool("connection_status", {"record": "explicit-id"})
        assert result.structured_content == {"observed": True}
        assert result.content[0].text == "Connected"
    assert remote.calls[-1][1]["arguments"] == {"record": "explicit-id"}


async def test_cursor_is_forwarded_without_fetching_unbounded_pages():
    remote = Remote()
    result = await proxy_for(remote).list_tools(
        None, types.PaginatedRequestParams(cursor="page-two")
    )
    assert result.next_cursor == "next-page"
    assert remote.calls == [("list", "page-two")]


async def test_failure_is_uncertain_sanitized_and_not_retried():
    remote = Remote()
    remote.fail = True
    proxy = proxy_for(remote)
    result = await proxy.call_tool(
        None, types.CallToolRequestParams(name="dispatch", arguments={"operation_id": "op-1"})
    )
    assert result.is_error
    assert "uncertain" in result.content[0].text
    assert "secret" not in result.content[0].text
    assert len(remote.calls) == 1
    with pytest.raises(ValueError, match="unavailable"):
        await proxy.list_tools(None, None)


async def test_remote_streamable_http_boundary_uses_resource_bearer_and_no_delete(monkeypatch):
    calls = []

    class Authorization:
        tokens = None

        async def access_token(self):
            return "fixture-access-token"

    def respond(request):
        assert request.headers["Authorization"] == "Bearer fixture-access-token"
        assert str(request.url) == "https://app.test/mcp"
        calls.append(request.method)
        if request.method == "GET":
            return httpx2.Response(405)
        body = json.loads(request.content)
        if "id" not in body:
            return httpx2.Response(202)
        if body["method"] == "initialize":
            result = {
                "protocolVersion": body["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fixture", "version": "1"},
            }
        elif body["method"] == "tools/list":
            result = {"tools": [{"name": "connection_status", "inputSchema": {"type": "object"}}]}
        elif body["method"] == "tools/call":
            result = {"content": [{"type": "text", "text": "Remote HTTP verified"}]}
        else:
            raise AssertionError(body["method"])
        return httpx2.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    original_client = httpx2.AsyncClient
    monkeypatch.setattr(
        "gc_mcp_connector.proxy.httpx2.AsyncClient",
        lambda **kwargs: original_client(transport=httpx2.MockTransport(respond), **kwargs),
    )
    proxy = RemoteProxy(Config("https://app.test"), Authorization())
    listing = await proxy.list_tools(None, None)
    assert listing.tools[0].name == "connection_status"
    result = await proxy.call_tool(None, types.CallToolRequestParams(name="connection_status"))
    assert not result.is_error
    assert result.content[0].text == "Remote HTTP verified"
    assert "DELETE" not in calls
