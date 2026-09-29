"""Official SDK proxy, canonical tracking workbook and verified TCP delivery."""

import uuid
from types import SimpleNamespace

import httpx2
from mcp import Client
from sqlalchemy import func, select
from test_backend_tcp import FixtureVault, fixture_lock
from test_backend_tcp import backend_tcp as backend_tcp

from gc_mcp_connector.artifacts import ArtifactClient
from gc_mcp_connector.auth import Authorization
from gc_mcp_connector.oauth import OAuthClient
from gc_mcp_connector.proxy import RemoteProxy


async def test_tracking_inspect_generate_retry_verified_download_over_tcp(backend_tcp, tmp_path):
    from app.infrastructure.database.models import (
        AgencyModel,
        ClientGroupModel,
        PassportExportHistoryModel,
        WhatsAppMessageLogModel,
    )
    from app.presentation.mcp.tracking_export_tools import register_tracking_export_tools
    from tests.integration.test_mcp_artifacts import Storage
    from tests.integration.test_mcp_exports import values
    from tests.integration.test_mcp_tracking_exports import seed

    config, sessions, attempt, code, _actor, app = backend_tcp
    if "prepare_tracking_export" not in app.state.mcp_operations:
        register_tracking_export_tools(app.state.mcp_server, app, app.state.settings)
    app.state.mcp_artifact_storage = storage = Storage()
    async with sessions() as session:
        agency = AgencyModel(
            id=uuid.uuid4(), name="TCP tracking", email="tcp-tracking@example.test"
        )
        session.add(agency)
        await session.flush()
        group = ClientGroupModel(
            id=uuid.uuid4(), agency_id=agency.id, name="TCP trip", token=uuid.uuid4().hex
        )
        session.add(group)
        await session.flush()
        f = await seed(SimpleNamespace(session=session, agency=agency, group=group))
        request = {
            "agency_id": str(agency.id),
            "group_id": str(group.id),
            "status": "not_submitted",
            "broadcast_id": str(f.broadcast.id),
        }
    async with httpx2.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as http:
        oauth = OAuthClient(config, http)
        await oauth.discover()
        authorization = Authorization(oauth, FixtureVault(), fixture_lock)
        await authorization.remember(await oauth.exchange(code, attempt))
        async with Client(RemoteProxy(config, authorization).server(), mode="legacy") as client:
            inspection = await client.call_tool("inspect_tracking_export", {"export": request})
            observed = inspection.structured_content
            assert not inspection.is_error and "error" not in observed, observed
            assert observed["history_checkpoint"] is False
            args = {
                "export": request,
                "expected_revision": observed["expected_revision"],
                "idempotency_key": uuid.uuid4().hex,
            }
            generated = await client.call_tool("prepare_tracking_export", args)
            result = generated.structured_content
            assert not generated.is_error and result.get("status") == "succeeded", result
            retry = await client.call_tool("prepare_tracking_export", args)
            assert retry.structured_content["artifact"] == result["artifact"]
            destination = tmp_path / "verified-tracking.xlsx"
            received = await ArtifactClient(config, authorization, http).download(
                result["artifact"]["artifact_id"], destination=destination
            )
            assert received.server_delivery_acknowledged
            assert "SYNTHETIC PERSON 2" in str(values(destination.read_bytes()))
            assert "TEST1" not in str(values(destination.read_bytes()))
            resumed = await client.call_tool(
                "resume_tracking_export", {"operation_id": result["operation_id"]}
            )
            assert resumed.structured_content["artifact"]["delivered_at"] is not None
    assert len(storage.objects) == 1
    async with sessions() as session:
        for model in (PassportExportHistoryModel, WhatsAppMessageLogModel):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
