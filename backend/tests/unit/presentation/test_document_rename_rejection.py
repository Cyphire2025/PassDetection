from __future__ import annotations

import uuid
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from fastapi import HTTPException, UploadFile

from app.domain.entities.entities import UserRole
from app.infrastructure.documents.document_matcher import (
    ClassifiedDocument,
    DocumentMatcher,
    DocumentParserUnavailableError,
)
from app.presentation.api.v1.routes.document_rename import (
    _lock_active_rename_actor,
    analyze_and_rename_documents,
    delete_rename_batches,
    download_renamed_document,
    download_renamed_zip,
)
from app.presentation.api.v1.schemas.document_rename_schemas import (
    DeleteRenameBatchesRequest,
)


def _user() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        role=UserRole.AGENCY_ADMIN,
        email="staff@example.test",
    )


async def test_parser_capacity_failure_returns_retryable_503_without_writes() -> None:
    user = _user()
    session = MagicMock()
    session.add = MagicMock()
    session.rollback = AsyncMock()
    storage = MagicMock()
    storage.upload_file = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.document_rename.classify_documents_bounded",
            side_effect=DocumentParserUnavailableError(
                "PDF verification is temporarily busy; retry the upload"
            ),
        ),
        patch(
            "app.presentation.api.v1.routes.document_rename.MinioStorageRepository",
            return_value=storage,
        ),
        pytest.raises(HTTPException) as error,
    ):
        await analyze_and_rename_documents(
            files=[
                UploadFile(
                    file=BytesIO(b"%PDF-1.7"),
                    filename="visa.pdf",
                    size=8,
                )
            ],
            title="Retry batch",
            current_user=user,
            session=session,
        )

    assert error.value.status_code == 503
    assert error.value.headers == {"Retry-After": "1"}
    session.add.assert_not_called()
    storage.upload_file.assert_not_awaited()


async def test_unverified_rename_pdf_is_rejected_without_storage_or_download() -> None:
    user = _user()
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    matcher = MagicMock()
    matcher.classify.return_value = ClassifiedDocument(
        original_filename="visa-invoice.pdf",
        detected_type="unknown",
        accepted=True,
        reason="Accepted",
        text="Payment receipt",
        extracted_name="Asha Mehta",
        extracted_passport_number="P1234567",
        extracted_reference=None,
    )
    storage = MagicMock()
    storage.upload_file = AsyncMock()
    storage.delete_files = AsyncMock(return_value=0)
    audit = MagicMock()
    audit.record = AsyncMock()
    content = b"%PDF-1.7 unrelated"

    with (
        patch(
            "app.presentation.api.v1.routes.document_rename.DocumentMatcher",
            return_value=matcher,
        ),
        patch(
            "app.presentation.api.v1.routes.document_rename.MinioStorageRepository",
            return_value=storage,
        ),
        patch(
            "app.presentation.api.v1.routes.document_rename.AuditLogRepository",
            return_value=audit,
        ),
        patch(
            "app.presentation.api.v1.routes.document_rename._lock_active_rename_actor",
            new=AsyncMock(return_value=user),
        ),
    ):
        response = await analyze_and_rename_documents(
            files=[
                UploadFile(
                    file=BytesIO(content),
                    filename="visa-invoice.pdf",
                    size=len(content),
                )
            ],
            title="Strict batch",
            current_user=user,
            session=session,
        )

    storage.upload_file.assert_not_awaited()
    session.commit.assert_awaited_once()
    assert response.unknown_count == 1
    assert response.items[0].status == "rejected"
    assert response.items[0].renamed_filename == "visa-invoice.pdf"
    assert response.items[0].download_url == ""
    assert response.items[0].extracted_name is None
    assert response.items[0].extracted_passport_number is None
    assert response.items[0].extracted_reference is None


