from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.domain.entities.entities import UserRole
from app.infrastructure.documents.document_matcher import (
    ClassifiedDocument,
    UnsupportedDocumentBatchFormatError,
)
from app.infrastructure.documents.verification_staging import (
    StagedDocumentReceipt,
    VerificationReceiptExpiredError,
    VerificationReceiptScopeChangedError,
)
from app.presentation.api.v1.routes import document_distribution


def _classification(filename: str = "verified.pdf") -> ClassifiedDocument:
    return ClassifiedDocument(
        original_filename=filename,
        detected_type="visa",
        accepted=True,
        reason="Verified visa structure",
        text="visa document",
        extracted_name="Passenger",
        extracted_passport_number="P1234567",
        extracted_reference="VISA-1",
    )


def _staged_receipt(
    *,
    agency_id: uuid.UUID,
    actor_id: uuid.UUID,
    group_id: uuid.UUID,
    upload_id: uuid.UUID,
    chunk_id: uuid.UUID,
) -> StagedDocumentReceipt:
    receipt_id = uuid.uuid4()
    return StagedDocumentReceipt(
        receipt_id=receipt_id,
        agency_id=agency_id,
        actor_id=actor_id,
        group_id=group_id,
        upload_id=upload_id,
        chunk_id=chunk_id,
        document_type="visa",
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
        storage_key=(f"document-verification-staging/{agency_id}/{actor_id}/{receipt_id}.pdf"),
        filename="verified.pdf",
        content_type="application/pdf",
        byte_count=128,
        content_sha256="a" * 64,
        roster_fingerprint="r" * 64,
        source_fingerprint="s" * 64,
        identifiers_fingerprint="i" * 64,
        classification=_classification(),
    )


def _arrange_upload_route(
    monkeypatch: pytest.MonkeyPatch,
) -> SimpleNamespace:
    group_id, agency_id, user_id, passenger_id, upload_id, chunk_id = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    user = SimpleNamespace(
        id=user_id,
        agency_id=agency_id,
        email="operator@example.test",
        role=UserRole.AGENCY_ADMIN,
    )
    group = SimpleNamespace(id=group_id, agency_id=agency_id)
    passenger = SimpleNamespace(
        id=passenger_id,
        updated_at=None,
        client_name="Passenger",
        client_phone=None,
        family_head_phone=None,
        confirmed_fields={},
        extracted_fields={},
        staff_metadata={},
        custom_answers=[],
        custom_detail_answers=[],
    )
    session = MagicMock()
    empty_result = MagicMock()
    empty_result.scalar_one_or_none.return_value = None
    empty_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=empty_result)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()
    session.commit = AsyncMock()
    monkeypatch.setattr(
        document_distribution,
        "_get_authorized_group",
        AsyncMock(return_value=group),
    )
    monkeypatch.setattr(
        document_distribution,
        "_group_passengers",
        AsyncMock(return_value=[passenger]),
    )
    monkeypatch.setattr(
        document_distribution,
        "_read_linked_document_match_source",
        AsyncMock(return_value=SimpleNamespace(snapshot=())),
    )
    monkeypatch.setattr(
        document_distribution,
        "_linked_document_match_identifiers",
        AsyncMock(return_value=()),
    )
    monkeypatch.setattr(
        document_distribution,
        "_all_group_documents",
        AsyncMock(return_value=[]),
    )
    response = SimpleNamespace(status="draft")
    monkeypatch.setattr(
        document_distribution,
        "_batch_response",
        AsyncMock(return_value=response),
    )
    ingestion = SimpleNamespace(
        batch=SimpleNamespace(status="draft"),
        rejected=[],
        created_storage_keys=[],
    )
    ingest = AsyncMock(return_value=ingestion)
    monkeypatch.setattr(
        document_distribution,
        "TravelDocumentIngestionService",
        lambda *_args, **_kwargs: SimpleNamespace(ingest=ingest),
    )
    cleanup = AsyncMock()
    monkeypatch.setattr(
        document_distribution,
        "cleanup_staged_storage_keys",
        cleanup,
    )
    return SimpleNamespace(
        group_id=group_id,
        agency_id=agency_id,
        user=user,
        upload_id=upload_id,
        chunk_id=chunk_id,
        session=session,
        response=response,
        ingest=ingest,
        cleanup=cleanup,
    )


