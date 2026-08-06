from __future__ import annotations

import inspect as py_inspect
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.infrastructure.database.models import DocumentUploadChunkModel
from app.infrastructure.documents.pdf_parser_sandbox import (
    MAX_PDF_SCALED_BATCH_SECONDS,
    bounded_pdf_batch_timeout_seconds,
)
from app.presentation.api.v1.document_chunk_uploads import (
    MAX_DOCUMENT_FILES_PER_CHUNK,
    MAX_LOGICAL_DOCUMENT_BYTES,
    acquire_document_upload_advisory_lock,
    acquire_document_upload_scope_advisory_lock,
    document_upload_advisory_lock_key,
    document_upload_scope_advisory_lock_key,
    resolve_concurrent_document_chunk_replay,
    resolve_document_chunk_metadata,
    validate_document_chunk_size,
    validate_existing_document_chunk,
    validate_next_document_chunk,
)
from app.presentation.api.v1.routes.document_distribution import (
    router as distribution_router,
)
from app.presentation.api.v1.routes.document_distribution import (
    upload_documents,
)
from app.presentation.api.v1.routes.document_rename import (
    analyze_and_rename_documents,
)
from app.presentation.api.v1.routes.document_rename import (
    router as rename_router,
)


def _metadata(
    *,
    upload_id: uuid.UUID | None = None,
    chunk_id: uuid.UUID | None = None,
    chunk_index: int = 0,
    expected_chunk_count: int = 1,
    expected_file_count: int = 1,
):
    return resolve_document_chunk_metadata(
        upload_id=upload_id or uuid.uuid4(),
        chunk_id=chunk_id or uuid.uuid4(),
        chunk_index=chunk_index,
        expected_chunk_count=expected_chunk_count,
        expected_file_count=expected_file_count,
    )


def _receipt(
    *,
    upload_id: uuid.UUID,
    chunk_index: int,
    expected_chunk_count: int,
    expected_file_count: int,
    agency_id: uuid.UUID | None = None,
    chunk_id: uuid.UUID | None = None,
    fingerprint: str = "a" * 64,
) -> DocumentUploadChunkModel:
    return DocumentUploadChunkModel(
        id=chunk_id or uuid.uuid4(),
        upload_id=upload_id,
        agency_id=agency_id or uuid.uuid4(),
        workflow="rename",
        group_id=None,
        document_type=None,
        chunk_index=chunk_index,
        expected_chunk_count=expected_chunk_count,
        expected_file_count=expected_file_count,
        file_count=1,
        byte_count=1024,
        fingerprint=fingerprint,
        accepted_count=1,
        rejected_count=0,
        rejected_documents=[],
        created_at=datetime.now(tz=UTC),
    )


def test_legacy_request_may_omit_all_chunk_metadata() -> None:
    assert resolve_document_chunk_metadata(
        upload_id=None,
        chunk_id=None,
        chunk_index=None,
        expected_chunk_count=None,
        expected_file_count=None,
    ) is None


def test_state_changing_document_chunk_routes_require_cookie_csrf() -> None:
    routes = [
        next(
            route
            for route in rename_router.routes
            if route.path == "/batches" and route.methods == {"POST"}
        ),
        next(route for route in rename_router.routes if route.path == "/batches/bulk-delete"),
        *[
            next(route for route in distribution_router.routes if route.path == path)
            for path in (
                "/groups/{group_id}/{document_type}/uploads/{batch_id}/abort",
                "/groups/{group_id}/{document_type}/passengers/{passenger_id}/reupload",
                "/groups/{group_id}/{document_type}/documents/unassign",
                "/groups/{group_id}/{document_type}/documents/delete",
                "/batches/{batch_id}/save",
                "/batches/{batch_id}/whatsapp-send",
            )
        ],
        next(
            route
            for route in distribution_router.routes
            if route.path == "/groups/{group_id}/{document_type}/upload"
        ),
    ]

    for route in routes:
        dependencies = {
            dependency.call.__name__ for dependency in route.dependant.dependencies
        }
        assert "require_cookie_csrf" in dependencies


@pytest.mark.asyncio
async def test_advisory_lock_is_stable_transaction_scoped_and_precedes_final_rereads() -> None:
    upload_id = uuid.uuid4()
    session = MagicMock()
    session.execute = AsyncMock()

    lock_key = await acquire_document_upload_advisory_lock(
        session,
        workflow="rename",
        upload_id=upload_id,
    )

    assert lock_key == document_upload_advisory_lock_key(
        workflow="rename",
        upload_id=upload_id,
    )
    assert lock_key != document_upload_advisory_lock_key(
        workflow="distribution",
        upload_id=upload_id,
    )
    assert "pg_advisory_xact_lock" in str(session.execute.await_args.args[0])
    for handler in (analyze_and_rename_documents, upload_documents):
        source = py_inspect.getsource(handler)
        assert source.index("acquire_document_upload_advisory_lock") < source.index(
            "serialized_batch_result"
        ) < source.index("locked_receipts_result")


