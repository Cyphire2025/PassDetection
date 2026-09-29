"""Streaming transfer documentation matches actual auth, bytes and typed receipts."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.presentation.api.v1.routes import mcp_artifacts, mcp_contact_imports, mcp_whatsapp_media
from app.presentation.api.v1.schemas.mcp_transfer_schemas import (
    XLSX_MEDIA,
    MCPArtifactMetadata,
    MCPContactUpload,
    MCPHeaderMedia,
)
from tests.integration.test_mcp_artifacts import artifacts as artifacts
from tests.integration.test_mcp_artifacts import upload as upload_pdf
from tests.integration.test_mcp_contact_imports import contact_import as contact_import
from tests.integration.test_mcp_contact_imports import upload as upload_contacts
from tests.integration.test_mcp_whatsapp_media import media as media
from tests.integration.test_mcp_whatsapp_media import upload as upload_media


def transport_app():
    app = FastAPI()
    for module in (mcp_artifacts, mcp_contact_imports, mcp_whatsapp_media):
        app.include_router(module.router)
    return app


def test_every_transfer_operation_documents_only_required_bearer_security():
    contract = transport_app().openapi()
    assert len(contract["paths"]) == 10
    for path in contract["paths"].values():
        for operation in path.values():
            assert operation["security"] == [{"HTTPBearer": []}]
            assert operation["responses"]["401"]["content"]["application/json"]["schema"]["anyOf"]


@pytest.mark.parametrize(
    "path,media_types,headers",
    [
        ("/mcp/artifacts/uploads", {"application/pdf"}, {"X-Artifact-Size", "X-Artifact-SHA256"}),
        ("/mcp/contact-imports/uploads", {XLSX_MEDIA}, {"X-Artifact-Size", "X-Artifact-SHA256"}),
        (
            "/mcp/whatsapp-media/uploads",
            {"image/jpeg", "image/png"},
            {"X-Artifact-Size", "X-Artifact-SHA256", "Idempotency-Key"},
        ),
    ],
)
def test_raw_upload_contracts_declare_actual_created_status_binary_body_and_headers(
    path, media_types, headers
):
    operation = transport_app().openapi()["paths"][path]["post"]
    assert "201" in operation["responses"] and "200" not in operation["responses"]
    assert operation["responses"]["201"]["content"]["application/json"]["schema"]["$ref"]
    assert operation["requestBody"]["required"]
    assert set(operation["requestBody"]["content"]) == media_types
    assert all(
        content["schema"] == {"type": "string", "format": "binary"}
        for content in operation["requestBody"]["content"].values()
    )
    documented = {
        parameter["name"]
        for parameter in operation["parameters"]
        if parameter["in"] == "header" and parameter["required"]
    }
    assert documented == headers


def test_metadata_does_not_create_fastapi_body_buffering_and_download_is_binary():
    app = transport_app()
    for route in app.routes:
        if isinstance(route, APIRoute):
            assert route.body_field is None
    paths = app.openapi()["paths"]
    download = paths["/mcp/artifacts/{handle}/content"]["get"]["responses"]["200"]
    assert set(download["content"]) == {"application/pdf", XLSX_MEDIA, "application/zip"}
    assert {"X-Artifact-Size", "X-Artifact-SHA256", "Content-Length"} <= set(download["headers"])
    ack = paths["/mcp/artifacts/{handle}/delivery"]["post"]["requestBody"]
    assert set(ack["content"]["application/json"]["schema"]["required"]) == {"byte_size", "sha256"}


async def test_real_pdf_response_matches_declared_schema(artifacts):
    response = await upload_pdf(artifacts)
    assert response.status_code == 201
    assert MCPArtifactMetadata.model_validate(response.json()).direction == "upload"


async def test_real_contact_upload_response_matches_declared_schema(contact_import):
    response = await upload_contacts(contact_import)
    assert response.status_code == 201
    assert MCPContactUpload.model_validate(response.json()).business_import == "not_started"


async def test_real_header_upload_and_replay_match_declared_receipt(media):
    first, replay = await upload_media(media), await upload_media(media)
    assert first.status_code == replay.status_code == 201
    parsed = MCPHeaderMedia.model_validate(first.json())
    assert parsed.status == "ready" and parsed.messages_queued == 0
    assert (
        MCPHeaderMedia.model_validate(replay.json()).media_artifact_id == parsed.media_artifact_id
    )


@pytest.mark.parametrize("headers", ["duplicate", "lowercase", "empty", "dashboard"])
async def test_exact_raw_authorization_remains_strict_and_rejects_before_body_read(
    artifacts, headers
):
    f = artifacts
    values = {
        "duplicate": [f"Bearer {f.token}", f"Bearer {f.token}"],
        "lowercase": [f"bearer {f.token}"],
        "empty": ["Bearer "],
        "dashboard": ["Bearer dashboard.jwt.invalid"],
    }[headers]
    consumed = False

    async def body():
        nonlocal consumed
        consumed = True
        yield b"should-not-be-read"

    response = await f.client.post(
        "/mcp/artifacts/uploads",
        params={
            "agency_id": str(f.agency.id),
            "group_id": str(f.group.id),
            "filename": "fixture.pdf",
        },
        headers=[
            *(("Authorization", value) for value in values),
            ("Content-Type", "application/pdf"),
            ("X-Artifact-Size", "18"),
            ("X-Artifact-SHA256", "a" * 64),
        ],
        content=body(),
    )
    assert response.status_code == 401 and not consumed