async def _upload(
    context: SimpleNamespace,
    *,
    files: list[object] | None = None,
    staging_receipts: list[str] | None = None,
) -> object:
    uses_receipts = bool(staging_receipts)
    return await document_distribution.upload_documents(
        group_id=context.group_id,
        document_type="visa",
        files=files,
        staging_receipts=staging_receipts,
        upload_id=context.upload_id if uses_receipts else None,
        chunk_id=context.chunk_id if uses_receipts else None,
        chunk_index=0 if uses_receipts else None,
        expected_chunk_count=1 if uses_receipts else None,
        expected_file_count=len(staging_receipts or []) if uses_receipts else None,
        current_user=context.user,
        session=context.session,
    )


@pytest.mark.asyncio
async def test_get_review_does_not_require_upload_form_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_id, agency_id = uuid.uuid4(), uuid.uuid4()
    group = SimpleNamespace(id=group_id, agency_id=agency_id)
    batch = SimpleNamespace(id=uuid.uuid4())
    session = MagicMock()
    session.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: batch))
    monkeypatch.setattr(
        document_distribution,
        "_get_authorized_group",
        AsyncMock(return_value=group),
    )
    monkeypatch.setattr(
        document_distribution,
        "_group_passengers",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        document_distribution,
        "_all_group_documents",
        AsyncMock(return_value=[]),
    )
    expected = SimpleNamespace(status="draft")
    batch_response = AsyncMock(return_value=expected)
    monkeypatch.setattr(document_distribution, "_batch_response", batch_response)

    result = await document_distribution.get_document_review(
        group_id=group_id,
        document_type="visa",
        current_user=SimpleNamespace(id=uuid.uuid4(), agency_id=agency_id),
        session=session,
    )

    assert result is expected
    batch_response.assert_awaited_once()


@pytest.mark.asyncio
async def test_verify_unsupported_batch_never_references_upload_cleanup_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_id, agency_id, user_id, passenger_id = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    user = SimpleNamespace(
        id=user_id,
        agency_id=agency_id,
        role=UserRole.AGENCY_ADMIN,
    )
    group = SimpleNamespace(id=group_id, agency_id=agency_id)
    passenger = SimpleNamespace(
        id=passenger_id,
        updated_at=None,
        client_name="Passenger",
        client_phone=None,
        family_head_phone=None,
        confirmed_fields={},
        extracted_fields={},
        staff_metadata={},
        custom_answers=[],
        custom_detail_answers=[],
    )
    session = MagicMock()
    session.rollback = AsyncMock()
    monkeypatch.setattr(
        document_distribution,
        "_get_authorized_group",
        AsyncMock(return_value=group),
    )
    monkeypatch.setattr(
        document_distribution,
        "_group_passengers",
        AsyncMock(return_value=[passenger]),
    )
    monkeypatch.setattr(
        document_distribution,
        "_read_linked_document_match_source",
        AsyncMock(return_value=SimpleNamespace(snapshot=())),
    )
    monkeypatch.setattr(
        document_distribution,
        "_linked_document_match_identifiers",
        AsyncMock(return_value=()),
    )
    monkeypatch.setattr(
        document_distribution,
        "read_bounded_document_uploads",
        AsyncMock(
            return_value=[
                SimpleNamespace(
                    filename="unknown.pdf",
                    content=b"%PDF",
                    content_type="application/pdf",
                )
            ]
        ),
    )
    monkeypatch.setattr(
        document_distribution.DocumentMatcher,
        "build_index",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )

    def unsupported(*_args: object, **_kwargs: object) -> object:
        raise UnsupportedDocumentBatchFormatError("Unsupported common document format")

    monkeypatch.setattr(document_distribution, "classify_documents_bounded", unsupported)
    stage = AsyncMock()
    monkeypatch.setattr(document_distribution, "stage_verified_documents", stage)

    with pytest.raises(HTTPException) as exc_info:
        await document_distribution.verify_documents(
            group_id=group_id,
            document_type="visa",
            files=[],
            current_user=user,
            session=session,
        )

    assert exc_info.value.status_code == 422
    stage.assert_not_awaited()


