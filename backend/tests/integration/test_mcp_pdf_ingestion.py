"""Real PDF classification/matching into retained drafts; synthetic private storage."""

from __future__ import annotations

import asyncio
import io
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import func, select

from app.application.mcp.artifacts import ArtifactError
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.application.mcp.pdf_ingestion import (
    MCPPDFIngestionService,
    PDFIngestRequest,
    pdf_ingestion_operation,
)
from app.infrastructure.database.mcp_artifact_models import MCPArtifactAccessModel, MCPArtifactModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AuditLogModel,
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    DocumentUploadChunkModel,
    PassportSubmissionModel,
)
from app.infrastructure.security.upload_validator import MalwareScanRejectedError
from app.presentation.mcp.pdf_ingestion_tools import ingestion_support
from tests.integration.test_mcp_artifacts import artifacts as artifacts
from tests.integration.test_mcp_artifacts import upload


def visa_pdf(passport="P1234567", name="ASHA MEHTA"):
    writer, output = PdfWriter(), io.BytesIO()
    page = writer.add_blank_page(width=600, height=800)
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        }
    )
    lines = [
        "SOCIALIST REPUBLIC OF VIETNAM",
        "VIETNAM ELECTRONIC VISA",
        "Issuing authority: Vietnam Immigration Department",
        "Visa number: EVN240001",
        f"Full name: {name}",
        f"Passport number: {passport}",
        "Valid from: 01 August 2026",
        "Valid until: 30 August 2026",
        "Number of entries: Multiple",
    ]
    content = DecodedStreamObject()
    content.set_data(
        (
            "BT /F1 12 Tf 40 750 Td 20 TL " + " ".join(f"({line}) Tj T*" for line in lines) + " ET"
        ).encode()
    )
    page[NameObject("/Contents")] = writer._add_object(content)
    writer.write(output)
    return output.getvalue()


class Documents:
    def __init__(self):
        self.objects = {}
        self.deleted = []
        self.fail_after_write = False
        self.after_write = None

    async def upload_file(self, content, key, content_type):
        assert key not in self.objects
        self.objects[key] = content
        if self.after_write:
            await self.after_write()
        if self.fail_after_write:
            raise OSError("Synthetic storage lost acknowledgement")
        return key

    async def delete_files(self, keys):
        self.deleted.extend(keys)
        for key in keys:
            self.objects.pop(key, None)


def service(f):
    return MCPPDFIngestionService(
        f.session,
        f.settings,
        ingestion_support(),
        artifacts=f.service,
        document_storage=f.documents,
    )


async def seed(f):
    f.documents = Documents()
    f.passport = PassportSubmissionModel(
        id=uuid.uuid4(),
        agency_id=f.agency.id,
        group_id=f.group.id,
        client_name="ASHA MEHTA",
        image_s3_key="original/passport-never-read",
        status="staff_approved",
        confirmed_fields={
            "given_name": "ASHA",
            "surname": "MEHTA",
            "passport_number": "P1234567",
        },
    )
    f.session.add(f.passport)
    await f.session.commit()
    return f


async def stage(f, data=None):
    response = await upload(f, data=visa_pdf() if data is None else data)
    assert response.status_code == 201, response.text
    metadata = response.json()
    return PDFIngestRequest(
        artifact_id=metadata["artifact_id"],
        agency_id=f.agency.id,
        group_id=f.group.id,
        document_type="visa",
    )


async def queue(f, request=None, key=None):
    request = request or await stage(f)
    observed = await service(f).inspect(f.principal, request)
    definition = pdf_ingestion_operation(f.settings, ingestion_support())
    payload = {
        "upload": request.model_dump(mode="json"),
        "expected_revision": observed["expected_revision"],
    }
    key = key or uuid.uuid4().hex
    receipt = await MCPOperationService(f.session, f.settings, [definition]).execute(
        access_token=f.token,
        operation_name=definition.policy.name,
        idempotency_key=key,
        payload=payload,
    )
    await f.session.commit()
    return receipt, request, key, payload


async def ingest(f, receipt, *, token=None, explicit_resume=False):
    result = await service(f).execute(
        access_token=token or f.token,
        operation_id=uuid.UUID(receipt["operation_id"]),
        explicit_resume=explicit_resume,
    )
    await f.session.commit()
    return result


async def count(f, model):
    return await f.session.scalar(select(func.count()).select_from(model))


