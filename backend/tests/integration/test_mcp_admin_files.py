"""The management feed paginates all sources together without exposing file authority."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_contact_import_models import MCPContactImportUploadModel
from app.infrastructure.database.mcp_models import MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.mcp_whatsapp_media_models import MCPWhatsAppHeaderMediaModel
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    WhatsAppBroadcastGroupModel,
)
from tests.integration.test_mcp_authorization import mcp_fixture  # noqa: F401


@pytest.fixture
async def admin_files(mcp_fixture):  # noqa: F811 - pytest resolves the imported shared fixture
    client, session, _, user, _, dashboard = mcp_fixture
    now = datetime.now(UTC)
    agency = AgencyModel(name="File scope", email="file-scope@example.test")
    grant = MCPGrantModel(user_id=user.id, client_id="global-connects-desktop", name="Source connection",
        resource="http://localhost:8000/mcp", capabilities=["mcp:upload"], security_version=1,
        mfa_at=now, created_at=now, expires_at=now + timedelta(days=1))
    session.add_all([agency, grant])
    await session.flush()
    group = ClientGroupModel(agency_id=agency.id, name="File group", token=uuid.uuid4().hex)
    broadcast = WhatsAppBroadcastGroupModel(agency_id=agency.id, name="File broadcast")
    session.add_all([group, broadcast])
    await session.flush()
    artifact = MCPArtifactModel(user_id=user.id, grant_id=grant.id, agency_id=agency.id, group_id=group.id,
        direction="upload", purpose="passport_pdf", handle_hash="a" * 64, storage_key="private-document-key",
        filename="document.pdf", media_type="application/pdf", byte_size=10, sha256="b" * 64,
        created_at=now, expires_at=now + timedelta(hours=1))
    contact = MCPContactImportUploadModel(user_id=user.id, original_grant_id=grant.id, agency_id=agency.id,
        handle_hash="c" * 64, storage_key="private-contact-key", filename="contacts.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", byte_size=11,
        sha256="d" * 64, workbook_snapshot={"private_cells": ["private-recipient"]},
        created_at=now + timedelta(seconds=1), expires_at=now + timedelta(hours=1))
    media = MCPWhatsAppHeaderMediaModel(user_id=user.id, original_grant_id=grant.id, agency_id=agency.id,
        broadcast_id=broadcast.id, idempotency_hash="e" * 64, request_hash="f" * 64, handle_hash="1" * 64,
        original_storage_key="private-source-key", normalized_storage_key="private-normalized-key",
        original_sha256="2" * 64, normalized_sha256="3" * 64, original_byte_size=12, normalized_byte_size=13,
        filename="header.png", original_media_type="image/png", normalized_media_type="image/png",
        provider_media_id="private-provider-media", provider_phone_number_id="private-provider-phone",
        attempt_id=uuid.uuid4(), attempted_at=now, attempt_expires_at=now + timedelta(minutes=2),
        status="ready", created_at=now + timedelta(seconds=2), updated_at=now,
        expires_at=now + timedelta(hours=1))
    session.add_all([artifact, contact, media])
    await session.commit()
    return client, session, user, {"Authorization": f"Bearer {dashboard}"}, artifact, contact, media


async def test_management_files_globally_paginate_safe_metadata(admin_files):
    client, _, _, headers, artifact, contact, media = admin_files
    expected = [(media.id, "whatsapp_header", "ready"), (contact.id, "contact_workbook", "staged"),
                (artifact.id, "artifact", "available")]
    for offset, (identifier, kind, status) in enumerate(expected):
        response = await client.get(f"/api/v1/admin/mcp/artifacts?offset={offset}&limit=1", headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["next_offset"] == (offset + 1 if offset < 2 else None)
        assert len(payload["items"]) == 1
        item = payload["items"][0]
        assert (item["id"], item["kind"], item["status"]) == (str(identifier), kind, status)
        assert set(item) == {"id", "kind", "connection_id", "agency_id", "group_id", "broadcast_id",
            "direction", "purpose", "filename", "byte_size", "sha256", "created_at", "expires_at",
            "delivered_at", "attempt_deadline", "operation_id", "status"}
        assert "private-" not in response.text and "handle" not in response.text
        if kind != "artifact":
            assert item["group_id"] is None
        if kind == "whatsapp_header":
            assert item["broadcast_id"] == str(media.broadcast_id)
            assert "T" in item["attempt_deadline"]
    response = await client.get("/api/v1/admin/mcp/artifacts?limit=101", headers=headers)
    assert response.status_code == 422


async def test_retained_import_and_uncertain_upload_are_truthful_after_expiry(admin_files):
    client, session, user, headers, artifact, contact, media = admin_files
    now = datetime.now(UTC)
    operation = MCPOperationModel(user_id=user.id, initial_grant_id=artifact.grant_id,
        operation_name="ingest_pdf", capability="mcp:upload", idempotency_hash="4" * 64,
        payload_hash="5" * 64, workflow_id=uuid.uuid4(), status="succeeded", progress=1,
        stage="draft_created", initial_result={"saved": True})
    session.add(operation)
    await session.flush()
    artifact.ingestion_operation_id = operation.id
    contact.consumed_operation_id, contact.consumed_at = operation.id, now
    media.status = "unknown"
    for row in (artifact, contact, media):
        row.created_at, row.expires_at = now - timedelta(hours=2), now - timedelta(hours=1)
    await session.commit()
    response = await client.get("/api/v1/admin/mcp/artifacts", headers=headers)
    assert response.status_code == 200, response.text
    assert {row["kind"]: row["status"] for row in response.json()["items"]} == {
        "artifact": "ingested", "contact_workbook": "imported", "whatsapp_header": "unknown"}


@pytest.mark.parametrize("change", ["role", "inactive", "deleted"])
async def test_file_management_requires_current_active_superadmin(admin_files, change):
    client, session, user, headers, *_ = admin_files
    if change == "role":
        user.role = "agency_admin"
    elif change == "inactive":
        user.is_active = False
    else:
        user.deleted_at = datetime.now(UTC)
    await session.commit()
    response = await client.get("/api/v1/admin/mcp/artifacts", headers=headers)
    assert response.status_code in {401, 403}
    assert "header.png" not in response.text
