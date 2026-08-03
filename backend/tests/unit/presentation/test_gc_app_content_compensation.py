from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.presentation.api.v1.routes.gc_app_content import (
    _store_common_document_version,
    delete_common_document,
    preview_common_document_content,
)


def _access(*, revision: int, access_id: uuid.UUID | None = None, offset: int = 0):
    now = datetime.now(tz=UTC)
    return SimpleNamespace(
        id=access_id or uuid.uuid4(),
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        revision=revision,
        access_starts_at=now + timedelta(hours=offset),
        access_expires_at=now + timedelta(days=10, hours=offset),
        updated_by_user_id=None,
        updated_at=None,
    )


def _scope_pair(*, revision: int = 4):
    initial = _access(revision=revision)
    locked = _access(revision=revision, access_id=initial.id, offset=2)
    locked.agency_id = initial.agency_id
    locked.group_id = initial.group_id
    group = SimpleNamespace(status="active")
    return initial, locked, group


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []})


def _validated_pdf():
    return SimpleNamespace(
        content=b"%PDF-1.7\nvalidated",
        content_type="application/pdf",
        filename="travel-tips.pdf",
        sha256_hex="a" * 64,
    )


@pytest.mark.asyncio
async def test_draft_delete_commits_before_object_cleanup() -> None:
    access, _locked, group = _scope_pair()
    current_user = SimpleNamespace(id=uuid.uuid4())
    document_id = uuid.uuid4()
    document = SimpleNamespace(status="draft", storage_key="private/draft.pdf")
    events: list[str] = []
    session = MagicMock()
    session.delete = AsyncMock(side_effect=lambda *_args: events.append("row-delete"))
    session.flush = AsyncMock(side_effect=lambda: events.append("flush"))
    session.commit = AsyncMock(side_effect=lambda: events.append("commit"))
    storage = MagicMock()
    storage.delete_files = AsyncMock(side_effect=lambda *_args: events.append("object-delete"))

    with (
        patch(
            "app.presentation.api.v1.routes.gc_app_content._admin_access_context",
            new=AsyncMock(return_value=(access, group)),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content._get_common_document",
            new=AsyncMock(return_value=document),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content._content_audit",
            new=AsyncMock(side_effect=lambda *_args, **_kwargs: events.append("audit")),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content.MinioStorageRepository",
            return_value=storage,
        ),
    ):
        response = await delete_common_document(
            access.group_id,
            document_id,
            _request(),
            agency_id=access.agency_id,
            current_user=current_user,
            session=session,
        )

    assert response.status_code == 204
    assert events == ["row-delete", "flush", "audit", "commit", "object-delete"]
    storage.delete_files.assert_awaited_once_with(["private/draft.pdf"])


@pytest.mark.asyncio
async def test_draft_delete_commit_failure_preserves_object() -> None:
    access, _locked, group = _scope_pair()
    document = SimpleNamespace(status="draft", storage_key="private/draft.pdf")
    session = MagicMock()
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock(side_effect=RuntimeError("commit failed"))
    storage = MagicMock()
    storage.delete_files = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.gc_app_content._admin_access_context",
            new=AsyncMock(return_value=(access, group)),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content._get_common_document",
            new=AsyncMock(return_value=document),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content._content_audit",
            new=AsyncMock(),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content.MinioStorageRepository",
            return_value=storage,
        ),
    ):
        with pytest.raises(RuntimeError, match="commit failed"):
            await delete_common_document(
                access.group_id,
                uuid.uuid4(),
                _request(),
                agency_id=access.agency_id,
                current_user=SimpleNamespace(id=uuid.uuid4()),
                session=session,
            )

    storage.delete_files.assert_not_awaited()


