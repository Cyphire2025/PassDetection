from contextlib import asynccontextmanager

import httpx2
import pytest
from mcp import Client, types
from test_artifacts import DATA, HANDLE, Auth, metadata
from test_proxy import Remote

from gc_mcp_connector.artifacts import ArtifactClient
from gc_mcp_connector.config import Config, ConnectorError
from gc_mcp_connector.file_tools import LocalFileTools
from gc_mcp_connector.proxy import RemoteProxy


def proxy(remote, files):
    @asynccontextmanager
    async def session():
        yield remote

    return RemoteProxy(Config("https://app.example"), Auth(), session, file_tools=files)


async def test_sdk_local_download_verifies_bytes_and_retains_failed_ack_recovery(tmp_path):
    destination = tmp_path / "requested.xlsx"
    artifact = metadata(filename="../../redirected", content_path="https://attacker.example/steal")
    requests = []
    acknowledge = False

    def respond(request):
        requests.append(request)
        assert request.url.host == "app.example"
        assert request.headers["authorization"] == "Bearer fixture-access-only"
        if request.url.path.endswith("/authority"):
            return httpx2.Response(200, json={"authorized": True, "capabilities": ["mcp:export"]})
        if request.url.path.endswith("/content"):
            return httpx2.Response(
                200,
                content=DATA,
                headers={
                    "X-Artifact-SHA256": artifact["sha256"],
                    "X-Artifact-Size": str(len(DATA)),
                },
            )
        if request.url.path.endswith("/delivery"):
            assert destination.read_bytes() == DATA
            return (
                httpx2.Response(200, json={**artifact, "delivered_at": "verified"})
                if acknowledge
                else httpx2.Response(503)
            )
        return httpx2.Response(200, json=artifact)

    @asynccontextmanager
    async def client_factory():
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
            yield ArtifactClient(Config("https://app.example"), Auth(), http)

    files = LocalFileTools(
        Config("https://app.example"),
        Auth(),
        download_directory=tmp_path,
        client_factory=client_factory,
    )
    remote = Remote()
    async with Client(proxy(remote, files).server(), mode="legacy") as client:
        listing = await client.list_tools()
        assert {tool.name for tool in listing.tools} >= {
            "local_upload_pdf",
            "local_download_export",
        }
        result = await client.call_tool(
            "local_download_export", {"artifact_id": HANDLE, "filename": destination.name}
        )
        assert not result.is_error
        assert result.structured_content["file"]["path"] == str(destination)
        assert not result.structured_content["server_delivery_acknowledged"]
        assert destination.read_bytes() == DATA
        selected = await client.call_tool("local_selected_files", {})
        selection = selected.structured_content["files"][0]["selected_file_id"]
        acknowledge = True
        recovered = await client.call_tool(
            "local_acknowledge_export", {"artifact_id": HANDLE, "selected_file_id": selection}
        )
        assert recovered.structured_content["server_delivery_acknowledged"]
        duplicate = await client.call_tool(
            "local_download_export", {"artifact_id": HANDLE, "filename": destination.name}
        )
        assert duplicate.is_error
        assert destination.read_bytes() == DATA
    assert [call[0] for call in remote.calls] == ["list"]
    assert len([request for request in requests if request.url.path.endswith("/content")]) == 1