@pytest.mark.asyncio
async def test_verify_rejects_partial_receipt_session_before_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorize = AsyncMock()
    monkeypatch.setattr(document_distribution, "_get_authorized_group", authorize)

    with pytest.raises(HTTPException) as exc_info:
        await document_distribution.verify_documents(
            group_id=uuid.uuid4(),
            document_type="visa",
            files=[],
            upload_id=uuid.uuid4(),
            chunk_id=None,
            current_user=SimpleNamespace(id=uuid.uuid4()),
            session=MagicMock(),
        )

    assert exc_info.value.status_code == 400
    authorize.assert_not_awaited()


@pytest.mark.asyncio
async def test_verify_binds_staging_receipt_to_exact_upload_and_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_id, agency_id, user_id, passenger_id, upload_id, chunk_id = (
        uuid.uuid4() for _index in range(6)
    )
    user = SimpleNamespace(id=user_id, agency_id=agency_id, role=UserRole.AGENCY_ADMIN)
    group = SimpleNamespace(id=group_id, agency_id=agency_id)
    passenger = SimpleNamespace(
        id=passenger_id,
        updated_at=None,
        client_name="Passenger",
        client_phone=None,
        family_head_phone=None,
        confirmed_fields={},
        extracted_fields={},
        staff_metadata={},
        custom_answers=[],
        custom_detail_answers=[],
    )
    upload = SimpleNamespace(
        filename="verified.pdf",
        content=b"%PDF",
        content_type="application/pdf",
    )
    session = MagicMock(rollback=AsyncMock())
    monkeypatch.setattr(
        document_distribution, "_get_authorized_group", AsyncMock(return_value=group)
    )
    monkeypatch.setattr(
        document_distribution, "_group_passengers", AsyncMock(return_value=[passenger])
    )
    monkeypatch.setattr(
        document_distribution,
        "_read_linked_document_match_source",
        AsyncMock(return_value=SimpleNamespace(snapshot=())),
    )
    monkeypatch.setattr(
        document_distribution,
        "_linked_document_match_identifiers",
        AsyncMock(return_value=()),
    )
    monkeypatch.setattr(
        document_distribution,
        "read_bounded_document_uploads",
        AsyncMock(return_value=[upload]),
    )
    monkeypatch.setattr(
        document_distribution.DocumentMatcher,
        "build_index",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        document_distribution.DocumentMatcher,
        "match_all",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        document_distribution,
        "classify_documents_bounded",
        lambda *_args, **_kwargs: [_classification()],
    )
    stage = AsyncMock(return_value=["opaque-receipt"])
    monkeypatch.setattr(document_distribution, "stage_verified_documents", stage)

    result = await document_distribution.verify_documents(
        group_id=group_id,
        document_type="visa",
        files=[],
        upload_id=upload_id,
        chunk_id=chunk_id,
        current_user=user,
        session=session,
    )

    assert result.files[0].staging_receipt == "opaque-receipt"
    assert stage.await_args.kwargs["upload_id"] == upload_id
    assert stage.await_args.kwargs["chunk_id"] == chunk_id


