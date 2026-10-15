"""Official SDK -> connector proxy -> real TCP -> canonical retained PDF draft."""

import uuid

import httpx2
from mcp import Client
from sqlalchemy import func, select
from test_backend_tcp import FixtureVault, fixture_lock
from test_backend_tcp import backend_tcp as backend_tcp

from gc_mcp_connector.artifacts import ArtifactClient
from gc_mcp_connector.auth import Authorization
from gc_mcp_connector.oauth import OAuthClient
from gc_mcp_connector.proxy import RemoteProxy


async def test_explicit_local_pdf_stage_then_inspect_ingest_retry_and_resume_over_tcp(backend_tcp, tmp_path):
    from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
    from app.infrastructure.database.models import (
        AgencyModel,
        ClientGroupModel,
        DistributedDocumentModel,
        DocumentDistributionBatchModel,
        PassportSubmissionModel,
    )
    from app.infrastructure.security.upload_security import UploadSecurityService
    from tests.integration.test_mcp_artifacts import Evidence, Scanner, Storage
    from tests.integration.test_mcp_pdf_ingestion import Documents, visa_pdf

    config, sessions, attempt, code, _actor, app = backend_tcp
    app.state.mcp_artifact_storage = storage = Storage()
    app.state.mcp_document_storage = documents = Documents()
    scanner = Scanner()
    app.state.mcp_artifact_security = UploadSecurityService(settings=app.state.settings,
        scanner=scanner, session_factory=Evidence, storage=storage)
    async with sessions() as session:
        agency = AgencyModel(id=uuid.uuid4(), name="TCP PDF", email="tcp-pdf@example.test")
        session.add(agency)
        await session.flush()
        group = ClientGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="TCP PDF trip", token=uuid.uuid4().hex)
        session.add(group)
        await session.flush()
        session.add(PassportSubmissionModel(id=uuid.uuid4(), agency_id=agency.id, group_id=group.id,
            client_name="ASHA MEHTA", image_s3_key="original/never-read", status="staff_approved",
            confirmed_fields={"given_name": "ASHA", "surname": "MEHTA", "passport_number": "P1234567"}))
        await session.commit()
        agency_id, group_id = agency.id, group.id
    path = tmp_path / "explicit-test-visa.pdf"
    path.write_bytes(visa_pdf())
    async with httpx2.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as http:
        oauth = OAuthClient(config, http)
        await oauth.discover()
        authorization = Authorization(oauth, FixtureVault(), fixture_lock)
        await authorization.remember(await oauth.exchange(code, attempt))
        transport = ArtifactClient(config, authorization, http)
        staged = await transport.upload_pdf(path, allowed_paths=frozenset({path}), agency_id=agency_id, group_id=group_id)
        assert scanner.calls == 1 and not documents.objects
        request = {"artifact_id": staged.artifact_id, "agency_id": str(agency_id),
                   "group_id": str(group_id), "document_type": "visa"}
        async with Client(RemoteProxy(config, authorization).server(), mode="legacy") as client:
            inspected = await client.call_tool("inspect_document_pdf_ingestion", {"upload": request})
            assert not inspected.is_error
            observed = inspected.structured_content
            assert "error" not in observed, observed
            assert observed["passenger_count"] == 1
            arguments = {"upload": request, "expected_revision": observed["expected_revision"],
                         "idempotency_key": uuid.uuid4().hex}
            ingested = await client.call_tool("ingest_document_pdf", arguments)
            assert not ingested.is_error
            result = ingested.structured_content
            assert result.get("status") == "succeeded", result
            assert result["accepted_file_count"] == 1 and result["batch_status"] == "draft"
            retry = await client.call_tool("ingest_document_pdf", arguments)
            assert retry.structured_content["operation_id"] == result["operation_id"]
            assert retry.structured_content["receipt"] == result["receipt"]
            resumed = await client.call_tool("resume_document_pdf_ingestion", {"operation_id": result["operation_id"]})
            assert resumed.structured_content["batch_id"] == result["batch_id"]
        assert len(storage.objects) == len(documents.objects) == 1 and scanner.calls == 2
        assert path.read_bytes() == visa_pdf()
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(DocumentDistributionBatchModel)) == 1
            assert await session.scalar(select(func.count()).select_from(DistributedDocumentModel)) == 1
            artifact = await session.scalar(select(MCPArtifactModel))
            assert artifact.ingestion_operation_id == uuid.UUID(result["operation_id"])
