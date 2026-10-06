"""Actual PostgreSQL races across independent connections for retained PDF drafts."""

import asyncio
import hashlib
import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.application.mcp.artifacts import MCPArtifactService
from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.application.mcp.pdf_ingestion import (
    MCPPDFIngestionService,
    PDFIngestRequest,
    pdf_ingestion_operation,
)
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    PassportSubmissionModel,
)
from app.infrastructure.security.upload_security import UploadSecurityService
from app.presentation.mcp.pdf_ingestion_tools import ingestion_support
from tests.integration.test_mcp_artifacts import Evidence, Scanner, Storage, chunks
from tests.integration.test_mcp_operations import seed_identity
from tests.integration.test_mcp_pdf_ingestion import Documents, visa_pdf
from tests.service_integration.test_mcp_concurrency_postgresql import mcp_sessions as mcp_sessions

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"
    ),
]


@pytest.fixture
async def queued_pdf(mcp_sessions):
    sessions, settings = mcp_sessions
    storage, documents, scanner = Storage(), Documents(), Scanner()
    security = UploadSecurityService(
        settings=settings, scanner=scanner, session_factory=Evidence, storage=storage
    )
    async with sessions() as session:
        (await session.get(MCPControlModel, 1)).enabled = True
        user, grants, tokens = await seed_identity(
            session, settings, enable_write_policy=True, email=f"pdf-{uuid.uuid4()}@example.test"
        )
        for grant in grants:
            grant.capabilities = ["mcp:upload"]
        agency = AgencyModel(
            id=uuid.uuid4(), name="Synthetic PDF agency", email=f"{uuid.uuid4()}@example.test"
        )
        session.add(agency)
        await session.flush()
        group = ClientGroupModel(
            id=uuid.uuid4(), agency_id=agency.id, name="Synthetic PDF trip", token=uuid.uuid4().hex
        )
        session.add(group)
        await session.flush()
        passport = PassportSubmissionModel(
            id=uuid.uuid4(),
            agency_id=agency.id,
            group_id=group.id,
            client_name="ASHA MEHTA",
            image_s3_key="original/never-read",
            status="staff_approved",
            confirmed_fields={
                "given_name": "ASHA",
                "surname": "MEHTA",
                "passport_number": "P1234567",
            },
        )
        session.add(passport)
        await session.commit()
        principal = await MCPAuthorizationService(session, settings).verify_access(tokens[0])
        await session.commit()
        artifacts = MCPArtifactService(session, settings, storage=storage, security=security)
        data = visa_pdf()
        metadata = await artifacts.stage_pdf(
            principal,
            agency_id=agency.id,
            group_id=group.id,
            filename="synthetic-visa.pdf",
            body=chunks(data),
            expected_size=len(data),
            expected_sha256=hashlib.sha256(data).hexdigest(),
        )
        await session.commit()
        request = PDFIngestRequest(
            artifact_id=metadata["artifact_id"],
            agency_id=agency.id,
            group_id=group.id,
            document_type="visa",
        )
        support = ingestion_support()
        service = MCPPDFIngestionService(
            session, settings, support, artifacts=artifacts, document_storage=documents
        )
        observed = await service.inspect(principal, request)
        definition = pdf_ingestion_operation(settings, support)
        receipt = await MCPOperationService(session, settings, [definition]).execute(
            access_token=tokens[0],
            operation_name=definition.policy.name,
            idempotency_key=uuid.uuid4().hex,
            payload={
                "upload": request.model_dump(mode="json"),
                "expected_revision": observed["expected_revision"],
            },
        )
        await session.commit()
        return (
            sessions,
            settings,
            storage,
            documents,
            security,
            tokens,
            grants[0].id,
            passport.id,
            uuid.UUID(receipt["operation_id"]),
        )


async def ingest(f, *, connection=0):
    sessions, settings, storage, documents, security, tokens, _, _, operation_id = f
    async with sessions() as session:
        result = await MCPPDFIngestionService(
            session,
            settings,
            ingestion_support(),
            artifacts=MCPArtifactService(session, settings, storage=storage, security=security),
            document_storage=documents,
        ).execute(
            access_token=tokens[connection],
            operation_id=operation_id,
            explicit_resume=connection > 0,
        )
        await session.commit()
        return result


async def test_two_connections_converge_on_one_draft_and_compensate_loser_copy(queued_pdf):
    f = queued_pdf
    arrived, first_copied, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    writes = 0

    async def both_copied():
        nonlocal writes
        writes += 1
        first_copied.set()
        if writes == 2:
            arrived.set()
        await release.wait()

    f[3].after_write = both_copied
    first = asyncio.create_task(ingest(f))
    # Let the bounded real parser finish before admitting a competing attempt.
    await asyncio.wait_for(first_copied.wait(), 15)
    second = asyncio.create_task(ingest(f, connection=1))
    try:
        await asyncio.wait_for(arrived.wait(), 15)
        release.set()
        results = await asyncio.wait_for(asyncio.gather(first, second), 15)
    finally:
        release.set()
        settled = await asyncio.gather(first, second, return_exceptions=True)
        assert all(isinstance(item, dict) for item in settled), settled
    assert results[0] == results[1]
    assert len(f[3].objects) == len(f[3].deleted) == 1
    async with f[0]() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(DocumentDistributionBatchModel)
                .where(DocumentDistributionBatchModel.id == f[-1])
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(DistributedDocumentModel)
                .where(DistributedDocumentModel.batch_id == f[-1])
            )
            == 1
        )


@pytest.mark.parametrize("change", ["revoke", "passport"])
async def test_authority_or_roster_change_during_private_copy_prevents_persistence(
    queued_pdf, change
):
    f = queued_pdf

    async def intervene():
        async with f[0]() as session:
            if change == "revoke":
                row = await session.get(MCPGrantModel, f[6])
                row.revoked_at = datetime.now(UTC)
            else:
                row = await session.get(PassportSubmissionModel, f[7])
                row.confirmed_fields = {**row.confirmed_fields, "surname": "CORRECTED"}
            await session.commit()

    f[3].after_write = intervene
    with pytest.raises((MCPAuthError, MCPOperationError)):
        await ingest(f)
    assert not f[3].objects and len(f[3].deleted) == 1 and len(f[2].objects) == 1
    async with f[0]() as session:
        assert await session.get(DocumentDistributionBatchModel, f[-1]) is None
        assert (await session.get(MCPOperationModel, f[-1])).status == "queued"


async def test_original_grant_revoked_queue_requires_explicit_new_grant_resume(queued_pdf):
    f = queued_pdf
    async with f[0]() as session:
        grant = await session.get(MCPGrantModel, f[6])
        grant.revoked_at = datetime.now(UTC)
        await session.commit()
    with pytest.raises(MCPAuthError):
        await ingest(f)
    result = await ingest(f, connection=1)
    assert result["status"] == "succeeded" and result["accepted_file_count"] == 1
