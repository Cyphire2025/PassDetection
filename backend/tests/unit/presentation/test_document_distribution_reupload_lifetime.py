"""Route-owned private objects after a synthetic producer's successful return.

Authorization, ORM rows, transaction ordering and compensation helper are real.
PDF/AV/classification and producer I/O are isolated synthetic boundaries; this
does not qualify a real parser, provider or object-storage server.
"""

from __future__ import annotations

import asyncio
import uuid
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anyio
import pytest
from fastapi import UploadFile
from sqlalchemy import func, select

from app.infrastructure.database.models import (
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
)
from app.infrastructure.documents.document_matcher import ClassifiedDocument
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.routes import document_distribution_manual_upload as manual
from app.presentation.api.v1.routes import document_distribution_reupload as route
from app.presentation.api.v1.routes import document_distribution_storage as storage
from tests.unit.presentation.test_document_distribution_residual_lifecycle import context


@pytest.mark.parametrize("kind", ["reupload", "manual"])
@pytest.mark.parametrize(
    "phase",
    [
        "healthy",
        "audit_error",
        "audit_cancel",
        "audit_scope_cancel",
        "audit_error_cleanup_cancel",
        "audit_cancel_cleanup_cancel",
        "commit_error",
        "commit_cancel",
    ],
)
async def test_reupload_compensation_and_ambiguous_commit_contract(
    db_session, monkeypatch, phase, kind
):
    ctx = await context(db_session)
    await db_session.commit()
    # Exercise the real SQL call/order on SQLite; this no-op does not qualify
    # PostgreSQL advisory-lock serialization or any service-dependent behavior.
    raw = await (await db_session.connection()).get_raw_connection()
    await raw.driver_connection.create_function("pg_advisory_xact_lock", 1, lambda _key: None)
    new_key = f"document-distribution/{ctx.agency_id}/{ctx.group_id}/visa/{uuid.uuid4()}.pdf"
    retained_key = "synthetic-existing-retained-document.pdf"
    objects = {retained_key: b"retained"}
    deleted = []
    audit_started = asyncio.Event()
    cleanup_started, cleanup_release = asyncio.Event(), asyncio.Event()
    ordinary_error = OSError("synthetic audit or commit failure")
    expected_response = SimpleNamespace(status="saved" if kind == "manual" else "draft")
    selected = manual if kind == "manual" else route
    cancel_scope = None

    class ObjectStore:
        async def delete_files(self, keys):
            if "cleanup_cancel" in phase:
                cleanup_started.set()
                await cleanup_release.wait()
            deleted.extend(keys)
            for key in keys:
                objects.pop(key, None)

    class Producer:
        def __init__(self, session):
            self.session = session

        async def ingest(self, **kwargs):
            await kwargs["before_persistence"]()
            await kwargs["before_persistence_capacity"](1)
            batch = DocumentDistributionBatchModel(
                agency_id=ctx.agency_id,
                group_id=ctx.group_id,
                document_type="visa",
                created_by_user_id=ctx.actor.id,
                uploaded_count=1,
                matched_count=1,
            )
            self.session.add(batch)
            await self.session.flush()
            document = DistributedDocumentModel(
                batch_id=batch.id,
                agency_id=ctx.agency_id,
                group_id=ctx.group_id,
                passenger_id=ctx.passenger_id,
                document_type="visa",
                original_filename="synthetic.pdf",
                storage_key=new_key,
                detected_type="visa",
                match_status="matched",
            )
            self.session.add(document)
            objects[new_key] = b"synthetic private PDF"
            if "before_persistence_documents" in kwargs:
                await kwargs["before_persistence_documents"]([document])
            await self.session.flush()
            return SimpleNamespace(
                batch=batch, documents=[document], created_storage_keys=(new_key,)
            )

    original_record = AuditLogRepository.record

    async def record(self, *args, **kwargs):
        if kwargs.get("action") in {
            "document_distribution_passenger_document_added",
            "document_distribution_manual_passenger_upload",
        }:
            audit_started.set()
            if phase.startswith("audit_cancel"):
                await asyncio.Event().wait()
            if phase == "audit_scope_cancel":
                assert cancel_scope is not None
                cancel_scope.cancel()
                await anyio.sleep(0)
            if phase.startswith("audit_error"):
                raise ordinary_error
        return await original_record(self, *args, **kwargs)

    original_commit = db_session.commit

    async def commit_with_lost_ack():
        await original_commit()
        if phase == "commit_cancel":
            raise asyncio.CancelledError("synthetic committed cancellation")
        raise ordinary_error

    monkeypatch.setattr(
        selected,
        "read_bounded_document_uploads",
        AsyncMock(
            return_value=[
                SimpleNamespace(
                    filename="synthetic.pdf",
                    content=b"isolated PDF boundary",
                    content_type="application/pdf",
                )
            ]
        ),
    )
    if kind == "reupload":
        monkeypatch.setattr(
            selected,
            "classify_documents_bounded",
            lambda *args, **kwargs: [
                ClassifiedDocument(
                    original_filename="synthetic.pdf",
                    detected_type="visa",
                    accepted=True,
                    reason="Synthetic approved classification",
                    text="",
                    extracted_name=None,
                    extracted_passport_number=None,
                    extracted_reference=None,
                )
            ],
        )
    monkeypatch.setattr(selected, "TravelDocumentIngestionService", Producer)
    monkeypatch.setattr(storage, "MinioStorageRepository", ObjectStore)
    monkeypatch.setattr(AuditLogRepository, "record", record)
    monkeypatch.setattr(selected, "_all_group_documents", AsyncMock(return_value=[]))
    monkeypatch.setattr(selected, "_batch_response", AsyncMock(return_value=expected_response))
    if phase.startswith("commit_"):
        monkeypatch.setattr(db_session, "commit", commit_with_lost_ack)

    async def invoke():
        arguments = dict(
            group_id=ctx.group_id,
            document_type="visa",
            passenger_id=ctx.passenger_id,
            file=UploadFile(file=BytesIO(b"isolated"), filename="synthetic.pdf"),
            current_user=ctx.actor,
            session=db_session,
        )
        if kind == "manual":
            return await selected.manually_upload_passenger_document(
                **arguments, mode="add", replacement_documents="[]"
            )
        return await selected.reupload_passenger_document(**arguments)

    task = None
    try:
        if phase == "audit_scope_cancel":
            with anyio.CancelScope() as cancel_scope:
                await invoke()
            assert cancel_scope.cancel_called
        else:
            task = asyncio.create_task(invoke())
            if phase.startswith("audit_cancel"):
                await asyncio.wait_for(audit_started.wait(), 3)
                task.cancel("synthetic precommit cancellation")
            if "cleanup_cancel" in phase:
                await asyncio.wait_for(cleanup_started.wait(), 3)
                for _ in range(2):
                    task.cancel("additional cleanup cancellation")
                    await asyncio.sleep(0)
                assert not task.done()
                cleanup_release.set()
            if phase.startswith("audit_error") or phase.endswith("error"):
                with pytest.raises(OSError) as raised:
                    await task
                assert raised.value is ordinary_error
            elif phase.endswith("cancel"):
                with pytest.raises(asyncio.CancelledError) as raised:
                    await task
                if phase.startswith("audit_cancel"):
                    assert raised.value.args == ("synthetic precommit cancellation",)
            else:
                assert await task is expected_response
        # This is also what the outer request-session owner does on failure.
        await db_session.rollback()
        precommit_failure = phase.startswith("audit_")
        assert deleted == ([new_key] if precommit_failure else [])
        assert set(objects) == ({retained_key} if precommit_failure else {retained_key, new_key})
        assert await db_session.scalar(
            select(func.count()).select_from(DocumentDistributionBatchModel)
        ) == (1 if precommit_failure else 2)
        assert await db_session.scalar(
            select(func.count()).select_from(DistributedDocumentModel)
        ) == (0 if precommit_failure else 1)
    finally:
        cleanup_release.set()
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
