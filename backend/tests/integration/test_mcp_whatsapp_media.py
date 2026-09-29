"""Scanned header media with real SQL and deterministic provider I/O."""

from __future__ import annotations

import asyncio
import hashlib
import io
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import func, select

from app.application.mcp.artifacts import ArtifactError
from app.application.mcp.whatsapp_media_access import MCPWhatsAppMediaAccess
from app.application.mcp.whatsapp_media_uploads import MCPWhatsAppMediaUploads
from app.infrastructure.database.mcp_models import MCPGrantModel
from app.infrastructure.database.mcp_whatsapp_media_models import (
    MCPWhatsAppHeaderAccessModel,
    MCPWhatsAppHeaderMediaModel,
)
from app.infrastructure.database.models import WhatsAppBroadcastGroupModel, WhatsAppMessageLogModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.whatsapp.cloud_api_provider import WhatsAppCloudApiError
from app.presentation.api.v1.routes.mcp_whatsapp_media import router
from tests.integration.test_mcp_artifacts import artifacts as artifacts
from tests.integration.test_mcp_artifacts import chunks


def picture(color="red"):
    output = io.BytesIO()
    with Image.new("RGB", (16, 16), color) as source:
        source.save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
async def media(artifacts, monkeypatch):
    f = artifacts
    f.settings = f.settings.model_copy(
        update={
            "whatsapp_access_token": "synthetic-provider-token",
            "whatsapp_phone_number_id": "synthetic-sender",
        }
    )
    f.token, f.principal = await f.connect(["mcp:upload", "mcp:communicate", "mcp:read"])
    f.agency_id, f.broadcast_id = f.agency.id, uuid.uuid4()
    f.session.add(
        WhatsAppBroadcastGroupModel(
            id=f.broadcast_id,
            agency_id=f.agency_id,
            name="Header fixture",
            created_by_user_id=f.principal.user_id,
        )
    )
    await f.session.commit()
    f.provider = AsyncMock(return_value="synthetic-media-receipt")
    monkeypatch.setattr(
        "app.application.mcp.whatsapp_media_uploads.upload_whatsapp_image", f.provider
    )
    app = FastAPI()
    (
        app.state.settings,
        app.state.mcp_whatsapp_media_storage,
        app.state.mcp_whatsapp_media_security,
    ) = f.settings, f.storage, f.security
    app.include_router(router)

    async def database():
        yield f.session

    app.dependency_overrides[get_db_session] = database
    f.media_service = MCPWhatsAppMediaUploads(
        f.session, f.settings, storage=f.storage, security=f.security
    )
    async with AsyncClient(
        transport=ASGITransport(app),
        base_url="http://localhost:8000",
        headers={"Authorization": f"Bearer {f.token}"},
    ) as client:
        f.media_client = client
        yield f


async def upload(f, content=None, *, key="stable-header-upload-001", headers=None, params=None):
    content = picture() if content is None else content
    return await f.media_client.post(
        "/mcp/whatsapp-media/uploads",
        params={
            "agency_id": str(f.agency_id),
            "broadcast_id": str(f.broadcast_id),
            "filename": "header.png",
            **(params or {}),
        },
        headers={
            "Content-Type": "image/png",
            "X-Artifact-Size": str(len(content)),
            "X-Artifact-SHA256": hashlib.sha256(content).hexdigest(),
            "Idempotency-Key": key,
            **(headers or {}),
        },
        content=chunks(content),
    )


async def count(f, model):
    return await f.session.scalar(select(func.count()).select_from(model))