async def test_real_pdf_is_rescanned_matched_and_retained_as_draft_without_saving_or_sending(
    artifacts,
):
    f = await seed(artifacts)
    receipt, request, _, _ = await queue(f)
    original = dict(f.storage.objects)
    assert f.scanner.calls == 1 and not f.documents.objects
    metadata = await f.client.get(f"/mcp/artifacts/{request.artifact_id}")
    assert metadata.json()["business_ingestion"] == "queued"
    result = await ingest(f, receipt)
    assert f.scanner.calls == 2
    assert [row.ingestion_flow for row in f.evidence.records] == [
        "mcp_group_document_pdf",
        "mcp_document_pdf_ingestion",
    ]
    assert result["batch_id"] == receipt["operation_id"] and result["batch_status"] == "draft"
    assert result["accepted_file_count"] == result["assignment_count"] == 1
    assert result["rejected_file_count"] == 0 and result["review_required"]
    assert result["background_processing"] is False
    document = await f.session.scalar(select(DistributedDocumentModel))
    assert document.passenger_id == f.passport.id and document.match_status == "matched"
    assert document.storage_key.startswith(
        f"document-distribution/{f.group.id}/{receipt['operation_id']}/"
    )
    assert f.documents.objects[document.storage_key] == visa_pdf()
    assert f.storage.objects == original and not f.documents.deleted
    assert (
        f.passport.status == "staff_approved"
        and f.passport.image_s3_key == "original/passport-never-read"
    )
    audit = await f.session.scalar(
        select(AuditLogModel).where(AuditLogModel.action == "document_distribution_uploaded")
    )
    assert (
        audit.metadata_json["source"] == "mcp_staged_pdf"
        and audit.metadata_json["manual_type_approved_files"] == []
    )
    metadata = await f.client.get(f"/mcp/artifacts/{request.artifact_id}")
    assert metadata.json()["business_ingestion"] == "ingested"


async def test_same_key_and_response_loss_recover_one_draft_distinct_key_cannot_reclaim(artifacts):
    f = await seed(artifacts)
    receipt, request, key, payload = await queue(f)
    first = await ingest(f, receipt)
    definition = pdf_ingestion_operation(f.settings, ingestion_support())
    replay = await MCPOperationService(f.session, f.settings, [definition]).execute(
        access_token=f.token,
        operation_name=definition.policy.name,
        idempotency_key=key,
        payload=payload,
    )
    await f.session.commit()
    assert replay == receipt and receipt["status"] == "queued"
    assert await ingest(f, receipt) == first
    with pytest.raises(MCPOperationError, match="artifact_already_claimed"):
        await queue(f, request)
    await f.session.rollback()
    assert await count(f, MCPOperationModel) == 1
    assert await count(f, DocumentDistributionBatchModel) == 1
    assert await count(f, DocumentUploadChunkModel) == 1
    assert await count(f, DistributedDocumentModel) == 1
    assert len(f.documents.objects) == 1 and f.scanner.calls == 2


async def test_new_connection_requires_explicit_resume_and_current_authority(artifacts):
    f = await seed(artifacts)
    receipt, request, _, _ = await queue(f)
    token, principal = await f.connect(["mcp:upload"])
    with pytest.raises(ArtifactError, match="explicitly"):
        await ingest(f, receipt, token=token)
    await f.session.rollback()
    result = await ingest(f, receipt, token=token, explicit_resume=True)
    assert result["accepted_file_count"] == 1
    assert await count(f, MCPArtifactAccessModel) == 2
    with pytest.raises(ArtifactError):
        await f.service.get(principal, request.artifact_id)
    await f.session.rollback()
    f.settings.mcp.enabled_capabilities = ["mcp:read"]
    from app.application.mcp.credentials import MCPAuthError

    with pytest.raises(MCPAuthError):
        await ingest(f, receipt, token=token, explicit_resume=True)


@pytest.mark.parametrize("failure", ["corrupt", "scan", "storage"])
async def test_failed_attempt_retains_queued_claim_and_original_then_resumes(artifacts, failure):
    f = await seed(artifacts)
    receipt, _, _, _ = await queue(f)
    original = dict(f.storage.objects)
    if failure == "corrupt":
        f.storage.corrupt = True
    elif failure == "scan":
        f.scanner.error = MalwareScanRejectedError
    else:
        f.documents.fail_after_write = True
    with pytest.raises((ArtifactError, MalwareScanRejectedError, OSError)):
        await ingest(f, receipt)
    await f.session.rollback()
    operation = await f.session.get(MCPOperationModel, uuid.UUID(receipt["operation_id"]))
    assert operation.status == "queued" and not f.documents.objects
    assert f.storage.objects == original
    assert await count(f, DocumentDistributionBatchModel) == 0
    f.storage.corrupt = f.documents.fail_after_write = False
    f.scanner.error = None
    assert (await ingest(f, receipt))["accepted_file_count"] == 1


async def test_change_after_storage_rolls_back_only_new_private_copy(artifacts):
    f = await seed(artifacts)
    receipt, _, _, _ = await queue(f)
    original = dict(f.storage.objects)

    async def correct_passenger():
        f.passport.confirmed_fields = {**f.passport.confirmed_fields, "surname": "CHANGED"}
        await f.session.commit()

    f.documents.after_write = correct_passenger
    with pytest.raises(MCPOperationError, match="ingestion_revision_changed"):
        await ingest(f, receipt)
    assert not f.documents.objects and len(f.documents.deleted) == 1
    assert f.storage.objects == original
    assert await count(f, DocumentDistributionBatchModel) == 0
    assert (
        await f.session.get(MCPOperationModel, uuid.UUID(receipt["operation_id"]))
    ).status == "queued"


