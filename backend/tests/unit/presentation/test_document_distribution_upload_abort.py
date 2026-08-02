from __future__ import annotations

import inspect as py_inspect
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.infrastructure.documents.distribution_capacity import (
    MAX_DISTRIBUTION_ASSIGNMENT_ROWS_PER_SCOPE,
    DocumentDistributionCapacityError,
)
from app.presentation.api.v1.routes import document_distribution


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _scalars_result(values):
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(values)
    return result


def _scalar_one_result(value):
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


@pytest.mark.asyncio
async def test_new_first_chunk_is_rejected_while_another_upload_is_processing(
    monkeypatch,
) -> None:
    group_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    blocking_upload_id = uuid.uuid4()
    monkeypatch.setattr(
        document_distribution,
        "_get_authorized_group",
        AsyncMock(return_value=SimpleNamespace(id=group_id, agency_id=agency_id)),
    )
    blocker = AsyncMock(return_value=blocking_upload_id)
    monkeypatch.setattr(
        document_distribution,
        "_first_blocking_processing_upload_id",
        blocker,
    )

    with pytest.raises(HTTPException) as error:
        await document_distribution.upload_documents(
            group_id=group_id,
            document_type="visa",
            files=[MagicMock()],
            upload_id=uuid.uuid4(),
            chunk_id=uuid.uuid4(),
            chunk_index=0,
            expected_chunk_count=1,
            expected_file_count=1,
            current_user=SimpleNamespace(id=uuid.uuid4()),
            session=MagicMock(),
        )

    assert error.value.status_code == 409
    assert "existing incomplete upload" in error.value.detail
    blocker.assert_awaited_once()


@pytest.mark.asyncio
async def test_review_surfaces_every_processing_upload_id(monkeypatch) -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    processing = [
        SimpleNamespace(
            id=uuid.uuid4(),
            agency_id=agency_id,
            group_id=group_id,
            document_type="visa",
            status="processing",
            uploaded_count=1,
            rejected_count=0,
            matched_count=1,
            saved_at=None,
            created_at=now,
        )
        for _ in range(2)
    ]
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalars_result(processing))
    monkeypatch.setattr(
        document_distribution,
        "MinioStorageRepository",
        MagicMock(return_value=MagicMock()),
    )

    response = await document_distribution._batch_response(
        session=session,
        group_id=group_id,
        agency_id=agency_id,
        document_type="visa",
        passengers=[],
        batch=None,
        documents=[],
    )

    assert response.status == "processing"
    assert response.batch_id == processing[0].id
    assert response.processing_upload_ids == [item.id for item in processing]


@pytest.mark.asyncio
async def test_group_document_ledger_read_fails_closed_instead_of_truncating() -> None:
    documents = [
        SimpleNamespace(id=uuid.uuid4())
        for _ in range(MAX_DISTRIBUTION_ASSIGNMENT_ROWS_PER_SCOPE + 1)
    ]
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalars_result(documents))

    with pytest.raises(HTTPException) as error:
        await document_distribution._all_group_documents(
            session,
            group_id=uuid.uuid4(),
            agency_id=uuid.uuid4(),
            document_type="visa",
        )

    assert error.value.status_code == 409
    statement = session.execute.await_args.args[0]
    assert statement._limit_clause.value == MAX_DISTRIBUTION_ASSIGNMENT_ROWS_PER_SCOPE + 1


@pytest.mark.asyncio
async def test_locked_scope_capacity_counts_existing_rows_and_rejects_overflow() -> None:
    session = MagicMock()
    session.execute = AsyncMock(
        return_value=_scalar_one_result(MAX_DISTRIBUTION_ASSIGNMENT_ROWS_PER_SCOPE)
    )

    with pytest.raises(DocumentDistributionCapacityError) as error:
        await document_distribution._enforce_group_document_assignment_capacity(
            session,
            group_id=uuid.uuid4(),
            agency_id=uuid.uuid4(),
            document_type="visa",
            incoming_rows=1,
        )

    assert error.value.scope == "group_document_type"


def test_bulk_and_reupload_capacity_errors_are_mapped_to_413_after_scope_lock() -> None:
    for handler in (
        document_distribution.upload_documents,
        document_distribution.reupload_passenger_document,
    ):
        source = py_inspect.getsource(handler)
        assert source.index("acquire_document_upload_scope_advisory_lock") < source.index(
            "enforce_capacity_before_persistence"
        )
        assert "except DocumentDistributionCapacityError as exc" in source
        # Keep this source-level ordering contract compatible with Starlette
        # releases that expose only HTTP_413_REQUEST_ENTITY_TOO_LARGE.
        assert "status_code=413" in source


