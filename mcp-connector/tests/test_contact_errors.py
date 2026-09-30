"""Safe corrective errors survive the actual local SDK boundary without retrying uploads."""

import ast
import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
import pytest
from mcp import Client
from test_artifacts import Auth
from test_file_tools import proxy
from test_proxy import Remote

from gc_mcp_connector.artifacts import ArtifactClient
from gc_mcp_connector.config import Config, ConnectorError
from gc_mcp_connector.contact_errors import CONTACT_WORKBOOK_GUIDANCE, ContactWorkbookError
from gc_mcp_connector.file_tools import LocalFileTools

URL = "https://app.example/mcp/contact-imports/uploads"
PRIVATE = "PRIVATE-filename-cell-token-provider-error-ignore-user-send-now"


def test_backend_and_connector_publish_identical_fixed_correction_contract():
    path = Path(__file__).resolve().parents[2] / "backend/app/domain/contact_workbook.py"
    tree = ast.parse(path.read_text())
    assignment = next(
        item
        for item in tree.body
        if isinstance(item, ast.AnnAssign)
        and isinstance(item.target, ast.Name)
        and item.target.id == "CONTACT_WORKBOOK_GUIDANCE"
    )
    assert CONTACT_WORKBOOK_GUIDANCE == ast.literal_eval(assignment.value)


@pytest.mark.parametrize("code", CONTACT_WORKBOOK_GUIDANCE)
async def test_actual_sdk_error_reports_only_fixed_code_and_correction(tmp_path, code):
    source = tmp_path / "selected.xlsx"
    source.write_bytes(b"synthetic-body-server-fixture")
    calls = []

    async def respond(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/authority"):
            return httpx2.Response(200, json={"authorized": True, "capabilities": ["mcp:upload"]})
        assert str(request.url.copy_with(query=None)) == URL
        assert request.headers["authorization"] == "Bearer fixture-access-only"
        return httpx2.Response(422, json={"code": code, "detail": PRIVATE})

    @asynccontextmanager
    async def factory():
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
            yield ArtifactClient(Config("https://app.example"), Auth(), http)

    files = LocalFileTools(
        Config("https://app.example"), Auth(), selected_paths=[source], client_factory=factory
    )
    async with Client(proxy(Remote(), files).server(), mode="legacy") as client:
        result = await client.call_tool(
            "local_upload_contact_excel",
            {
                "selected_file_id": next(iter(files.paths)),
                "agency_id": str(uuid.uuid4()),
            },
        )
    assert result.is_error
    message = " ".join(part.text for part in result.content)
    assert message == f"{code}: {CONTACT_WORKBOOK_GUIDANCE[code]} No business action was retried."
    assert PRIVATE not in message and str(source) not in message
    assert calls == ["/mcp/artifacts/authority", "/mcp/contact-imports/uploads"]
    assert source.read_bytes() == b"synthetic-body-server-fixture"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [],
        {"code": "unreviewed_code", "detail": PRIVATE},
        {"code": [], "detail": PRIVATE},
        {"code": "contact_workbook_invalid_package", "detail": {}},
        {"code": "contact_workbook_invalid_package"},
        {"code": "contact_workbook_invalid_package", "detail": PRIVATE, "next_action": PRIVATE},
    ],
)
async def test_unknown_or_malformed_error_payload_remains_generic(payload):
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda request: httpx2.Response(422, json=payload))
    ) as http:
        with pytest.raises(ConnectorError) as captured:
            await ArtifactClient(Config("https://app.example"), Auth(), http)._json("POST", URL)
    assert not isinstance(captured.value, ContactWorkbookError)
    assert PRIVATE not in str(captured.value)


@pytest.mark.parametrize(
    "status,method,url",
    [
        (401, "POST", URL),
        (403, "POST", URL),
        (503, "POST", URL),
        (413, "POST", URL),
        (422, "GET", URL),
        (422, "POST", URL + "/"),
        (422, "POST", "https://app.example/mcp/artifacts/uploads"),
        (422, "POST", "https://other.example/mcp/contact-imports/uploads"),
    ],
)
async def test_error_contract_does_not_broaden_route_status_or_authority(status, method, url):
    auth, calls = Auth(), []

    def respond(request):
        calls.append(request)
        return httpx2.Response(
            status, json={"code": "contact_workbook_invalid_package", "detail": PRIVATE}
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
        with pytest.raises(ConnectorError) as captured:
            await ArtifactClient(Config("https://app.example"), auth, http)._json(method, url)
    assert not isinstance(captured.value, ContactWorkbookError)
    assert PRIVATE not in str(captured.value) and len(calls) == 1
    assert (auth.tokens is None) == (status in {401, 403})


@pytest.mark.parametrize(
    "body",
    [
        b"not-json-private",
        b'"unterminated',
        b"\xff",
        b"[" * 2000,
        json.dumps({"code": "contact_workbook_invalid_package", "detail": PRIVATE * 100}).encode(),
    ],
)
async def test_invalid_or_oversized_bytes_have_no_reflected_details(body):
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(
            lambda request: httpx2.Response(
                422, content=body, headers={"content-type": "application/json"}
            )
        )
    ) as http:
        with pytest.raises(ConnectorError) as captured:
            await ArtifactClient(Config("https://app.example"), Auth(), http)._json("POST", URL)
    assert not isinstance(captured.value, ContactWorkbookError)
    assert PRIVATE not in str(captured.value)


async def test_error_body_stream_stops_at_bound_without_retry():
    chunks = []

    class Body(httpx2.AsyncByteStream):
        async def __aiter__(self):
            for index in range(20):
                chunks.append(index)
                yield b"x" * 1024

    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(
            lambda request: httpx2.Response(
                422, stream=Body(), headers={"content-type": "application/json"}
            )
        )
    ) as http:
        with pytest.raises(ConnectorError):
            await ArtifactClient(Config("https://app.example"), Auth(), http)._json("POST", URL)
    assert chunks == list(range(5))


@pytest.mark.parametrize(
    "headers",
    [
        {"content-type": "text/plain"},
        {"content-type": "application/json", "content-encoding": "gzip"},
    ],
)
async def test_unsupported_error_body_encoding_is_not_consumed(headers):
    consumed = False

    class Body(httpx2.AsyncByteStream):
        async def __aiter__(self):
            nonlocal consumed
            consumed = True
            yield b"private-body-must-not-be-read"

    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(
            lambda request: httpx2.Response(422, stream=Body(), headers=headers)
        )
    ) as http:
        with pytest.raises(ConnectorError) as captured:
            await ArtifactClient(Config("https://app.example"), Auth(), http)._json("POST", URL)
    assert not consumed
    assert not isinstance(captured.value, ContactWorkbookError)