async def test_scanned_original_and_exact_provider_bytes_retained_with_hidden_provider_id(media):
    f = media
    content = picture()
    response = await upload(f, content)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["status"] == "ready" and result["messages_queued"] == 0
    assert "provider_media_id" not in result and "storage_key" not in result
    row = await f.session.get(MCPWhatsAppHeaderMediaModel, uuid.UUID(result["media_artifact_id"]))
    assert row.status == "ready" and row.provider_media_id == "synthetic-media-receipt"
    assert row.attempt_id is not None and row.revision == 3
    assert f.storage.objects[row.original_storage_key][0] == content
    sent = f.provider.await_args.kwargs["file_content"]
    assert sent == f.storage.objects[row.normalized_storage_key][0]
    assert hashlib.sha256(sent).hexdigest() == result["provider_content_sha256"]
    assert f.scanner.calls == 1 and await count(f, WhatsAppMessageLogModel) == 0
    # A retried request does not scan or send bytes again.
    replay = await upload(f, content)
    assert replay.json() == result and f.provider.await_count == 1 and f.scanner.calls == 1


async def test_same_key_changed_image_or_destination_conflicts_without_new_side_effects(media):
    f = media
    assert (await upload(f)).status_code == 201
    changed = await upload(f, picture("blue"))
    assert changed.status_code == 409
    assert f.provider.await_count == 1 and await count(f, MCPWhatsAppHeaderMediaModel) == 1