@pytest.mark.asyncio
async def test_abort_processing_upload_is_scoped_transactional_and_cleans_after_commit(
    monkeypatch,
) -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    batch_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    remaining_id = uuid.uuid4()
    batch = SimpleNamespace(
        id=batch_id,
        agency_id=agency_id,
        group_id=group_id,
        document_type="visa",
        status="processing",
    )
    receipts = [SimpleNamespace(id=uuid.uuid4()) for _ in range(2)]
    documents = [
        SimpleNamespace(
            id=uuid.uuid4(),
            storage_key="document-distribution/partial.pdf",
            original_filename="Passenger Name.pdf",
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            storage_key="document-distribution/shared.pdf",
            original_filename="Other Passenger.pdf",
        ),
    ]
    execute_results = [
        _scalar_result(batch),
        _scalars_result(receipts),
        _scalars_result(documents),
        _scalar_result(None),
        _scalars_result(["document-distribution/shared.pdf"]),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        _scalars_result([remaining_id]),
    ]
    session = MagicMock()
    session.execute = AsyncMock(side_effect=execute_results)
    session.rollback = AsyncMock()
    events: list[str] = []

    async def commit() -> None:
        events.append("commit")

    session.commit = AsyncMock(side_effect=commit)
    monkeypatch.setattr(
        document_distribution,
        "_get_authorized_group",
        AsyncMock(return_value=SimpleNamespace(id=group_id, agency_id=agency_id)),
    )
    monkeypatch.setattr(
        document_distribution,
        "_lock_active_document_scope",
        AsyncMock(return_value=(SimpleNamespace(id=actor_id), SimpleNamespace())),
    )
    scope_lock = AsyncMock()
    upload_lock = AsyncMock()
    monkeypatch.setattr(
        document_distribution,
        "acquire_document_upload_scope_advisory_lock",
        scope_lock,
    )
    monkeypatch.setattr(
        document_distribution,
        "acquire_document_upload_advisory_lock",
        upload_lock,
    )
    staged_job = SimpleNamespace(id=uuid.uuid4(), object_count=1)
    stage_cleanup = MagicMock(return_value=(staged_job,))
    monkeypatch.setattr(
        document_distribution,
        "stage_storage_cleanup_jobs",
        stage_cleanup,
    )
    audit_record = AsyncMock()
    monkeypatch.setattr(
        document_distribution,
        "AuditLogRepository",
        lambda _session: SimpleNamespace(record=audit_record),
    )

    async def process_cleanup(_job_id: uuid.UUID):
        events.append("cleanup")
        return SimpleNamespace(completed=True)

    monkeypatch.setattr(
        document_distribution,
        "process_storage_cleanup_job",
        process_cleanup,
    )

    response = await document_distribution.abort_incomplete_distribution_upload(
        group_id=group_id,
        document_type="visa",
        batch_id=batch_id,
        current_user=SimpleNamespace(id=actor_id),
        session=session,
    )

    assert events == ["commit", "cleanup"]
    assert response.batch_id == batch_id
    assert response.deleted_document_count == 2
    assert response.deleted_chunk_count == 2
    assert response.deleted_storage_object_count == 1
    assert response.storage_cleanup_pending is False
    assert response.remaining_processing_upload_ids == [remaining_id]
    scope_lock.assert_awaited_once_with(
        session,
        agency_id=agency_id,
        group_id=group_id,
        document_type="visa",
    )
    upload_lock.assert_awaited_once_with(
        session,
        workflow="distribution",
        upload_id=batch_id,
    )
    stage_cleanup.assert_called_once_with(
        session,
        agency_id=agency_id,
        source="document_distribution_abort",
        context_id=str(batch_id),
        storage_keys=["document-distribution/partial.pdf"],
    )
    audit_payload = audit_record.await_args.kwargs
    assert audit_payload["action"] == "document_distribution_upload_aborted"
    assert "actor_email" not in audit_payload
    audit_text = repr(audit_payload["metadata"])
    assert "Passenger Name.pdf" not in audit_text
    assert "document-distribution/" not in audit_text

    delete_statements = [str(call.args[0]) for call in session.execute.await_args_list[5:8]]
    assert "DELETE FROM distributed_documents" in delete_statements[0]
    assert "batch_id" in delete_statements[0] and "agency_id" in delete_statements[0]
    assert "DELETE FROM document_upload_chunks" in delete_statements[1]
    assert "upload_id" in delete_statements[1] and "workflow" in delete_statements[1]
    assert "DELETE FROM document_distribution_batches" in delete_statements[2]
    assert "status" in delete_statements[2] and "document_type" in delete_statements[2]


@pytest.mark.asyncio
async def test_abort_refuses_completed_batch_before_delete_or_cleanup(monkeypatch) -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    batch_id = uuid.uuid4()
    session = MagicMock()
    session.execute = AsyncMock(
        return_value=_scalar_result(SimpleNamespace(id=batch_id, status="draft"))
    )
    session.commit = AsyncMock()
    monkeypatch.setattr(
        document_distribution,
        "_get_authorized_group",
        AsyncMock(return_value=SimpleNamespace(id=group_id, agency_id=agency_id)),
    )
    monkeypatch.setattr(
        document_distribution,
        "_lock_active_document_scope",
        AsyncMock(return_value=(SimpleNamespace(id=uuid.uuid4()), SimpleNamespace())),
    )
    monkeypatch.setattr(
        document_distribution,
        "acquire_document_upload_scope_advisory_lock",
        AsyncMock(),
    )
    monkeypatch.setattr(
        document_distribution,
        "acquire_document_upload_advisory_lock",
        AsyncMock(),
    )
    stage_cleanup = MagicMock()
    monkeypatch.setattr(
        document_distribution,
        "stage_storage_cleanup_jobs",
        stage_cleanup,
    )

    with pytest.raises(HTTPException) as error:
        await document_distribution.abort_incomplete_distribution_upload(
            group_id=group_id,
            document_type="visa",
            batch_id=batch_id,
            current_user=SimpleNamespace(id=uuid.uuid4()),
            session=session,
        )

    assert error.value.status_code == 409
    stage_cleanup.assert_not_called()
    session.commit.assert_not_awaited()
    assert session.execute.await_count == 1
