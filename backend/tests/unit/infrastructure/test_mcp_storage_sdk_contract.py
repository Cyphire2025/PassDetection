"""Exercise the installed SDK's validation, serialization and request signing."""

from __future__ import annotations

import hashlib
import io

import boto3
import pytest
from botocore.awsrequest import AWSResponse
from botocore.config import Config

from app.domain.exceptions.exceptions import StorageError
from app.infrastructure.storage.mcp_artifact_storage import MCPArtifactStorage


class ResponseBody(io.BytesIO):
    def stream(self, amt=None, decode_content=False):
        yield self.read()


@pytest.mark.parametrize("conflict", [409, 412])
async def test_installed_sdk_sends_signed_create_only_put_and_preserves_conflicts(
    test_settings, conflict
):
    client = boto3.client(
        "s3", region_name="us-east-1", endpoint_url="https://storage.example.invalid",
        aws_access_key_id="synthetic-sdk-contract", aws_secret_access_key="synthetic-sdk-contract",
        config=Config(signature_version="s3v4", retries={"total_max_attempts": 1}),
    )
    requests = []
    retained = []

    def transport(request, **_):
        # before-send runs after the real parameter validator, serializer and signer.
        # Returning a response here guarantees no network I/O or real credentials.
        headers = {key.lower(): value for key, value in request.headers.items()}
        assert headers["if-none-match"] == b"*"
        assert b"if-none-match" in headers["authorization"].split(b"SignedHeaders=", 1)[1].split(b",", 1)[0]
        body = request.body.read()
        assert headers["x-amz-meta-sha256"].decode() == hashlib.sha256(body).hexdigest()
        requests.append(body)
        if not retained:
            retained.append(body)
            return AWSResponse(request.url, 200, {}, ResponseBody(b""))
        code = "PreconditionFailed" if conflict == 412 else "ConditionalRequestConflict"
        return AWSResponse(request.url, conflict, {"content-type": "application/xml"},
                           ResponseBody(f"<Error><Code>{code}</Code></Error>".encode()))

    client.meta.events.register("before-send.s3.PutObject", transport)
    adapter = object.__new__(MCPArtifactStorage)
    adapter._client = client
    adapter.settings = test_settings.s3

    async def put(body):
        await adapter.put_transfer(
            io.BytesIO(body), key="mcp-transfers/v1/installed-sdk-contract", size=len(body),
            sha256=hashlib.sha256(body).hexdigest(), media_type="application/octet-stream",
        )

    try:
        await put(b"original")
        with pytest.raises(StorageError):
            await put(b"replacement")
        assert requests == [b"original", b"replacement"]
        assert retained == [b"original"]
    finally:
        client.close()
