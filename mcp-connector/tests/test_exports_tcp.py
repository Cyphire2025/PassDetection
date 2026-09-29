"""Actual SDK proxy and loopback HTTP generation/delivery, with private-storage double."""

import hashlib
import uuid

import httpx2
from mcp import Client
from openpyxl import load_workbook
from sqlalchemy import func, select
from test_backend_tcp import FixtureVault, fixture_lock
from test_backend_tcp import backend_tcp as backend_tcp

from gc_mcp_connector.artifacts import ArtifactClient
from gc_mcp_connector.auth import Authorization
from gc_mcp_connector.oauth import OAuthClient
from gc_mcp_connector.proxy import RemoteProxy


async def test_inspect_generate_retry_and_verified_local_delivery_over_sdk_tcp(
    backend_tcp, tmp_path
):
    from app.core.mcp_export_admission import export_slot
    from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
    from app.infrastructure.database.mcp_operation_models import MCPOperationModel
    from app.infrastructure.database.models import (
        AgencyModel,
        AuditLogModel,
        ClientGroupModel,
        PassportExportHistoryModel,
        PassportSubmissionModel,
    )
    from app.infrastructure.storage.minio_repository import ObjectIntegrityMetadata

    config, sessions, attempt, code, _actor, app = backend_tcp

    class Storage:
        def __init__(self):
            self.objects = {}

        async def put_transfer(self, source, *, key, size, sha256, media_type):
            assert key not in self.objects
            source.seek(0)
            data = source.read()
            assert len(data) == size and hashlib.sha256(data).hexdigest() == sha256
            self.objects[key] = (data, sha256, media_type)

        async def stat_file(self, key):
            data, checksum, media = self.objects[key]
            return ObjectIntegrityMetadata(len(data), checksum, media)

        async def stream_file(self, key, *, start, expected_bytes, chunk_size):
            data = self.objects[key][0]
            for offset in range(start, len(data), chunk_size):
                yield data[offset : offset + chunk_size]

    app.state.mcp_artifact_storage = storage = Storage()
    async with sessions() as session:
        agency = AgencyModel(id=uuid.uuid4(), name="TCP export", email="tcp-export@example.test")
        session.add(agency)
        await session.flush()
        group = ClientGroupModel(
            id=uuid.uuid4(), agency_id=agency.id, name="TCP trip", token=uuid.uuid4().hex
        )
        session.add(group)
        await session.flush()
        session.add(
            PassportSubmissionModel(
                id=uuid.uuid4(),
                agency_id=agency.id,
                group_id=group.id,
                client_name="Synthetic traveller",
                image_s3_key="fixture/source/never-read",
                status="staff_approved",
                confirmed_fields={"passport_number": "TCP-SYNTHETIC"},
            )
        )
        await session.commit()
        request = {"agency_id": str(agency.id), "group_ids": [str(group.id)]}

    async with httpx2.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as http:
        oauth = OAuthClient(config, http)
        await oauth.discover()
        authorization = Authorization(oauth, FixtureVault(), fixture_lock)
        await authorization.remember(await oauth.exchange(code, attempt))
        async with Client(RemoteProxy(config, authorization).server(), mode="legacy") as client:
            with export_slot():
                busy = (
                    await client.call_tool("inspect_excel_export", {"export": request})
                ).structured_content
            assert busy["error"] == "export_busy" and busy["completeness"] == "unavailable"
            async with sessions() as session:
                audit = await session.get(AuditLogModel, uuid.UUID(busy["audit_id"]))
                assert audit.result == "blocked"
                assert audit.action == "mcp.tool.inspect_excel_export"
            assert "execute.lock" not in str(busy) and "passdetection-mcp-exports" not in str(busy)
            inspected = await client.call_tool("inspect_excel_export", {"export": request})
            assert not inspected.is_error
            observed = inspected.structured_content
            assert "error" not in observed, observed
            assert observed["passenger_count"] == 1
            arguments = {
                "export": request,
                "expected_revision": observed["expected_revision"],
                "idempotency_key": uuid.uuid4().hex,
            }
            with export_slot():
                busy_prepare = (
                    await client.call_tool("prepare_excel_export", arguments)
                ).structured_content
            assert busy_prepare["error"] == "export_busy" and "receipt" not in busy_prepare
            async with sessions() as session:
                audit = await session.get(AuditLogModel, uuid.UUID(busy_prepare["audit_id"]))
                assert audit.result == "blocked" and audit.action == "mcp.tool.prepare_excel_export"
                assert (
                    await session.scalar(select(func.count()).select_from(MCPOperationModel)) == 0
                )
            prepared = await client.call_tool("prepare_excel_export", arguments)
            assert not prepared.is_error
            result = prepared.structured_content
            assert result.get("status") == "succeeded", result
            retry = await client.call_tool("prepare_excel_export", arguments)
            assert retry.structured_content["operation_id"] == result["operation_id"]
            assert retry.structured_content["artifact"] == result["artifact"]
            assert len(storage.objects) == 1
            with export_slot():
                busy_resume = (
                    await client.call_tool(
                        "resume_excel_export", {"operation_id": result["operation_id"]}
                    )
                ).structured_content
            assert busy_resume["error"] == "export_busy"
            assert busy_resume["operation_id"] == result["operation_id"]
            async with sessions() as session:
                history = await session.scalar(select(PassportExportHistoryModel))
                assert history.status == "prepared"
            destination = tmp_path / "verified-export.xlsx"
            delivered = await ArtifactClient(config, authorization, http).download(
                result["artifact"]["artifact_id"],
                destination=destination,
            )
            assert delivered.server_delivery_acknowledged
            workbook = load_workbook(destination, read_only=True)
            assert "TCP-SYNTHETIC" in str([list(sheet.values) for sheet in workbook])
            resumed = await client.call_tool(
                "resume_excel_export", {"operation_id": result["operation_id"]}
            )
            assert resumed.structured_content["artifact"]["delivered_at"] is not None
            async with sessions() as session:
                history = await session.scalar(select(PassportExportHistoryModel))
                assert history.status == "completed"
                assert await session.scalar(select(func.count()).select_from(MCPArtifactModel)) == 1
