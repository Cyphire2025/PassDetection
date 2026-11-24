"""Actual ORM upload receipts and staged-object ownership across phase boundaries."""

import asyncio
import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    DocumentRenameBatchModel,
    DocumentRenameItemModel,
    DocumentUploadChunkModel,
    UserModel,
)
from app.infrastructure.documents.document_matcher import ClassifiedDocument
from app.presentation.api.v1.document_chunk_uploads import (
    document_chunk_fingerprint,
    new_document_chunk_receipt,
    resolve_document_chunk_metadata,
)
from app.presentation.api.v1.document_uploads import BoundedDocumentUpload
from app.presentation.api.v1.routes import document_rename, document_rename_chunk_staging


@pytest.fixture
async def rename_upload(db_session, monkeypatch):
    agency = AgencyModel(id=uuid.uuid4(), name="Synthetic agency", email="agency@example.test")
    actor = UserModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        role="agency_admin",
        is_active=True,
        email="rename@example.test",
        full_name="Synthetic actor",
        hashed_password="test-only",
    )
    db_session.add(agency)
    await db_session.flush()
    db_session.add(actor)
    await db_session.commit()
    user = SimpleNamespace(
        id=actor.id, agency_id=agency.id, email=actor.email, role=UserRole.AGENCY_ADMIN
    )
    uploads = [BoundedDocumentUpload("visa.pdf", b"%PDF synthetic visa", "application/pdf")]
    objects, deleted = {}, []

    async def upload(content, key, _content_type):
        objects[key] = content

    async def delete(keys):
        for key in keys:
            objects.pop(key, None)
            deleted.append(key)
        return len(keys)

    storage = SimpleNamespace(
        upload_file=AsyncMock(side_effect=upload), delete_files=AsyncMock(side_effect=delete)
    )
    monkeypatch.setattr(document_rename, "MinioStorageRepository", lambda: storage)
    monkeypatch.setattr(
        document_rename,
        "read_bounded_document_uploads",
        AsyncMock(side_effect=lambda *_args, **_kwargs: list(uploads)),
    )
    monkeypatch.setattr(
        document_rename,
        "classify_documents_bounded",
        lambda *_args, **_kwargs: [
            ClassifiedDocument(
                original_filename="visa.pdf",
                detected_type="visa",
                accepted=True,
                reason="Synthetic accepted visa",
                text="Synthetic text",
                extracted_name="Synthetic Passenger",
                extracted_passport_number=None,
                extracted_reference=None,
            )
        ],
    )
    # SQLite cannot execute PostgreSQL transaction advisory locks. Keep all
    # actual ORM rereads/ownership/receipts; this fixture makes no PG lock claim.
    monkeypatch.setattr(
        document_rename_chunk_staging, "acquire_document_upload_advisory_lock", AsyncMock()
    )
    return SimpleNamespace(
        session=db_session,
        user=user,
        uploads=uploads,
        storage=storage,
        objects=objects,
        deleted=deleted,
    )


async def _send(fixture, upload_id, chunk_id, index, *, total=2):
    return await document_rename.analyze_and_rename_documents(
        files=[object()],
        title="Synthetic trip",
        upload_id=upload_id,
        chunk_id=chunk_id,
        chunk_index=index,
        expected_chunk_count=total,
        expected_file_count=total,
        current_user=fixture.user,
        session=fixture.session,
    )


async def test_actual_two_chunk_workflow_and_exact_replays_preserve_private_objects(rename_upload):
    f = rename_upload
    upload_id, first_id, final_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    first = await _send(f, upload_id, first_id, 0)
    assert first.status == "processing" and first.total_count == 1 and first.items == []
    replay = await _send(f, upload_id, first_id, 0)
    # SQLite returns a naive datetime on reload; compare the same stored UTC
    # instant explicitly while retaining equality for every business field.
    assert replay.created_at.replace(tzinfo=UTC) == first.created_at.replace(tzinfo=UTC)
    assert replay.model_dump(exclude={"created_at"}) == first.model_dump(exclude={"created_at"})
    assert f.storage.upload_file.await_count == 1 and len(f.objects) == 1
    final = await _send(f, upload_id, final_id, 1)
    assert final.status == "completed" and final.total_count == final.visa_count == 2
    assert {item.renamed_filename for item in final.items} == {
        "SYNTHETIC_PASSENGER_VISA.pdf",
        "SYNTHETIC_PASSENGER_VISA_2.pdf",
    }
    assert (await _send(f, upload_id, final_id, 1)).model_dump() == final.model_dump()
    f.uploads[0] = BoundedDocumentUpload("visa.pdf", b"%PDF changed payload", "application/pdf")
    with pytest.raises(HTTPException) as mismatch:
        await _send(f, upload_id, final_id, 1)
    assert mismatch.value.status_code == 409
    assert len(f.objects) == f.storage.upload_file.await_count == 2 and f.deleted == []
    receipts = list(
        (
            await f.session.scalars(
                select(DocumentUploadChunkModel).order_by(DocumentUploadChunkModel.chunk_index)
            )
        ).all()
    )
    assert [receipt.chunk_index for receipt in receipts] == [0, 1]
    assert all(
        receipt.upload_id == upload_id and receipt.agency_id == f.user.agency_id
        for receipt in receipts
    )
    audits = list(
        (
            await f.session.scalars(
                select(AuditLogModel).where(AuditLogModel.entity_id == str(upload_id))
            )
        ).all()
    )
    assert {audit.action for audit in audits} == {
        "document_rename_chunk_uploaded",
        "document_rename_completed",
    }
    assert "Synthetic Passenger" not in json.dumps([audit.metadata_json for audit in audits])