@pytest.mark.parametrize(
    "code,expected",
    [
        ("WHATSAPP_MEDIA_UPLOAD_UNREACHABLE", "failed"),
        ("WHATSAPP_MEDIA_UPLOAD_INTERRUPTED", "unknown"),
        ("WHATSAPP_MEDIA_UPLOAD_REJECTED", "unknown"),
    ],
)
async def test_provider_failure_or_uncertain_receipt_is_never_automatically_reuploaded(
    media, code, expected
):
    f = media
    f.provider.side_effect = WhatsAppCloudApiError("fixture diagnostic excluded", code=code)
    response = await upload(f)
    assert response.status_code == 201
    result = response.json()
    assert result["status"] == expected and "fixture diagnostic" not in response.text
    f.provider.side_effect = None
    assert (await upload(f)).json() == result
    assert f.provider.await_count == 1
    token, _ = await f.connect(["mcp:upload", "mcp:communicate"])
    recovered = await f.media_client.post(
        f"/mcp/whatsapp-media/{result['media_artifact_id']}/recover",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert recovered.status_code == 409 and f.provider.await_count == 1


async def test_ready_recovery_uses_new_grant_without_reupload_after_origin_revocation(media):
    f = media
    original = (await upload(f)).json()
    grant = await f.session.get(MCPGrantModel, f.principal.grant_id)
    grant.revoked_at = datetime.now(UTC)
    await f.session.commit()
    token, _ = await f.connect(["mcp:upload", "mcp:communicate"])
    response = await f.media_client.post(
        f"/mcp/whatsapp-media/{original['media_artifact_id']}/recover",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    recovered = response.json()
    assert recovered["media_handle"] != original["media_handle"]
    assert recovered["media_artifact_id"] == original["media_artifact_id"]
    assert recovered["provider_content_sha256"] == original["provider_content_sha256"]
    assert f.provider.await_count == 1 and len(f.storage.objects) == 2
    assert await count(f, MCPWhatsAppHeaderAccessModel) == 2
    foreign_handle = await f.media_client.get(
        f"/mcp/whatsapp-media/{original['media_handle']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert foreign_handle.status_code == 404
    ready = await f.media_client.get(
        f"/mcp/whatsapp-media/{recovered['media_handle']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ready.status_code == 200 and ready.json()["status"] == "ready"


@pytest.mark.parametrize("scopes", [["mcp:upload"], ["mcp:communicate"], ["mcp:read"]])
async def test_both_upload_and_communicate_are_required(media, scopes):
    f = media
    token, _ = await f.connect(scopes)
    response = await upload(f, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    f.provider.assert_not_awaited()
    assert await count(f, MCPWhatsAppHeaderMediaModel) == 0


@pytest.mark.parametrize(
    "invalid",
    ["foreign_agency", "missing_broadcast", "archive", "checksum", "media", "malformed", "key"],
)
async def test_invalid_uploads_do_not_claim_or_contact_provider(media, invalid):
    f = media
    headers, params, content = {}, {}, None
    if invalid == "foreign_agency":
        params["agency_id"] = str(uuid.uuid4())
    if invalid == "missing_broadcast":
        params["broadcast_id"] = str(uuid.uuid4())
    if invalid == "archive":
        row = await f.session.get(WhatsAppBroadcastGroupModel, f.broadcast_id)
        row.archived_at = datetime.now(UTC)
        await f.session.commit()
    if invalid == "checksum":
        headers["X-Artifact-SHA256"] = "0" * 64
    if invalid == "media":
        headers["Content-Type"] = "image/gif"
    if invalid == "malformed":
        content = b"not an image"
    if invalid == "key":
        headers["Idempotency-Key"] = "short"
    response = await upload(f, content, headers=headers, params=params)
    assert response.status_code in {403, 422}
    f.provider.assert_not_awaited()
    assert await count(f, MCPWhatsAppHeaderMediaModel) == 0


async def test_crash_after_durable_claim_keeps_future_attempt_pending_then_unknown_without_retry(
    media,
):
    f = media
    started, release = asyncio.Event(), asyncio.Event()

    async def interrupted(**_):
        started.set()
        await release.wait()
        return "should-not-complete"

    f.provider.side_effect = interrupted
    task = asyncio.create_task(upload(f))
    await asyncio.wait_for(started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await f.session.rollback()
    retry = await upload(f)
    assert retry.status_code == 201 and retry.json()["status"] == "uploading"
    row = await f.session.get(
        MCPWhatsAppHeaderMediaModel, uuid.UUID(retry.json()["media_artifact_id"])
    )
    row.attempted_at = datetime.now(UTC) - timedelta(minutes=3)
    row.attempt_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await f.session.commit()
    final = await f.media_client.get(f"/mcp/whatsapp-media/{retry.json()['media_handle']}")
    assert final.status_code == 200 and final.json()["status"] == "unknown"
    assert f.provider.await_count == 1


async def test_sender_context_change_and_source_corruption_fail_closed(media, monkeypatch):
    f = media
    f.storage.corrupt = True
    response = await upload(f)
    assert response.status_code == 201 and response.json()["status"] == "failed"
    f.provider.assert_not_awaited()
    f.storage.corrupt = False
    ready = (await upload(f, key="second-valid-header-intent")).json()
    f.settings.whatsapp_phone_number_id = "different-sender"
    assert (await upload(f, key="second-valid-header-intent")).status_code == 409
    assert f.provider.await_count == 1
    # Current metadata remains an observation, but explicit recovery validates sender context.
    with pytest.raises(ArtifactError, match="another sender"):
        await MCPWhatsAppMediaAccess(f.session, f.settings).recover(
            f.principal, uuid.UUID(ready["media_artifact_id"])
        )


async def test_authority_preflight_requires_both_capabilities_and_exact_live_scope(media):
    f = media
    params = {"agency_id": str(f.agency_id), "broadcast_id": str(f.broadcast_id)}
    response = await f.media_client.get("/mcp/whatsapp-media/authority", params=params)
    assert response.status_code == 200
    assert response.json() == {
        "authorized": True,
        "capabilities": ["mcp:upload", "mcp:communicate"],
        **params,
    }
    token, _ = await f.connect(["mcp:upload"])
    denied = await f.media_client.get(
        "/mcp/whatsapp-media/authority",
        params=params,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert denied.status_code == 403
    wrong = await f.media_client.get(
        "/mcp/whatsapp-media/authority",
        params={**params, "broadcast_id": str(uuid.uuid4())},
    )
    assert wrong.status_code == 403
    assert f.scanner.calls == 0 and not f.storage.objects
    f.provider.assert_not_awaited()