@pytest.mark.asyncio
async def test_distribution_scope_lock_is_stable_and_precedes_upload_lock() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    session = MagicMock()
    session.execute = AsyncMock()

    lock_key = await acquire_document_upload_scope_advisory_lock(
        session,
        agency_id=agency_id,
        group_id=group_id,
        document_type="visa",
    )

    assert lock_key == document_upload_scope_advisory_lock_key(
        agency_id=agency_id,
        group_id=group_id,
        document_type="visa",
    )
    assert lock_key != document_upload_scope_advisory_lock_key(
        agency_id=agency_id,
        group_id=group_id,
        document_type="flight_ticket",
    )
    assert "pg_advisory_xact_lock" in str(session.execute.await_args.args[0])

    source = py_inspect.getsource(upload_documents)
    assert source.index("acquire_document_upload_scope_advisory_lock") < source.index(
        "acquire_document_upload_advisory_lock"
    ) < source.index("serialized_batch_result")
    assert source.count("_first_blocking_processing_upload_id") == 2


def test_chunk_manifest_is_all_or_nothing_and_caps_logical_selection() -> None:
    with pytest.raises(HTTPException) as incomplete:
        resolve_document_chunk_metadata(
            upload_id=uuid.uuid4(),
            chunk_id=None,
            chunk_index=0,
            expected_chunk_count=1,
            expected_file_count=1,
        )
    assert incomplete.value.status_code == 400

    with pytest.raises(HTTPException) as oversized:
        _metadata(expected_file_count=1_501)
    assert oversized.value.status_code == 413


def test_server_chunk_count_remains_memory_bounded() -> None:
    metadata = _metadata(
        expected_chunk_count=2,
        expected_file_count=MAX_DOCUMENT_FILES_PER_CHUNK + 1,
    )
    with pytest.raises(HTTPException) as error:
        validate_document_chunk_size(
            metadata,
            file_count=MAX_DOCUMENT_FILES_PER_CHUNK + 1,
        )
    assert error.value.status_code == 413


def test_server_accepts_fifty_file_chunk_and_rejects_fifty_one() -> None:
    assert MAX_DOCUMENT_FILES_PER_CHUNK == 50
    metadata = _metadata(expected_file_count=50)
    assert metadata is not None

    validate_document_chunk_size(metadata, file_count=50)

    with pytest.raises(HTTPException) as manifest_error:
        _metadata(expected_file_count=51)
    assert manifest_error.value.status_code == 400

    with pytest.raises(HTTPException) as chunk_error:
        validate_document_chunk_size(metadata, file_count=51)
    assert chunk_error.value.status_code == 413


def test_same_chunk_token_replay_requires_exact_scope_manifest_and_fingerprint() -> None:
    agency_id = uuid.uuid4()
    upload_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    metadata = _metadata(upload_id=upload_id, chunk_id=chunk_id)
    assert metadata is not None
    receipt = _receipt(
        upload_id=upload_id,
        chunk_index=0,
        expected_chunk_count=1,
        expected_file_count=1,
        agency_id=agency_id,
        chunk_id=chunk_id,
    )
    validate_existing_document_chunk(
        receipt,
        metadata=metadata,
        agency_id=agency_id,
        workflow="rename",
        group_id=None,
        document_type=None,
        fingerprint="a" * 64,
        file_count=1,
        byte_count=1024,
    )

    with pytest.raises(HTTPException) as cross_tenant:
        validate_existing_document_chunk(
            receipt,
            metadata=metadata,
            agency_id=uuid.uuid4(),
            workflow="rename",
            group_id=None,
            document_type=None,
            fingerprint="a" * 64,
            file_count=1,
            byte_count=1024,
        )
    assert cross_tenant.value.status_code == 409

    with pytest.raises(HTTPException) as changed_payload:
        validate_existing_document_chunk(
            receipt,
            metadata=metadata,
            agency_id=agency_id,
            workflow="rename",
            group_id=None,
            document_type=None,
            fingerprint="b" * 64,
            file_count=1,
            byte_count=1024,
        )
    assert changed_payload.value.status_code == 409