async def test_unmatched_pdf_records_rejection_without_forced_assignment(artifacts):
    f = await seed(artifacts)
    request = await stage(f, visa_pdf("Z9999999", "UNKNOWN TRAVELLER"))
    receipt, _, _, _ = await queue(f, request)
    result = await ingest(f, receipt)
    assert result["accepted_file_count"] == result["assignment_count"] == 0
    assert result["rejected_file_count"] == 1 and result["rejected_documents"]
    assert result["batch_status"] == "draft" and not f.documents.objects
    assert await count(f, DistributedDocumentModel) == 0


async def test_expiry_blocks_queued_but_never_deletes_retained_result_or_recreates_missing_batch(
    artifacts,
):
    f = await seed(artifacts)
    receipt, _, _, _ = await queue(f)
    first = await ingest(f, receipt)
    row = await f.session.scalar(select(MCPArtifactModel))
    row.created_at = datetime.now(UTC) - timedelta(hours=2)
    row.expires_at = datetime.now(UTC) - timedelta(hours=1)
    await f.session.commit()
    assert await ingest(f, receipt) == first
    batch = await f.session.get(DocumentDistributionBatchModel, uuid.UUID(first["batch_id"]))
    # Simulate the existing manual workflow removing the retained result.
    from sqlalchemy import delete

    await f.session.execute(
        delete(DistributedDocumentModel).where(DistributedDocumentModel.batch_id == batch.id)
    )
    await f.session.delete(batch)
    await f.session.commit()
    with pytest.raises(ArtifactError, match="will not be recreated"):
        await ingest(f, receipt)
    await f.session.rollback()
    assert len(f.documents.objects) == 1 and f.scanner.calls == 2


async def test_db_only_claim_never_initializes_storage_or_parses(artifacts, monkeypatch):
    from app.application.mcp import artifacts as artifact_module
    from app.infrastructure.documents import distribution_ingestion

    f = await seed(artifacts)
    request = await stage(f)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("DB-only callback must not initialize storage or parse")

    monkeypatch.setattr(artifact_module, "MCPArtifactStorage", forbidden)
    monkeypatch.setattr(distribution_ingestion, "classify_documents_bounded", forbidden)
    receipt, _, _, _ = await queue(f, request)
    assert receipt["status"] == "queued" and not f.documents.objects
    assert f.scanner.calls == 1 and await count(f, DocumentDistributionBatchModel) == 0


async def test_expired_queued_source_never_starts_classification(artifacts):
    f = await seed(artifacts)
    receipt, _, _, _ = await queue(f)
    row = await f.session.scalar(select(MCPArtifactModel))
    row.created_at = datetime.now(UTC) - timedelta(hours=2)
    row.expires_at = datetime.now(UTC) - timedelta(hours=1)
    await f.session.commit()
    with pytest.raises(ArtifactError, match="expired"):
        await ingest(f, receipt)
    await f.session.rollback()
    assert f.scanner.calls == 1 and not f.documents.objects
    assert (
        await f.session.get(MCPOperationModel, uuid.UUID(receipt["operation_id"]))
    ).status == "queued"


async def test_cancellation_drains_storage_then_rolls_back_draft_and_owned_copy(artifacts):
    f = await seed(artifacts)
    receipt, _, _, _ = await queue(f)
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow_write():
        entered.set()
        await release.wait()

    f.documents.after_write = slow_write
    task = asyncio.create_task(ingest(f, receipt))
    try:
        await asyncio.wait_for(entered.wait(), 15)
        task.cancel()
        await asyncio.sleep(0.02)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
    assert not f.documents.objects and len(f.documents.deleted) == 1
    assert len(f.storage.objects) == 1
    assert await count(f, DocumentDistributionBatchModel) == 0
    assert (
        await f.session.get(MCPOperationModel, uuid.UUID(receipt["operation_id"]))
    ).status == "queued"


async def test_receipt_failure_rolls_back_canonical_flush_and_compensates_copy(artifacts):
    f = await seed(artifacts)
    receipt, _, _, _ = await queue(f)

    def fail_receipt(*_args):
        raise RuntimeError("Synthetic failure after canonical rows flushed")

    support = replace(ingestion_support(), receipt=fail_receipt)
    broken = MCPPDFIngestionService(
        f.session, f.settings, support, artifacts=f.service, document_storage=f.documents
    )
    with pytest.raises(RuntimeError, match="Synthetic failure"):
        await broken.execute(access_token=f.token, operation_id=uuid.UUID(receipt["operation_id"]))
    assert not f.documents.objects and len(f.documents.deleted) == 1
    assert await count(f, DocumentDistributionBatchModel) == 0
    assert (
        await f.session.get(MCPOperationModel, uuid.UUID(receipt["operation_id"]))
    ).status == "queued"
    assert (await ingest(f, receipt))["accepted_file_count"] == 1