@pytest.mark.asyncio
async def test_upload_accepts_receipts_without_resending_pdf_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _arrange_upload_route(monkeypatch)
    receipt = _staged_receipt(
        agency_id=context.agency_id,
        actor_id=context.user.id,
        group_id=context.group_id,
        upload_id=context.upload_id,
        chunk_id=context.chunk_id,
    )
    decode = MagicMock(return_value=[receipt])
    monkeypatch.setattr(document_distribution, "decode_verification_receipts", decode)

    result = await _upload(context, staging_receipts=["opaque-receipt"])

    assert result is context.response
    decode.assert_called_once()
    assert decode.call_args.kwargs["upload_id"] == context.upload_id
    assert decode.call_args.kwargs["chunk_id"] == context.chunk_id
    ingest_kwargs = context.ingest.await_args.kwargs
    assert ingest_kwargs["preclassified_documents"] == [receipt.classification]
    assert ingest_kwargs["staged_storage_keys"] == [receipt.storage_key]
    assert len(ingest_kwargs["files"]) == 1
    assert ingest_kwargs["files"][0].content == b""
    context.cleanup.assert_awaited_once_with([receipt.storage_key])


@pytest.mark.asyncio
async def test_upload_rejects_mixed_pdf_and_receipt_before_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorize = AsyncMock()
    monkeypatch.setattr(document_distribution, "_get_authorized_group", authorize)

    with pytest.raises(HTTPException) as exc_info:
        await document_distribution.upload_documents(
            group_id=uuid.uuid4(),
            document_type="visa",
            files=[object()],
            staging_receipts=["opaque-receipt"],
            upload_id=None,
            chunk_id=None,
            chunk_index=None,
            expected_chunk_count=None,
            expected_file_count=None,
            current_user=SimpleNamespace(id=uuid.uuid4()),
            session=MagicMock(),
        )

    assert exc_info.value.status_code == 400
    authorize.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_type", "expected_status"),
    [
        (VerificationReceiptExpiredError, 410),
        (VerificationReceiptScopeChangedError, 409),
    ],
)
async def test_upload_cleans_scoped_staging_after_expiry_or_scope_change(
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[VerificationReceiptExpiredError | VerificationReceiptScopeChangedError],
    expected_status: int,
) -> None:
    context = _arrange_upload_route(monkeypatch)
    owned_key = (
        f"document-verification-staging/{context.agency_id}/{context.user.id}/{uuid.uuid4()}.pdf"
    )
    monkeypatch.setattr(
        document_distribution,
        "decode_verification_receipts",
        MagicMock(side_effect=error_type("Receipt cannot be finalized", storage_keys=(owned_key,))),
    )

    with pytest.raises(HTTPException) as exc_info:
        await _upload(context, staging_receipts=["opaque-receipt"])

    assert exc_info.value.status_code == expected_status
    context.cleanup.assert_awaited_once_with([owned_key])
    context.ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_guard_preserves_decoded_staging_on_transient_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _arrange_upload_route(monkeypatch)
    receipt = _staged_receipt(
        agency_id=context.agency_id,
        actor_id=context.user.id,
        group_id=context.group_id,
        upload_id=context.upload_id,
        chunk_id=context.chunk_id,
    )
    monkeypatch.setattr(
        document_distribution,
        "decode_verification_receipts",
        MagicMock(return_value=[receipt]),
    )
    monkeypatch.setattr(
        document_distribution,
        "get_settings",
        MagicMock(side_effect=RuntimeError("settings unavailable")),
    )

    with pytest.raises(RuntimeError, match="settings unavailable"):
        await _upload(context, staging_receipts=["opaque-receipt"])

    context.cleanup.assert_not_awaited()
    context.ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_guard_preserves_staging_on_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup = AsyncMock()
    monkeypatch.setattr(document_distribution, "cleanup_staged_storage_keys", cleanup)
    storage_key = f"document-verification-staging/{uuid.uuid4()}/object.pdf"

    @document_distribution._with_staging_cleanup
    async def cancelled_handler() -> None:
        document_distribution._remember_request_staging_keys([storage_key])
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await cancelled_handler()

    cleanup.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_guard_cleans_staging_on_terminal_client_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup = AsyncMock()
    monkeypatch.setattr(document_distribution, "cleanup_staged_storage_keys", cleanup)
    storage_key = f"document-verification-staging/{uuid.uuid4()}/object.pdf"

    @document_distribution._with_staging_cleanup
    async def rejected_handler() -> None:
        document_distribution._remember_request_staging_keys([storage_key])
        raise HTTPException(status_code=422, detail="Rejected")

    with pytest.raises(HTTPException) as exc_info:
        await rejected_handler()

    assert exc_info.value.status_code == 422
    cleanup.assert_awaited_once_with([storage_key])