async def test_remote_content_cannot_widen_selected_files_or_local_destinations(tmp_path):
    source = tmp_path / "provided.pdf"
    source.write_bytes(b"%PDF-fixture")
    calls = []

    class SelectionAuthority:
        async def authority(self, capability=None):
            calls.append("authority")

    @asynccontextmanager
    async def forbidden_client():
        yield SelectionAuthority()

    files = LocalFileTools(
        Config("https://app.example"),
        Auth(),
        selected_paths=[source],
        client_factory=forbidden_client,
    )
    async with Client(proxy(Remote(), files).server(), mode="legacy") as client:
        listing = await client.call_tool("local_selected_files", {})
        assert listing.structured_content["files"][0]["filename"] == "provided.pdf"
        assert calls == ["authority"]
        calls.clear()
        result = await client.call_tool(
            "local_upload_pdf",
            {
                "selected_file_id": "0" * 16,
                "agency_id": "00000000-0000-4000-8000-000000000001",
                "group_id": "00000000-0000-4000-8000-000000000002",
                "path": str(tmp_path / "unrelated.pdf"),
            },
        )
        assert result.is_error
        assert not calls
        download = await client.call_tool(
            "local_download_export", {"artifact_id": HANDLE, "filename": "export.xlsx"}
        )
        assert download.is_error and "download-directory" in download.content[0].text


@pytest.mark.parametrize(
    "filename",
    ["../secret", "C:\\secret", "..", "CON.txt", "stream:secret", "name.", "path/subfolder.xlsx"],
)
def test_download_names_cannot_escape_selected_directory(tmp_path, filename):
    files = LocalFileTools(Config("https://app.example"), Auth(), download_directory=tmp_path)
    with pytest.raises(ConnectorError, match="filename"):
        files.destination(filename)


async def test_remote_discovery_cannot_override_reserved_local_tool_names(tmp_path):
    remote = Remote()

    async def conflicting(*, params):
        return types.ListToolsResult(
            tools=[types.Tool(name="local_upload_pdf", input_schema={"type": "object"})]
        )

    remote.list_tools = conflicting
    with pytest.raises(ValueError, match="unavailable"):
        await proxy(remote, LocalFileTools(Config("https://app.example"), Auth())).list_tools(
            None, None
        )


async def test_local_tools_are_added_once_without_consuming_remote_pages(tmp_path):
    remote = Remote()
    bridge = proxy(remote, LocalFileTools(Config("https://app.example"), Auth()))
    first = await bridge.list_tools(None, None)
    following = await bridge.list_tools(None, types.PaginatedRequestParams(cursor="next-page"))
    assert first.next_cursor == following.next_cursor == "next-page"
    assert len(first.tools) == 9 and len(following.tools) == 1
    assert remote.calls == [("list", None), ("list", "next-page")]


def test_startup_selection_rejects_directories_and_codex_credentials(tmp_path):
    with pytest.raises(ConnectorError, match="regular files"):
        LocalFileTools(Config("https://app.example"), Auth(), selected_paths=[tmp_path])
    private = tmp_path / ".codex" / "auth.json"
    private.parent.mkdir()
    private.write_text("synthetic-private-credential")
    with pytest.raises(ConnectorError, match="credential"):
        LocalFileTools(Config("https://app.example"), Auth(), selected_paths=[private])


async def test_revoked_authority_prevents_local_listing_and_opening_selected_upload(tmp_path):
    source = tmp_path / "private-selected.pdf"
    source.write_bytes(b"%PDF-private")
    calls = []

    class Denied:
        async def authority(self, capability=None):
            calls.append(capability)
            raise ConnectorError("Connection revoked")

        async def upload_pdf(self, *args, **kwargs):
            pytest.fail("A denied connection must not open or upload the selected file")

    @asynccontextmanager
    async def denied_client():
        yield Denied()

    files = LocalFileTools(
        Config("https://app.example"), Auth(), selected_paths=[source], client_factory=denied_client
    )
    async with Client(proxy(Remote(), files).server(), mode="legacy") as client:
        listing = await client.call_tool("local_selected_files", {})
        assert listing.is_error and source.name not in listing.content[0].text
        upload = await client.call_tool(
            "local_upload_pdf",
            {
                "selected_file_id": next(iter(files.paths)),
                "agency_id": "00000000-0000-4000-8000-000000000001",
                "group_id": "00000000-0000-4000-8000-000000000002",
            },
        )
        assert upload.is_error and calls == [None, "mcp:upload"]
