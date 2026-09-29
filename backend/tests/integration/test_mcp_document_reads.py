"""Document/job reads preserve identity, roster differences and retained evidence."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.document_reads import MCPDocumentReadService
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    PassportProcessingJobModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    UserModel,
)


@pytest.fixture
async def document_reads(db_session):
    actor = UserModel(id=uuid.uuid4(), email="documents@example.test", hashed_password="fixture",
                      full_name="Reader", role="super_admin", is_active=True)
    agencies = [AgencyModel(id=uuid.uuid4(), name=f"Agency {index}", email=f"agency{index}@example.test") for index in range(2)]
    db_session.add_all([actor, *agencies])
    await db_session.flush()
    group = ClientGroupModel(id=uuid.uuid4(), agency_id=agencies[0].id, name="Documents",
                              token="SECRET_UPLOAD_TOKEN", import_only=True)
    db_session.add(group)
    await db_session.flush()
    return db_session, actor, agencies, group, MCPDocumentReadService(db_session, cursor_secret="test-document-cursor")


def batch(group, **fields):
    return DocumentDistributionBatchModel(id=uuid.uuid4(), agency_id=group.agency_id, group_id=group.id,
        document_type="visa", created_at=datetime.now(UTC) - timedelta(minutes=2), **fields)


def document(group, upload, **fields):
    return DistributedDocumentModel(id=uuid.uuid4(), agency_id=group.agency_id, group_id=group.id,
        batch_id=upload.id, document_type="visa", original_filename="fixture.pdf", storage_key="SECRET_STORAGE_KEY",
        created_at=datetime.now(UTC) - timedelta(minutes=1), extracted_passport_number="SECRET_PASSPORT",
        extracted_name="Sensitive Name", extracted_reference="SECRET_REFERENCE", **fields)


@pytest.mark.asyncio
async def test_empty_import_only_group_missing_agency_and_retained_opt_in(document_reads):
    session, actor, agencies, group, service = document_reads
    for method in (service.list_documents, service.list_batches, service.list_processing_jobs):
        result = await method(user_id=actor.id, group_id=group.id)
        assert result["items"] == [] and result["completeness"] == "complete"
        assert "SECRET" not in json.dumps(result)
        with pytest.raises(ValueError, match="scope"):
            await method(user_id=actor.id, group_id=group.id, agency_id=agencies[1].id)
    group.deleted_at, group.status = datetime.now(UTC), "deleted"
    await session.flush()
    with pytest.raises(ValueError, match="scope"):
        await service.list_documents(user_id=actor.id, group_id=group.id)
    assert (await service.list_documents(user_id=actor.id, group_id=group.id, include_deleted=True))["items"] == []


@pytest.mark.asyncio
async def test_document_privacy_provenance_and_operational_roster_are_separate(document_reads):
    session, actor, _, group, service = document_reads
    passports = [PassportSubmissionModel(id=uuid.uuid4(), group_id=group.id, agency_id=group.agency_id,
        client_name=f"Person {index}", image_s3_key=f"private/{index}", status=status) for index, status in enumerate(("confirmed", "uploaded", "staff_approved"))]
    upload = batch(group)
    session.add_all([upload, *passports])
    await session.flush()
    session.add(PassportRosterResolutionModel(id=uuid.uuid4(), agency_id=group.agency_id,
        client_group_id=group.id, submission_id=passports[2].id, resolution_type="rejected", status="active",
        excluded_submission_ids=[], resolved_by_user_id=actor.id))
    docs = [document(group, upload, passenger_id=person.id, match_status="matched",
             match_reason="Document type manually approved; SECRET_MATCH_TEXT") for person in passports]
    docs.append(document(group, upload))
    session.add_all(docs)
    await session.flush()
    result = await service.list_documents(user_id=actor.id, group_id=group.id)
    assert len(result["items"]) == 4
    assert sum(row["assigned_to_operational_passenger"] for row in result["items"]) == 1
    assert sum(row["manual_type_approved"] for row in result["items"]) == 3
    assert "SECRET" not in json.dumps(result) and "Sensitive Name" not in json.dumps(result)
    assert not any("url" in row or "storage_key" in row for row in result["items"])
    detailed = await service.list_documents(user_id=actor.id, group_id=group.id, include_extracted_identifiers=True)
    assert detailed["items"][0]["extracted_passport_number"] == "SECRET_PASSPORT"
    audit = (await session.execute(select(AuditLogModel).where(AuditLogModel.action == "sensitive_read.authorized"))).scalar_one()
    assert audit.metadata_json["authorized_result_count"] == 4
    assert "SECRET" not in json.dumps(audit.metadata_json)


@pytest.mark.asyncio
async def test_batches_and_jobs_keep_incomplete_and_old_revision_evidence(document_reads):
    session, actor, _, group, service = document_reads
    uploads = [batch(group, status=status, uploaded_count=4, rejected_count=1, matched_count=2) for status in ("processing", "draft", "saved")]
    passport = PassportSubmissionModel(id=uuid.uuid4(), agency_id=group.agency_id, group_id=group.id,
        client_name="Person", image_s3_key="private/image", extraction_revision=2)
    session.add_all([passport, *uploads])
    await session.flush()
    jobs = [PassportProcessingJobModel(id=uuid.uuid4(), submission_id=passport.id, extraction_revision=revision,
             status=status, current_stage="SECRET_PROMPT_INJECTION", error_message="SECRET_RAW_ERROR", progress=0.4)
            for revision, status in ((1, "succeeded"), (2, "failed"))]
    session.add_all(jobs)
    await session.flush()
    listed = await service.list_batches(user_id=actor.id, group_id=group.id)
    assert {row["status"] for row in listed["items"]} == {"processing", "draft", "saved"}
    result = await service.list_processing_jobs(user_id=actor.id, group_id=group.id)
    assert len(result["items"]) == 2 and sum(row["is_current_revision"] for row in result["items"]) == 1
    assert all(row["current_stage"] == "unknown" and row["has_error"] for row in result["items"])
    assert "SECRET" not in json.dumps(result)
    current = await service.list_processing_jobs(user_id=actor.id, group_id=group.id, status="failed", submission_id=passport.id)
    assert len(current["items"]) == 1 and current["items"][0]["is_current_revision"] is True


@pytest.mark.asyncio
async def test_document_keysets_and_filter_contact_and_tenant_binding(document_reads):
    session, actor, agencies, group, service = document_reads
    upload = batch(group)
    session.add(upload)
    await session.flush()
    docs = [document(group, upload) for _ in range(107)]
    stamp = datetime.now(UTC) - timedelta(minutes=2)
    for index, row in enumerate(docs):
        row.created_at = stamp
        row.id = uuid.UUID(f"cccccccc-cccc-cccc-cccc-{index + 1:012x}")
    inconsistent = document(group, upload)
    inconsistent.agency_id = agencies[1].id
    session.add_all([*docs, inconsistent])
    await session.flush()
    page = await service.list_documents(user_id=actor.id, group_id=group.id, page_size=13)
    cursor = page["next_cursor"]
    seen = [row["id"] for row in page["items"]]
    while page["has_more"]:
        page = await service.list_documents(user_id=actor.id, group_id=group.id, page_size=13, cursor=page["next_cursor"])
        seen.extend(row["id"] for row in page["items"])
    assert len(seen) == len(set(seen)) == 107 and str(inconsistent.id) not in seen
    for changed in ({"include_extracted_identifiers": True}, {"document_type": "visa"}, {"include_deleted": True}):
        with pytest.raises(ValueError, match="cursor"):
            await service.list_documents(user_id=actor.id, group_id=group.id, page_size=13, cursor=cursor, **changed)


@pytest.mark.asyncio
async def test_document_bounds_types_and_live_role(document_reads):
    session, actor, _, group, service = document_reads
    with pytest.raises(ValueError, match="document type"):
        await service.list_documents(user_id=actor.id, group_id=group.id, document_type="../../secrets")
    with pytest.raises(ValueError, match="status"):
        await service.list_processing_jobs(user_id=actor.id, group_id=group.id, status="arbitrary SQL")
    for value in (0, 101, True):
        with pytest.raises(ValueError, match="Page size"):
            await service.list_documents(user_id=actor.id, group_id=group.id, page_size=value)
    actor.role = "agency_admin"
    await session.flush()
    with pytest.raises(MCPAuthError):
        await service.list_documents(user_id=actor.id, group_id=group.id)
    actor.role, actor.is_active = "super_admin", False
    await session.flush()
    with pytest.raises(MCPAuthError):
        await service.list_processing_jobs(user_id=actor.id, group_id=group.id)
