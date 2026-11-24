"""Pre-commit private objects are cleaned even if rollback itself is interrupted."""

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.domain.entities.entities import UserRole
from app.infrastructure.documents.document_matcher import ClassifiedDocument
from app.presentation.api.v1.document_uploads import BoundedDocumentUpload
from app.presentation.api.v1.routes import document_rename, document_rename_cleanup


@pytest.mark.parametrize("rollback_error", [None, RuntimeError, asyncio.CancelledError])
async def test_precommit_actor_rejection_cleans_owned_upload_despite_rollback_failure(
    monkeypatch, rollback_error
):
    objects = {}
    uploaded = []
    deleted = []

    async def upload(content, key, _content_type):
        objects[key] = content
        uploaded.append(key)

    async def delete(keys):
        for key in keys:
            objects.pop(key, None)
            deleted.append(key)
        return len(keys)

    storage = SimpleNamespace(
        upload_file=AsyncMock(side_effect=upload), delete_files=AsyncMock(side_effect=delete)
    )
    session = MagicMock()
    session.rollback = AsyncMock(
        side_effect=[
            None,
            rollback_error("Synthetic rollback interrupted") if rollback_error else None,
        ]
    )
    session.commit = AsyncMock()
    monkeypatch.setattr(
        document_rename,
        "read_bounded_document_uploads",
        AsyncMock(
            return_value=[
                BoundedDocumentUpload(
                    "synthetic.pdf", b"%PDF synthetic private document", "application/pdf"
                )
            ]
        ),
    )
    monkeypatch.setattr(
        document_rename,
        "classify_documents_bounded",
        lambda *_args, **_kwargs: [
            ClassifiedDocument(
                original_filename="synthetic.pdf",
                detected_type="visa",
                extracted_name="Synthetic Passenger",
                accepted=True,
                reason="Synthetic visa fixture",
                text="Synthetic bounded text",
                extracted_passport_number=None,
                extracted_reference=None,
            )
        ],
    )
    monkeypatch.setattr(document_rename, "MinioStorageRepository", lambda: storage)
    monkeypatch.setattr(
        document_rename,
        "_lock_active_rename_actor",
        AsyncMock(side_effect=HTTPException(status_code=403, detail="Synthetic actor revoked")),
    )
    user = SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4(), role=UserRole.AGENCY_ADMIN)
    expected = rollback_error or HTTPException
    with pytest.raises(expected):
        await document_rename.analyze_and_rename_documents(
            files=[MagicMock()], title="Synthetic batch", current_user=user, session=session
        )
    assert len(uploaded) == 1 and len(deleted) == 1
    assert deleted == uploaded and objects == {}
    session.commit.assert_not_awaited()
    session.add.assert_not_called()


@pytest.mark.parametrize("tracking_fails", [False, True])
async def test_failed_owned_cleanup_tracks_keys_durably_without_logging_private_details(
    monkeypatch, caplog, tracking_fails
):
    agency_id, batch_id = uuid.uuid4(), uuid.uuid4()
    private_key = "document-rename/private-passenger-storage-key.pdf"
    storage = SimpleNamespace(delete_files=AsyncMock(side_effect=RuntimeError(private_key)))
    persist = AsyncMock(side_effect=RuntimeError(private_key) if tracking_fails else None)
    monkeypatch.setattr(document_rename_cleanup, "persist_storage_cleanup_job", persist)
    await document_rename._cleanup_owned_rename_storage(
        storage, [private_key], agency_id=agency_id, batch_id=batch_id
    )
    persist.assert_awaited_once_with(
        agency_id=agency_id,
        source="document_rename_compensation",
        context_id=str(batch_id),
        storage_keys=[private_key],
    )
    assert private_key not in caplog.text
    assert "document_rename_storage_cleanup_deferred" in caplog.text
    assert ("document_rename_cleanup_tracking_failed" in caplog.text) is tracking_fails