@pytest.mark.asyncio
async def test_upload_guard_preserves_staging_on_retryable_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup = AsyncMock()
    monkeypatch.setattr(document_distribution, "cleanup_staged_storage_keys", cleanup)
    storage_key = f"document-verification-staging/{uuid.uuid4()}/object.pdf"

    @document_distribution._with_staging_cleanup
    async def conflicting_handler() -> None:
        document_distribution._remember_request_staging_keys([storage_key])
        raise HTTPException(status_code=409, detail="Prior chunk is still committing")

    with pytest.raises(HTTPException) as exc_info:
        await conflicting_handler()

    assert exc_info.value.status_code == 409
    cleanup.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_rejects_51_receipts_before_decode_or_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decode = MagicMock()
    authorize = AsyncMock()
    monkeypatch.setattr(document_distribution, "decode_verification_receipts", decode)
    monkeypatch.setattr(document_distribution, "_get_authorized_group", authorize)

    with pytest.raises(HTTPException) as exc_info:
        await document_distribution.upload_documents(
            group_id=uuid.uuid4(),
            document_type="visa",
            files=None,
            staging_receipts=[f"receipt-{index}" for index in range(51)],
            upload_id=None,
            chunk_id=None,
            chunk_index=None,
            expected_chunk_count=None,
            expected_file_count=None,
            current_user=SimpleNamespace(id=uuid.uuid4()),
            session=MagicMock(),
        )

    assert exc_info.value.status_code == 413
    decode.assert_not_called()
    authorize.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_rejects_aggregate_receipt_bytes_before_decrypt_or_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decode = MagicMock()
    authorize = AsyncMock()
    monkeypatch.setattr(document_distribution, "decode_verification_receipts", decode)
    monkeypatch.setattr(document_distribution, "_get_authorized_group", authorize)
    monkeypatch.setattr(
        document_distribution,
        "validate_verification_receipt_token_batch",
        MagicMock(
            side_effect=document_distribution.VerificationReceiptBatchTooLargeError(
                "The document verification receipts are too large"
            )
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await document_distribution.upload_documents(
            group_id=uuid.uuid4(),
            document_type="visa",
            files=None,
            staging_receipts=["opaque-receipt"],
            upload_id=uuid.uuid4(),
            chunk_id=uuid.uuid4(),
            chunk_index=0,
            expected_chunk_count=1,
            expected_file_count=1,
            current_user=SimpleNamespace(id=uuid.uuid4()),
            session=MagicMock(),
        )

    assert exc_info.value.status_code == 413
    decode.assert_not_called()
    authorize.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_legacy_files_only_path_remains_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _arrange_upload_route(monkeypatch)
    read_uploads = AsyncMock(
        return_value=[
            SimpleNamespace(
                filename="legacy.pdf",
                content=b"%PDF legacy",
                content_type="application/pdf",
            )
        ]
    )
    decode = MagicMock()
    monkeypatch.setattr(document_distribution, "read_bounded_document_uploads", read_uploads)
    monkeypatch.setattr(document_distribution, "decode_verification_receipts", decode)

    result = await _upload(context, files=[object()])

    assert result is context.response
    read_uploads.assert_awaited_once()
    decode.assert_not_called()
    ingest_kwargs = context.ingest.await_args.kwargs
    assert ingest_kwargs["preclassified_documents"] is None
    assert ingest_kwargs["staged_storage_keys"] is None
    assert ingest_kwargs["files"][0].content == b"%PDF legacy"
    context.cleanup.assert_not_awaited()