async def test_blank_visa_form_is_rejected_by_real_classifier_without_storage(
    monkeypatch,
) -> None:
    user = _user()
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    matcher = DocumentMatcher()
    monkeypatch.setattr(
        matcher,
        "_pdf_text",
        lambda _content: (
            "VISA APPLICATION FORM Visa number: Visa type: Date of issue: Date of expiry:"
        ),
    )
    storage = MagicMock()
    storage.upload_file = AsyncMock()
    storage.delete_files = AsyncMock(return_value=0)
    audit = MagicMock()
    audit.record = AsyncMock()
    content = b"%PDF-1.7 blank form"

    with (
        patch(
            "app.presentation.api.v1.routes.document_rename.DocumentMatcher",
            return_value=matcher,
        ),
        patch(
            "app.presentation.api.v1.routes.document_rename.MinioStorageRepository",
            return_value=storage,
        ),
        patch(
            "app.presentation.api.v1.routes.document_rename.AuditLogRepository",
            return_value=audit,
        ),
        patch(
            "app.presentation.api.v1.routes.document_rename._lock_active_rename_actor",
            new=AsyncMock(return_value=user),
        ),
    ):
        response = await analyze_and_rename_documents(
            files=[UploadFile(file=BytesIO(content), filename="form.pdf", size=len(content))],
            title="Strict batch",
            current_user=user,
            session=session,
        )

    storage.upload_file.assert_not_awaited()
    assert response.items[0].status == "rejected"
    assert response.items[0].extracted_name is None
    assert response.items[0].extracted_passport_number is None


async def test_supported_rename_pdf_is_stored_and_remains_downloadable() -> None:
    user = _user()
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    matcher = MagicMock()
    matcher.classify.return_value = ClassifiedDocument(
        original_filename="visa.pdf",
        detected_type="visa",
        accepted=True,
        reason="Accepted",
        text="Electronic visa",
        extracted_name="Asha Mehta",
        extracted_passport_number="P1234567",
        extracted_reference=None,
    )
    storage = MagicMock()
    storage.upload_file = AsyncMock()
    storage.delete_files = AsyncMock(return_value=0)
    audit = MagicMock()
    audit.record = AsyncMock()
    content = b"%PDF-1.7 visa"

    with (
        patch(
            "app.presentation.api.v1.routes.document_rename.DocumentMatcher",
            return_value=matcher,
        ),
        patch(
            "app.presentation.api.v1.routes.document_rename.MinioStorageRepository",
            return_value=storage,
        ),
        patch(
            "app.presentation.api.v1.routes.document_rename.AuditLogRepository",
            return_value=audit,
        ),
        patch(
            "app.presentation.api.v1.routes.document_rename._lock_active_rename_actor",
            new=AsyncMock(return_value=user),
        ),
    ):
        response = await analyze_and_rename_documents(
            files=[UploadFile(file=BytesIO(content), filename="visa.pdf", size=len(content))],
            title="Visa batch",
            current_user=user,
            session=session,
        )

    storage.upload_file.assert_awaited_once()
    assert response.visa_count == 1
    assert response.items[0].status == "renamed"
    assert response.items[0].renamed_filename == "ASHA_MEHTA_VISA.pdf"
    assert response.items[0].download_url.endswith("/download")


async def test_rename_commit_failure_keeps_uploaded_object_for_reconciliation() -> None:
    user = _user()
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock(side_effect=RuntimeError("commit acknowledgement lost"))
    session.rollback = AsyncMock()
    matcher = MagicMock()
    matcher.classify.return_value = ClassifiedDocument(
        original_filename="visa.pdf",
        detected_type="visa",
        accepted=True,
        reason="Accepted",
        text="Electronic visa",
        extracted_name="Asha Mehta",
        extracted_passport_number="P1234567",
        extracted_reference=None,
    )
    storage = MagicMock()
    storage.upload_file = AsyncMock()
    storage.delete_files = AsyncMock(return_value=0)
    audit = MagicMock()
    audit.record = AsyncMock()
    content = b"%PDF-1.7 visa"

    with (
        patch(
            "app.presentation.api.v1.routes.document_rename.DocumentMatcher",
            return_value=matcher,
        ),
        patch(
            "app.presentation.api.v1.routes.document_rename.MinioStorageRepository",
            return_value=storage,
        ),
        patch(
            "app.presentation.api.v1.routes.document_rename.AuditLogRepository",
            return_value=audit,
        ),
        patch(
            "app.presentation.api.v1.routes.document_rename._lock_active_rename_actor",
            new=AsyncMock(return_value=user),
        ),
        pytest.raises(RuntimeError, match="acknowledgement lost"),
    ):
        await analyze_and_rename_documents(
            files=[UploadFile(file=BytesIO(content), filename="visa.pdf", size=len(content))],
            title="Visa batch",
            current_user=user,
            session=session,
        )

    storage.upload_file.assert_awaited_once()
    storage.delete_files.assert_not_awaited()
    assert session.rollback.await_count == 2