@pytest.mark.parametrize("winner", ["exact", "different_bytes", "foreign_agency"])
async def test_independently_committed_chunk_winner_fences_staged_loser(rename_upload, winner):
    f = rename_upload
    upload_id, chunk_id = uuid.uuid4(), uuid.uuid4()
    entered, release = asyncio.Event(), asyncio.Event()
    original_upload = f.storage.upload_file.side_effect

    async def paused_upload(*args):
        entered.set()
        await release.wait()
        await original_upload(*args)

    f.storage.upload_file.side_effect = paused_upload
    task = asyncio.create_task(_send(f, upload_id, chunk_id, 0, total=1))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        factory = async_sessionmaker(f.session.bind, expire_on_commit=False)
        async with factory() as other:
            agency_id = f.user.agency_id
            if winner == "foreign_agency":
                agency_id = uuid.uuid4()
                other.add(
                    AgencyModel(id=agency_id, name="Synthetic other", email="other@example.test")
                )
                await other.flush()
            now = datetime.now(UTC)
            other.add(
                DocumentRenameBatchModel(
                    id=upload_id,
                    agency_id=agency_id,
                    title="Synthetic trip",
                    status="completed",
                    total_count=1,
                    visa_count=1,
                    ticket_count=0,
                    unknown_count=0,
                    created_by_user_id=f.user.id,
                    created_at=now,
                    updated_at=now,
                )
            )
            await other.flush()
            other.add(
                DocumentRenameItemModel(
                    id=uuid.uuid4(),
                    batch_id=upload_id,
                    agency_id=agency_id,
                    original_filename="winner.pdf",
                    renamed_filename="WINNER_VISA.pdf",
                    storage_key="synthetic-winner-private-key",
                    content_type="application/pdf",
                    detected_type="visa",
                    status="renamed",
                    created_at=now,
                    updated_at=now,
                )
            )
            metadata = resolve_document_chunk_metadata(
                upload_id=upload_id,
                chunk_id=chunk_id,
                chunk_index=0,
                expected_chunk_count=1,
                expected_file_count=1,
            )
            other.add(
                new_document_chunk_receipt(
                    metadata=metadata,
                    agency_id=agency_id,
                    workflow="rename",
                    group_id=None,
                    document_type=None,
                    fingerprint=document_chunk_fingerprint(f.uploads)
                    if winner != "different_bytes"
                    else "0" * 64,
                    file_count=1,
                    byte_count=len(f.uploads[0].content),
                    accepted_count=1,
                    rejected_count=0,
                )
            )
            await other.commit()
        f.objects["synthetic-winner-private-key"] = b"synthetic winner payload"
        release.set()
        if winner == "exact":
            response = await asyncio.wait_for(task, 3)
            assert (
                response.total_count == 1
                and response.items[0].renamed_filename == "WINNER_VISA.pdf"
            )
        else:
            with pytest.raises(HTTPException) as denied:
                await asyncio.wait_for(task, 3)
            assert denied.value.status_code == 409
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 3)
    assert len(f.deleted) == 1 and f.deleted[0] != "synthetic-winner-private-key"
    assert f.objects == {"synthetic-winner-private-key": b"synthetic winner payload"}
    assert await f.session.scalar(select(func.count()).select_from(DocumentUploadChunkModel)) == 1
    assert await f.session.scalar(select(func.count()).select_from(DocumentRenameItemModel)) == 1
