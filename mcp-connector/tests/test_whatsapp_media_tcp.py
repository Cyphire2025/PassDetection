"""Selected image tools through official SDK and actual TCP, with provider fixture only."""

import uuid
from unittest.mock import AsyncMock

import httpx2
import pytest
from mcp import Client
from sqlalchemy import func, select
from test_backend_tcp import FixtureVault, fixture_lock
from test_backend_tcp import backend_tcp as backend_tcp

from gc_mcp_connector.auth import Authorization
from gc_mcp_connector.file_tools import LocalFileTools
from gc_mcp_connector.oauth import OAuthClient
from gc_mcp_connector.proxy import RemoteProxy


@pytest.mark.parametrize("status", ["ready", "unknown"])
async def test_selected_header_upload_replay_inspection_and_recovery_never_send(
    backend_tcp, tmp_path, monkeypatch, status
):
    from app.infrastructure.database.mcp_models import MCPGrantModel
    from app.infrastructure.database.mcp_whatsapp_media_models import MCPWhatsAppHeaderMediaModel
    from app.infrastructure.database.models import (
        AgencyModel,
        WhatsAppBroadcastGroupModel,
        WhatsAppMessageLogModel,
    )
    from app.infrastructure.security.upload_security import UploadSecurityService
    from app.infrastructure.whatsapp.cloud_api_provider import WhatsAppCloudApiError
    from tests.integration.test_mcp_artifacts import Evidence, Scanner, Storage
    from tests.integration.test_mcp_whatsapp_media import picture

    config, sessions, attempt, code, actor, app = backend_tcp
    app.state.settings.whatsapp_access_token = "synthetic-provider-token"
    app.state.settings.whatsapp_phone_number_id = "synthetic-provider-sender"
    app.state.mcp_whatsapp_media_storage = storage = Storage()
    scanner = Scanner()
    app.state.mcp_whatsapp_media_security = UploadSecurityService(
        settings=app.state.settings, scanner=scanner, session_factory=Evidence, storage=storage
    )
    provider = AsyncMock(return_value="synthetic-provider-receipt-never-exposed")
    if status == "unknown":
        provider.side_effect = WhatsAppCloudApiError(
            "fixture uncertain response", code="WHATSAPP_MEDIA_UPLOAD_INTERRUPTED"
        )
    monkeypatch.setattr(
        "app.application.mcp.whatsapp_media_uploads.upload_whatsapp_image", provider
    )
    async with sessions() as session:
        grant = await session.scalar(select(MCPGrantModel).where(MCPGrantModel.user_id == actor))
        grant.capabilities = [*grant.capabilities, "mcp:communicate"]
        agency = AgencyModel(id=uuid.uuid4(), name="Header TCP", email="header-tcp@example.test")
        session.add(agency)
        await session.flush()
        broadcast = WhatsAppBroadcastGroupModel(
            id=uuid.uuid4(),
            agency_id=agency.id,
            name="Synthetic header broadcast",
            created_by_user_id=actor,
        )
        session.add(broadcast)
        await session.commit()
        agency_id, broadcast_id = agency.id, broadcast.id
    source = tmp_path / "explicit-header.png"
    source.write_bytes(picture())
    original = source.read_bytes()
    async with httpx2.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as http:
        oauth = OAuthClient(config, http)
        await oauth.discover()
        authorization = Authorization(oauth, FixtureVault(), fixture_lock)
        await authorization.remember(await oauth.exchange(code, attempt))
        files = LocalFileTools(config, authorization, selected_paths=[source])
        async with Client(
            RemoteProxy(config, authorization, file_tools=files).server(), mode="legacy"
        ) as client:
            arguments = {
                "selected_file_id": next(iter(files.paths)),
                "agency_id": str(agency_id),
                "broadcast_id": str(broadcast_id),
                "idempotency_key": uuid.uuid4().hex,
            }
            uploaded = await client.call_tool("local_upload_whatsapp_header_image", arguments)
            assert not uploaded.is_error, uploaded
            result = uploaded.structured_content
            assert result["status"] == status and result["ready_for_message_plan"] == (
                status == "ready"
            )
            assert result["messages_queued"] == 0
            assert "provider_media_id" not in result and "storage_key" not in result
            retried = await client.call_tool("local_upload_whatsapp_header_image", arguments)
            assert retried.structured_content == result
            scope = {"agency_id": str(agency_id), "broadcast_id": str(broadcast_id)}
            observed = await client.call_tool(
                "local_inspect_whatsapp_header_image",
                {**scope, "media_handle": result["media_handle"]},
            )
            assert not observed.is_error and observed.structured_content["status"] == status
            recovered = await client.call_tool(
                "local_recover_whatsapp_header_image",
                {**scope, "media_artifact_id": result["media_artifact_id"]},
            )
            assert recovered.is_error == (status != "ready")
    assert provider.await_count == scanner.calls == 1 and source.read_bytes() == original
    assert len(storage.objects) == 2
    async with sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(MCPWhatsAppHeaderMediaModel)) == 1
        )
        assert await session.scalar(select(func.count()).select_from(WhatsAppMessageLogModel)) == 0