async def test_rename_releases_auth_transaction_and_reauthorizes_before_staging() -> None:
    user = _user()
    events: list[str] = []
    session = MagicMock()
    session.add = MagicMock(side_effect=lambda _row: events.append("db-stage"))
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock(side_effect=lambda: events.append("rollback"))
    matcher = MagicMock()
    matcher.classify.return_value = ClassifiedDocument(
        original_filename="visa.pdf",
        detected_type="visa",
        accepted=True,
        reason="Accepted",
        text="Electronic visa",
        extracted_name="Asha Mehta",
        extracted_passport_number="P1234567",
        extracted_reference=None,
    )
    storage = MagicMock()
    storage.upload_file = AsyncMock(side_effect=lambda *_args: events.append("upload"))
    storage.delete_files = AsyncMock(return_value=0)
    audit = MagicMock()
    audit.record = AsyncMock()

    async def reauthorize(*_args, **_kwargs):
        events.append("reauthorize")
        return user

    with (
        patch(
            "app.presentation.api.v1.routes.document_rename.DocumentMatcher",
            return_value=matcher,
        ),
        patch(
            "app.presentation.api.v1.routes.document_rename.MinioStorageRepository",
            return_value=storage,
        ),
        patch(
            "app.presentation.api.v1.routes.document_rename.AuditLogRepository",
            return_value=audit,
        ),
        patch(
            "app.presentation.api.v1.routes.document_rename._lock_active_rename_actor",
            new=AsyncMock(side_effect=reauthorize),
        ),
    ):
        await analyze_and_rename_documents(
            files=[
                UploadFile(
                    file=BytesIO(b"%PDF-1.7 visa"),
                    filename="visa.pdf",
                    size=13,
                )
            ],
            title="Visa batch",
            current_user=user,
            session=session,
        )

    assert events.index("rollback") < events.index("upload")
    assert events.index("upload") < events.index("reauthorize")
    assert events.index("reauthorize") < events.index("db-stage")