@pytest.mark.asyncio
async def test_common_document_preview_streams_without_materializing_full_pdf() -> None:
    access, _locked, group = _scope_pair()
    payload = b"%PDF-1.7\nbody"
    document = SimpleNamespace(
        status="draft",
        storage_key="private/preview.pdf",
        byte_size=len(payload),
        safe_filename="preview.pdf",
        media_type="application/pdf",
    )
    session = MagicMock()
    session.commit = AsyncMock()
    session.close = AsyncMock()
    storage = MagicMock()
    storage.get_file_range = AsyncMock(return_value=payload[:16])
    stream_closed = False

    async def stream_file(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        nonlocal stream_closed
        try:
            yield payload[:5]
            yield payload[5:]
        finally:
            stream_closed = True

    storage.stream_file = stream_file

    with (
        patch(
            "app.presentation.api.v1.routes.gc_app_content._admin_access_context",
            new=AsyncMock(return_value=(access, group)),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content._get_common_document",
            new=AsyncMock(return_value=document),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content.MinioStorageRepository",
            return_value=storage,
        ),
    ):
        response = await preview_common_document_content(
            access.group_id,
            uuid.uuid4(),
            agency_id=access.agency_id,
            current_user=SimpleNamespace(id=uuid.uuid4()),
            session=session,
        )
        rendered = b"".join([chunk async for chunk in response.body_iterator])

    assert rendered == payload
    assert response.headers["content-length"] == str(len(payload))
    storage.get_file_range.assert_awaited_once_with(
        "private/preview.pdf",
        start=0,
        end=len(payload) - 1,
    )
    assert storage.get_file.call_count == 0
    session.commit.assert_awaited_once()
    session.close.assert_awaited_once()
    assert stream_closed is True


@pytest.mark.asyncio
async def test_common_document_preview_cancellation_closes_storage_stream() -> None:
    access, _locked, group = _scope_pair()
    payload = b"%PDF-1.7\nbody"
    document = SimpleNamespace(
        status="draft",
        storage_key="private/cancelled-preview.pdf",
        byte_size=len(payload),
        safe_filename="preview.pdf",
        media_type="application/pdf",
    )
    session = MagicMock()
    session.commit = AsyncMock()
    session.close = AsyncMock()
    storage = MagicMock()
    storage.get_file_range = AsyncMock(return_value=payload[:16])
    stream_closed = False

    async def stream_file(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        nonlocal stream_closed
        try:
            yield payload[:5]
            yield payload[5:]
        finally:
            stream_closed = True

    storage.stream_file = stream_file

    with (
        patch(
            "app.presentation.api.v1.routes.gc_app_content._admin_access_context",
            new=AsyncMock(return_value=(access, group)),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content._get_common_document",
            new=AsyncMock(return_value=document),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content.MinioStorageRepository",
            return_value=storage,
        ),
    ):
        response = await preview_common_document_content(
            access.group_id,
            uuid.uuid4(),
            agency_id=access.agency_id,
            current_user=SimpleNamespace(id=uuid.uuid4()),
            session=session,
        )
        iterator = response.body_iterator
        assert await anext(iterator) == payload[:5]
        await iterator.aclose()

    session.commit.assert_awaited_once()
    session.close.assert_awaited_once()
    assert stream_closed is True


@pytest.mark.asyncio
async def test_common_document_storage_finishes_before_access_row_lock() -> None:
    initial, locked, group = _scope_pair()
    current_user = SimpleNamespace(id=uuid.uuid4())
    events: list[str] = []
    captured_documents: list[object] = []
    session = MagicMock()
    session.add = MagicMock(side_effect=captured_documents.append)
    session.flush = AsyncMock(side_effect=lambda: events.append("flush"))
    session.commit = AsyncMock(side_effect=lambda: events.append("commit"))
    session.rollback = AsyncMock(side_effect=lambda: events.append("read-transaction-closed"))
    storage = MagicMock()
    storage.upload_file = AsyncMock(side_effect=lambda *_args: events.append("storage-upload"))
    storage.delete_files = AsyncMock(return_value=1)

    async def access_context(*_args, lock: bool, **_kwargs):
        events.append("row-lock" if lock else "authorize-read")
        return (locked if lock else initial), group

    async def validate(_file):
        events.append("pdf-validation")
        return _validated_pdf()

    with (
        patch(
            "app.presentation.api.v1.routes.gc_app_content._admin_access_context",
            side_effect=access_context,
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content._validated_common_pdf",
            side_effect=validate,
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content.MinioStorageRepository",
            return_value=storage,
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content._content_audit",
            new=AsyncMock(),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content._common_document_response",
            return_value=SimpleNamespace(id="response"),
        ),
    ):
        result = await _store_common_document_version(
            session,
            request=_request(),
            current_user=current_user,
            group_id=initial.group_id,
            agency_id=initial.agency_id,
            expected_access_revision=4,
            file=MagicMock(),
            category="travel_tips",
            display_name="Travel tips",
            offline_available=True,
        )

    assert result.id == "response"
    assert events.index("authorize-read") < events.index("read-transaction-closed")
    assert events.index("read-transaction-closed") < events.index("pdf-validation")
    assert events.index("storage-upload") < events.index("row-lock")
    assert events.index("row-lock") < events.index("flush") < events.index("commit")
    assert storage.delete_files.await_count == 0
    document = captured_documents[0]
    assert document.availability_starts_at == locked.access_starts_at
    assert document.availability_expires_at == locked.access_expires_at


@pytest.mark.asyncio
async def test_common_document_commit_failure_deletes_only_staged_object() -> None:
    initial, locked, group = _scope_pair()
    current_user = SimpleNamespace(id=uuid.uuid4())
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock(side_effect=RuntimeError("relational commit failed"))
    session.rollback = AsyncMock()
    storage = MagicMock()
    storage.upload_file = AsyncMock()
    storage.delete_files = AsyncMock(return_value=1)

    async def access_context(*_args, lock: bool, **_kwargs):
        return (locked if lock else initial), group

    with (
        patch(
            "app.presentation.api.v1.routes.gc_app_content._admin_access_context",
            side_effect=access_context,
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content._validated_common_pdf",
            new=AsyncMock(return_value=_validated_pdf()),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content.MinioStorageRepository",
            return_value=storage,
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content._content_audit",
            new=AsyncMock(),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content._common_document_response",
            return_value=SimpleNamespace(id="response"),
        ),
    ):
        with pytest.raises(RuntimeError, match="relational commit failed"):
            await _store_common_document_version(
                session,
                request=_request(),
                current_user=current_user,
                group_id=initial.group_id,
                agency_id=initial.agency_id,
                expected_access_revision=4,
                file=MagicMock(),
                category="travel_tips",
                display_name="Travel tips",
                offline_available=True,
            )

    uploaded_key = storage.upload_file.await_args.args[1]
    assert uploaded_key.startswith(
        f"gc-app/{initial.agency_id}/{initial.group_id}/common/"
    )
    storage.delete_files.assert_awaited_once_with([uploaded_key])
    # One rollback closes the authorization read; the second clears the failed
    # relational commit before object compensation.
    assert session.rollback.await_count == 2


@pytest.mark.asyncio
async def test_revision_conflict_after_staging_rolls_back_and_deletes_object() -> None:
    initial, locked, group = _scope_pair()
    locked.revision = initial.revision + 1
    current_user = SimpleNamespace(id=uuid.uuid4())
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    storage = MagicMock()
    storage.upload_file = AsyncMock()
    storage.delete_files = AsyncMock(return_value=1)

    async def access_context(*_args, lock: bool, **_kwargs):
        return (locked if lock else initial), group

    with (
        patch(
            "app.presentation.api.v1.routes.gc_app_content._admin_access_context",
            side_effect=access_context,
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content._validated_common_pdf",
            new=AsyncMock(return_value=_validated_pdf()),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content.MinioStorageRepository",
            return_value=storage,
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await _store_common_document_version(
                session,
                request=_request(),
                current_user=current_user,
                group_id=initial.group_id,
                agency_id=initial.agency_id,
                expected_access_revision=4,
                file=MagicMock(),
                category="travel_tips",
                display_name="Travel tips",
                offline_available=True,
            )

    assert exc_info.value.status_code == 409
    assert "refresh and retry" in str(exc_info.value.detail)
    storage.delete_files.assert_awaited_once_with(
        [storage.upload_file.await_args.args[1]]
    )
    session.add.assert_not_called()
    session.commit.assert_not_awaited()
    assert session.rollback.await_count == 2


@pytest.mark.asyncio
async def test_replacement_allocates_version_only_after_row_lock() -> None:
    initial, locked, group = _scope_pair()
    logical_id = uuid.uuid4()
    document_id = uuid.uuid4()
    initial_previous = SimpleNamespace(logical_document_id=logical_id, sort_order=3)
    locked_previous = SimpleNamespace(logical_document_id=logical_id, sort_order=7)
    current_user = SimpleNamespace(id=uuid.uuid4())
    events: list[str] = []
    captured_documents: list[object] = []
    scalar_result = MagicMock()
    scalar_result.scalar_one.return_value = 9
    session = MagicMock()
    session.add = MagicMock(side_effect=captured_documents.append)
    session.execute = AsyncMock(
        side_effect=lambda *_args: (events.append("version-query"), scalar_result)[1]
    )
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    storage = MagicMock()
    storage.upload_file = AsyncMock(side_effect=lambda *_args: events.append("storage-upload"))
    storage.delete_files = AsyncMock(return_value=1)

    async def access_context(*_args, lock: bool, **_kwargs):
        events.append("row-lock" if lock else "authorize-read")
        return (locked if lock else initial), group

    async def get_document(*_args, lock: bool, **_kwargs):
        return locked_previous if lock else initial_previous

    with (
        patch(
            "app.presentation.api.v1.routes.gc_app_content._admin_access_context",
            side_effect=access_context,
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content._get_common_document",
            side_effect=get_document,
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content._validated_common_pdf",
            new=AsyncMock(return_value=_validated_pdf()),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content.MinioStorageRepository",
            return_value=storage,
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content._content_audit",
            new=AsyncMock(),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content._common_document_response",
            return_value=SimpleNamespace(id="response"),
        ),
    ):
        await _store_common_document_version(
            session,
            request=_request(),
            current_user=current_user,
            group_id=initial.group_id,
            agency_id=initial.agency_id,
            expected_access_revision=4,
            file=MagicMock(),
            category="itinerary_pdf",
            display_name="Itinerary",
            offline_available=True,
            replace_document_id=document_id,
        )

    assert events.index("storage-upload") < events.index("row-lock")
    assert events.index("row-lock") < events.index("version-query")
    document = captured_documents[0]
    assert document.logical_document_id == logical_id
    assert document.version == 10
    assert document.sort_order == locked_previous.sort_order
    storage.delete_files.assert_not_awaited()