def test_1500_file_manifest_completes_only_on_contiguous_final_chunk() -> None:
    upload_id = uuid.uuid4()
    receipts = [
        _receipt(
            upload_id=upload_id,
            chunk_index=index,
            expected_chunk_count=1_500,
            expected_file_count=1_500,
        )
        for index in range(1_499)
    ]
    metadata = _metadata(
        upload_id=upload_id,
        chunk_index=1_499,
        expected_chunk_count=1_500,
        expected_file_count=1_500,
    )
    assert metadata is not None
    assert validate_next_document_chunk(
        receipts,
        metadata=metadata,
        incoming_file_count=1,
        incoming_byte_count=1024,
    )


def test_out_of_order_or_mismatched_totals_never_complete() -> None:
    upload_id = uuid.uuid4()
    metadata = _metadata(
        upload_id=upload_id,
        chunk_index=1,
        expected_chunk_count=2,
        expected_file_count=3,
    )
    assert metadata is not None
    first = _receipt(
        upload_id=upload_id,
        chunk_index=0,
        expected_chunk_count=2,
        expected_file_count=3,
    )
    with pytest.raises(HTTPException) as totals:
        validate_next_document_chunk(
            [first],
            metadata=metadata,
            incoming_file_count=1,
            incoming_byte_count=1024,
        )
    assert totals.value.status_code == 409


def test_scaled_parser_budget_covers_max_chunk_below_request_timeout() -> None:
    assert (
        bounded_pdf_batch_timeout_seconds(MAX_DOCUMENT_FILES_PER_CHUNK)
        == MAX_PDF_SCALED_BATCH_SECONDS
    )
    assert bounded_pdf_batch_timeout_seconds(1_500) == MAX_PDF_SCALED_BATCH_SECONDS


def test_server_enforces_cumulative_two_gibibyte_logical_upload_cap() -> None:
    upload_id = uuid.uuid4()
    metadata = _metadata(
        upload_id=upload_id,
        chunk_index=1,
        expected_chunk_count=2,
        expected_file_count=2,
    )
    assert metadata is not None
    first = _receipt(
        upload_id=upload_id,
        chunk_index=0,
        expected_chunk_count=2,
        expected_file_count=2,
    )
    first.byte_count = MAX_LOGICAL_DOCUMENT_BYTES

    with pytest.raises(HTTPException) as error:
        validate_next_document_chunk(
            [first],
            metadata=metadata,
            incoming_file_count=1,
            incoming_byte_count=1,
        )

    assert error.value.status_code == 413


def test_database_constraints_fence_concurrent_chunk_index_and_manifest_shape() -> None:
    constraints = {
        constraint.name: str(getattr(constraint, "sqltext", ""))
        for constraint in DocumentUploadChunkModel.__table__.constraints
        if constraint.name
    }
    assert "uq_document_upload_chunks_workflow_upload_index" in constraints
    assert "chunk_index < expected_chunk_count" in constraints[
        "ck_document_upload_chunks_index_manifest"
    ]
    assert "expected_file_count <= expected_chunk_count * 50" in constraints[
        "ck_document_upload_chunks_manifest_capacity"
    ]
    assert "file_count BETWEEN 1 AND 50" in constraints[
        "ck_document_upload_chunks_file_count"
    ]
    assert "accepted_count + rejected_count = file_count" in constraints[
        "ck_document_upload_chunks_result_counts"
    ]


def test_concurrent_same_index_exact_payload_resolves_as_idempotent_replay() -> None:
    agency_id = uuid.uuid4()
    upload_id = uuid.uuid4()
    metadata = _metadata(upload_id=upload_id, chunk_id=uuid.uuid4())
    assert metadata is not None
    winning_receipt = _receipt(
        upload_id=upload_id,
        chunk_index=0,
        expected_chunk_count=1,
        expected_file_count=1,
        agency_id=agency_id,
        chunk_id=uuid.uuid4(),
    )

    resolved = resolve_concurrent_document_chunk_replay(
        [winning_receipt],
        metadata=metadata,
        agency_id=agency_id,
        workflow="rename",
        group_id=None,
        document_type=None,
        fingerprint="a" * 64,
        file_count=1,
        byte_count=1024,
    )

    assert resolved is winning_receipt

    with pytest.raises(HTTPException) as mismatch:
        resolve_concurrent_document_chunk_replay(
            [winning_receipt],
            metadata=metadata,
            agency_id=agency_id,
            workflow="rename",
            group_id=None,
            document_type=None,
            fingerprint="b" * 64,
            file_count=1,
            byte_count=1024,
        )
    assert mismatch.value.status_code == 409
