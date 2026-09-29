"""Document metadata and job tools at the actual authenticated SDK HTTP boundary."""

from __future__ import annotations

import uuid

import pytest

from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    PassportProcessingJobModel,
    PassportSubmissionModel,
)
from app.presentation.mcp.document_read_tools import register_document_read_tools
from tests.integration.test_mcp_authorization import call_mcp, connect
from tests.integration.test_mcp_authorization import mcp_fixture as mcp_fixture


@pytest.mark.asyncio
async def test_all_document_tools_http_and_schema_rejection(mcp_fixture):
    client, session, settings, _, _, _ = mcp_fixture
    app = client._transport.app
    if "list_group_documents" not in [tool.name for tool in await app.state.mcp_server.list_tools()]:
        register_document_read_tools(app.state.mcp_server, app, settings)
    agency = AgencyModel(id=uuid.uuid4(), name="Fixture", email="fixture@example.test")
    session.add(agency)
    await session.flush()
    group = ClientGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Documents", token="SECRET_UPLOAD_TOKEN")
    session.add(group)
    await session.flush()
    upload = DocumentDistributionBatchModel(id=uuid.uuid4(), agency_id=agency.id, group_id=group.id, document_type="visa", status="processing")
    passport = PassportSubmissionModel(id=uuid.uuid4(), agency_id=agency.id, group_id=group.id, client_name="Person", image_s3_key="SECRET_SOURCE")
    session.add_all([upload, passport])
    await session.flush()
    session.add(DistributedDocumentModel(id=uuid.uuid4(), batch_id=upload.id, agency_id=agency.id,
        group_id=group.id, document_type="visa", original_filename="fixture.pdf", storage_key="SECRET_DOCUMENT",
        extracted_passport_number="SECRET_NUMBER"))
    session.add(PassportProcessingJobModel(id=uuid.uuid4(), submission_id=passport.id,
                                         status="failed", error_message="SECRET_ERROR"))
    await session.flush()
    _, tokens = await connect(mcp_fixture)
    for name in ("list_group_documents", "list_group_document_batches", "list_group_processing_jobs"):
        response = await call_mcp(client, tokens["access_token"], name=name, arguments={"group_id": str(group.id)})
        assert response.status_code == 200 and "SECRET" not in response.text
        result = response.json()["result"]["structuredContent"]
        assert len(result["items"]) == 1 and result["environment"] == settings.app_env
        assert result["observed_at"] and result["audit_id"] and result["completeness"] == "complete"
    invalid = await call_mcp(client, tokens["access_token"], name="list_group_documents",
        arguments={"group_id": str(group.id), "document_type": "../../files"})
    assert invalid.json()["result"].get("isError") is True
    _, denied_token = await connect(mcp_fixture, scopes=["mcp:diagnose"])
    denied = await call_mcp(client, denied_token["access_token"], name="list_group_processing_jobs",
                           arguments={"group_id": str(group.id)})
    assert denied.json()["result"]["structuredContent"]["error"] == "access_denied"
