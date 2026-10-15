"""Official SDK proxy and real TCP delivery of a canonical passport image ZIP."""

import uuid
import zipfile

import httpx2
from mcp import Client
from sqlalchemy import func, select
from test_backend_tcp import FixtureVault, fixture_lock
from test_backend_tcp import backend_tcp as backend_tcp

from gc_mcp_connector.artifacts import ArtifactClient
from gc_mcp_connector.auth import Authorization
from gc_mcp_connector.oauth import OAuthClient
from gc_mcp_connector.proxy import RemoteProxy


async def test_image_zip_inspect_generate_retry_verified_local_delivery_over_tcp(backend_tcp, tmp_path):
    from app.infrastructure.database.models import (
        AgencyModel,
        ClientGroupModel,
        PassportExportHistoryModel,
        PassportSubmissionModel,
    )
    from app.presentation.mcp.image_export_tools import register_image_export_tools
    from tests.integration.test_mcp_artifacts import Storage
    from tests.integration.test_mcp_image_exports import Images, png

    config, sessions, attempt, code, _actor, app = backend_tcp
    # This exact registration is invoked by install_mcp after qualification.
    if "prepare_image_export" not in app.state.mcp_operations:
        register_image_export_tools(app.state.mcp_server, app, app.state.settings)
    app.state.mcp_artifact_storage = storage = Storage()
    app.state.mcp_image_storage = images = Images()
    images.retain("original/front.png", "red")
    images.retain("original/back.png", "blue")
    originals = dict(images.objects)
    async with sessions() as session:
        agency = AgencyModel(id=uuid.uuid4(), name="TCP images", email="tcp-images@example.test")
        session.add(agency)
        await session.flush()
        group = ClientGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="TCP image trip", token=uuid.uuid4().hex)
        session.add(group)
        await session.flush()
        session.add(PassportSubmissionModel(id=uuid.uuid4(), agency_id=agency.id, group_id=group.id,
            client_name="Synthetic traveller", image_s3_key="original/front.png", passport_back_s3_key="original/back.png",
            status="staff_approved", confirmed_fields={"passport_number": "SYNTHETIC"}))
        await session.commit()
        request = {"agency_id": str(agency.id), "group_id": str(group.id)}
    async with httpx2.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as http:
        oauth = OAuthClient(config, http)
        await oauth.discover()
        authorization = Authorization(oauth, FixtureVault(), fixture_lock)
        await authorization.remember(await oauth.exchange(code, attempt))
        async with Client(RemoteProxy(config, authorization).server(), mode="legacy") as client:
            inspection = await client.call_tool("inspect_image_export", {"export": request})
            observed = inspection.structured_content
            assert not inspection.is_error and "error" not in observed, observed
            args = {"export": request, "expected_revision": observed["expected_revision"], "idempotency_key": uuid.uuid4().hex}
            generated = await client.call_tool("prepare_image_export", args)
            result = generated.structured_content
            assert not generated.is_error and result.get("status") == "succeeded", result
            retry = await client.call_tool("prepare_image_export", args)
            assert retry.structured_content["artifact"] == result["artifact"]
            async with sessions() as session:
                history = await session.scalar(select(PassportExportHistoryModel))
                assert history.status == "prepared"
            destination = tmp_path / "verified-images.zip"
            received = await ArtifactClient(config, authorization, http).download(result["artifact"]["artifact_id"], destination=destination)
            assert received.server_delivery_acknowledged
            with zipfile.ZipFile(destination) as archive:
                files = [name for name in archive.namelist() if not name.endswith("/")]
                assert len(files) == 2 and {archive.read(name) for name in files} == {png("red"), png("blue")}
            resumed = await client.call_tool("resume_image_export", {"operation_id": result["operation_id"]})
            assert resumed.structured_content["artifact"]["delivered_at"] is not None
    assert images.objects == originals and len(storage.objects) == 1
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(PassportExportHistoryModel)) == 1
        assert (await session.scalar(select(PassportExportHistoryModel))).status == "completed"