async def test_rename_reauthorization_failure_removes_new_uploads() -> None:
    user = _user()
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    matcher = MagicMock()
    matcher.classify.return_value = ClassifiedDocument(
        original_filename="visa.pdf",
        detected_type="visa",
        accepted=True,
        reason="Accepted",
        text="Electronic visa",
        extracted_name="Asha Mehta",
        extracted_passport_number="P1234567",
        extracted_reference=None,
    )
    storage = MagicMock()
    storage.upload_file = AsyncMock()
    storage.delete_files = AsyncMock(return_value=1)

    with (
        patch(
            "app.presentation.api.v1.routes.document_rename.DocumentMatcher",
            return_value=matcher,
        ),
        patch(
            "app.presentation.api.v1.routes.document_rename.MinioStorageRepository",
            return_value=storage,
        ),
        patch(
            "app.presentation.api.v1.routes.document_rename._lock_active_rename_actor",
            new=AsyncMock(
                side_effect=HTTPException(status_code=403, detail="authorization changed")
            ),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await analyze_and_rename_documents(
            files=[
                UploadFile(
                    file=BytesIO(b"%PDF-1.7 visa"),
                    filename="visa.pdf",
                    size=13,
                )
            ],
            title="Visa batch",
            current_user=user,
            session=session,
        )

    assert exc_info.value.status_code == 403
    storage.upload_file.assert_awaited_once()
    storage.delete_files.assert_awaited_once()
    assert len(storage.delete_files.await_args.args[0]) == 1
    session.add.assert_not_called()


async def test_rename_ambiguous_upload_failure_cleans_preclaimed_key() -> None:
    user = _user()
    session = MagicMock()
    session.add = MagicMock()
    session.rollback = AsyncMock()
    matcher = MagicMock()
    matcher.classify.return_value = ClassifiedDocument(
        original_filename="visa.pdf",
        detected_type="visa",
        accepted=True,
        reason="Accepted",
        text="Electronic visa",
        extracted_name="Asha Mehta",
        extracted_passport_number="P1234567",
        extracted_reference=None,
    )
    storage = MagicMock()
    storage.upload_file = AsyncMock(side_effect=RuntimeError("upload acknowledgement lost"))
    storage.delete_files = AsyncMock(return_value=1)

    with (
        patch(
            "app.presentation.api.v1.routes.document_rename.DocumentMatcher",
            return_value=matcher,
        ),
        patch(
            "app.presentation.api.v1.routes.document_rename.MinioStorageRepository",
            return_value=storage,
        ),
        pytest.raises(RuntimeError, match="acknowledgement lost"),
    ):
        await analyze_and_rename_documents(
            files=[
                UploadFile(
                    file=BytesIO(b"%PDF-1.7 visa"),
                    filename="visa.pdf",
                    size=13,
                )
            ],
            title="Visa batch",
            current_user=user,
            session=session,
        )

    storage.delete_files.assert_awaited_once()
    assert len(storage.delete_files.await_args.args[0]) == 1
    session.add.assert_not_called()


async def test_rename_actor_reauthorization_locks_active_user_and_agency() -> None:
    user = _user()
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    actor = await _lock_active_rename_actor(
        session,
        user_id=user.id,
        agency_id=user.agency_id,
    )

    assert actor is user
    statement = session.execute.await_args.args[0]
    rendered = str(statement)
    assert "JOIN agencies" in rendered
    assert "users.is_active IS true" in rendered
    assert "agencies.is_active IS true" in rendered
    assert "FOR UPDATE" in rendered
    assert statement.get_execution_options()["populate_existing"] is True


async def test_rename_bulk_delete_does_not_touch_storage_when_commit_fails() -> None:
    user = _user()
    batch_id = uuid.uuid4()
    batch = SimpleNamespace(id=batch_id)
    item = SimpleNamespace(storage_key="document-rename/batch/visa.pdf")
    batch_result = MagicMock()
    batch_result.scalars.return_value.all.return_value = [batch]
    item_result = MagicMock()
    item_result.scalars.return_value.all.return_value = [item]
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[batch_result, item_result])
    session.delete = AsyncMock()
    session.commit = AsyncMock(side_effect=RuntimeError("commit failed"))
    storage = MagicMock()
    storage.delete_files = AsyncMock(return_value=1)
    audit = MagicMock()
    audit.record = AsyncMock()
    process_cleanup = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.document_rename.MinioStorageRepository",
            return_value=storage,
        ),
        patch(
            "app.presentation.api.v1.routes.document_rename.AuditLogRepository",
            return_value=audit,
        ),
        patch(
            "app.presentation.api.v1.routes.document_rename.process_storage_cleanup_job",
            new=process_cleanup,
        ),
        pytest.raises(RuntimeError, match="commit failed"),
    ):
        await delete_rename_batches(
            payload=DeleteRenameBatchesRequest(batch_ids=[batch_id]),
            current_user=user,
            session=session,
        )

    storage.delete_files.assert_not_awaited()
    process_cleanup.assert_not_awaited()
    batch_statement = session.execute.await_args_list[0].args[0]
    item_statement = session.execute.await_args_list[1].args[0]
    assert "ORDER BY document_rename_batches.id" in str(batch_statement)
    assert "FOR UPDATE" in str(batch_statement)
    assert "ORDER BY document_rename_items.id" in str(item_statement)
    assert "FOR UPDATE" in str(item_statement)


async def test_rename_bulk_delete_processes_every_job_and_defers_runner_failure() -> None:
    user = _user()
    batch_id = uuid.uuid4()
    cleanup_job_ids = [uuid.uuid4(), uuid.uuid4()]
    batch = SimpleNamespace(id=batch_id)
    item = SimpleNamespace(storage_key="document-rename/batch/visa.pdf")
    batch_result = MagicMock()
    batch_result.scalars.return_value.all.return_value = [batch]
    item_result = MagicMock()
    item_result.scalars.return_value.all.return_value = [item]
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[batch_result, item_result])
    session.delete = AsyncMock()
    session.commit = AsyncMock()
    audit = MagicMock()
    audit.record = AsyncMock()
    process_cleanup = AsyncMock(
        side_effect=[
            RuntimeError("cleanup database unavailable"),
            SimpleNamespace(completed=True, deleted_count=1),
        ]
    )

    with (
        patch(
            "app.presentation.api.v1.routes.document_rename.AuditLogRepository",
            return_value=audit,
        ),
        patch(
            "app.presentation.api.v1.routes.document_rename.stage_storage_cleanup_jobs",
            return_value=tuple(
                SimpleNamespace(id=job_id, object_count=1) for job_id in cleanup_job_ids
            ),
        ),
        patch(
            "app.presentation.api.v1.routes.document_rename.process_storage_cleanup_job",
            new=process_cleanup,
        ),
    ):
        response = await delete_rename_batches(
            payload=DeleteRenameBatchesRequest(batch_ids=[batch_id]),
            current_user=user,
            session=session,
        )

    assert response.deleted_count == 1
    assert response.deleted_storage_objects == 1
    session.commit.assert_awaited_once()
    assert process_cleanup.await_args_list == [
        call(cleanup_job_ids[0]),
        call(cleanup_job_ids[1]),
    ]


