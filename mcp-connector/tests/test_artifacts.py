import hashlib
import json
import uuid

import httpx2
import pytest

from gc_mcp_connector.artifacts import ArtifactClient
from gc_mcp_connector.config import Config, ConnectorError

HANDLE = "gcmcp_artifact_" + "a" * 64
DATA = b"verified-artifact-fixture"


class Auth:
    tokens = object()

    async def access_token(self):
        return "fixture-access-only"


def metadata(**overrides):
    return {
        "artifact_id": HANDLE,
        "direction": "export",
        "purpose": "passport_excel",
        "agency_id": str(uuid.uuid4()),
        "group_id": str(uuid.uuid4()),
        "byte_size": len(DATA),
        "sha256": hashlib.sha256(DATA).hexdigest(),
        **overrides,
    }


async def test_typed_paths_ignore_remote_urls_and_ack_only_after_verified_save(tmp_path):
    destination = tmp_path / "explicit.xlsx"
    artifact = metadata(content_path="https://attacker.example/steal-token", filename="../../evil")
    requested = []

    def handler(request):
        requested.append(str(request.url))
        assert (
            request.url.host == "app.example"
            and request.headers["authorization"] == "Bearer fixture-access-only"
        )
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
            assert json.loads(request.content) == {
                "byte_size": len(DATA),
                "sha256": artifact["sha256"],
            }
            return httpx2.Response(200, json={**artifact, "delivered_at": "2026-09-29T12:00:00Z"})
        return httpx2.Response(200, json=artifact)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
        client = ArtifactClient(Config("https://app.example"), Auth(), http)
        result = await client.download(HANDLE, destination=destination)
        assert result.server_delivery_acknowledged and result.file.path == str(destination)
        with pytest.raises(ConnectorError, match="new local filename"):
            await client.download(HANDLE, destination=destination)
    assert len(requested) == 3


@pytest.mark.parametrize("failure", ["corrupt", "redirect", "headers"])
async def test_failed_transfers_never_publish_or_acknowledge(tmp_path, failure):
    artifact = metadata()
    requested = []

    def handler(request):
        requested.append(request.url.path)
        if request.url.path.endswith("/content"):
            if failure == "redirect":
                return httpx2.Response(302, headers={"Location": "https://attacker.example"})
            return httpx2.Response(
                200,
                content=b"changed" if failure == "corrupt" else DATA,
                headers={
                    "X-Artifact-SHA256": "0" * 64 if failure == "headers" else artifact["sha256"],
                    "X-Artifact-Size": str(len(DATA)),
                },
            )
        return httpx2.Response(200, json=artifact)

    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(handler), follow_redirects=True
    ) as http:
        with pytest.raises(ConnectorError):
            await ArtifactClient(Config("https://app.example"), Auth(), http).download(
                HANDLE, destination=tmp_path / "export.xlsx"
            )
    assert len(requested) == 2 and list(tmp_path.iterdir()) == []


async def test_ack_failure_preserves_verified_file_and_explicit_recovery(tmp_path):
    artifact = metadata()
    acknowledged = False
    destination = tmp_path / "export.xlsx"

    def handler(request):
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
            return (
                httpx2.Response(200, json={**artifact, "delivered_at": "2026-09-29T12:00:00Z"})
                if acknowledged
                else httpx2.Response(503)
            )
        return httpx2.Response(200, json=artifact)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
        client = ArtifactClient(Config("https://app.example"), Auth(), http)
        result = await client.download(HANDLE, destination=destination)
        assert not result.server_delivery_acknowledged and destination.read_bytes() == DATA
        acknowledged = True
        result = await client.acknowledge_existing(
            HANDLE, path=destination, allowed_paths=frozenset({destination.resolve()})
        )
        assert result.server_delivery_acknowledged


async def test_upload_is_explicit_streamed_and_receipt_bound_to_group(tmp_path):
    source = tmp_path / "chosen.pdf"
    source.write_bytes(DATA)
    agency, group = uuid.uuid4(), uuid.uuid4()
    requests = 0

    async def handler(request):
        nonlocal requests
        requests += 1
        assert await request.aread() == DATA
        assert request.headers["x-artifact-sha256"] == hashlib.sha256(DATA).hexdigest()
        return httpx2.Response(
            201,
            json=metadata(
                direction="upload",
                purpose="group_document_pdf",
                agency_id=str(agency),
                group_id=str(group),
            ),
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
        client = ArtifactClient(Config("https://app.example"), Auth(), http)
        with pytest.raises(ConnectorError, match="not explicitly provided"):
            await client.upload_pdf(
                source, allowed_paths=frozenset(), agency_id=agency, group_id=group
            )
        result = await client.upload_pdf(
            source, allowed_paths=frozenset({source.resolve()}), agency_id=agency, group_id=group
        )
        assert result.direction == "upload" and requests == 1
        for handle in ["../secret", "https://attacker.example/secret", HANDLE + "?token=x"]:
            with pytest.raises(ConnectorError, match="exact artifact ID"):
                await client.metadata(handle)