async def test_rename_zip_skips_rejected_rows_even_if_repository_returns_one() -> None:
    user = _user()
    batch = SimpleNamespace(id=uuid.uuid4())
    accepted = SimpleNamespace(
        id=uuid.uuid4(),
        detected_type="visa",
        status="renamed",
        storage_key="accepted-key",
        renamed_filename="ASHA_VISA.pdf",
        created_at=datetime.now(tz=UTC),
    )
    rejected = SimpleNamespace(
        id=uuid.uuid4(),
        detected_type="unknown",
        status="rejected",
        storage_key="",
        renamed_filename="invoice.pdf",
        created_at=datetime.now(tz=UTC),
    )
    batch_result = MagicMock()
    batch_result.scalar_one_or_none.return_value = batch
    items_result = MagicMock()
    items_result.scalars.return_value.all.return_value = [accepted, rejected]
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[batch_result, items_result])
    session.rollback = AsyncMock()
    storage = MagicMock()
    storage.get_file = AsyncMock(return_value=b"%PDF accepted")

    with patch(
        "app.presentation.api.v1.routes.document_rename.MinioStorageRepository",
        return_value=storage,
    ):
        response = await download_renamed_zip(
            batch_id=batch.id,
            current_user=user,
            session=session,
        )
        body = b"".join([chunk async for chunk in response.body_iterator])

    storage.get_file.assert_awaited_once_with("accepted-key")
    session.rollback.assert_awaited_once()
    assert response.media_type == "application/zip"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("attachment;")
    with zipfile.ZipFile(BytesIO(body)) as archive:
        assert archive.namelist() == ["ASHA_VISA.pdf"]


async def test_all_rejected_rename_batch_has_no_zip_download() -> None:
    user = _user()
    batch = SimpleNamespace(id=uuid.uuid4())
    batch_result = MagicMock()
    batch_result.scalar_one_or_none.return_value = batch
    items_result = MagicMock()
    items_result.scalars.return_value.all.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[batch_result, items_result])
    session.rollback = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await download_renamed_zip(
            batch_id=batch.id,
            current_user=user,
            session=session,
        )

    assert exc_info.value.status_code == 404
    assert "no verified" in str(exc_info.value.detail).lower()
    session.rollback.assert_awaited_once()


async def test_foreign_or_other_staff_rename_item_returns_404_without_storage_access() -> None:
    user = _user()
    user.role = UserRole.AGENCY_STAFF
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    storage = MagicMock()
    storage.get_file = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.document_rename.MinioStorageRepository",
            return_value=storage,
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await download_renamed_document(
            item_id=uuid.uuid4(),
            current_user=user,
            session=session,
        )

    assert exc_info.value.status_code == 404
    storage.get_file.assert_not_awaited()
    rendered = str(session.execute.await_args.args[0])
    assert "document_rename_items.agency_id" in rendered
    assert "document_rename_batches.agency_id" in rendered
    assert "document_rename_batches.created_by_user_id" in rendered


async def test_renamed_document_download_forces_safe_pdf_headers() -> None:
    user = _user()
    item = SimpleNamespace(
        storage_key="document-rename/batch/visa.pdf",
        renamed_filename="ASHA_VISA.pdf",
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = item
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.rollback = AsyncMock()
    storage = MagicMock()
    storage.get_file = AsyncMock(return_value=b"%PDF safe")

    with patch(
        "app.presentation.api.v1.routes.document_rename.MinioStorageRepository",
        return_value=storage,
    ):
        response = await download_renamed_document(
            item_id=uuid.uuid4(),
            current_user=user,
            session=session,
        )

    assert response.media_type == "application/pdf"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["cache-control"] == "private, no-store"
    session.rollback.assert_awaited_once()
