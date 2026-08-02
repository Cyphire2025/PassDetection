from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request

from app.presentation.api.v1.routes.gc_app_content import (
    _store_common_document_version,
)


@pytest.mark.asyncio
async def test_common_document_commit_failure_deletes_only_uploaded_object() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    access = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        group_id=group_id,
        revision=4,
        updated_by_user_id=None,
        updated_at=None,
    )
    current_user = SimpleNamespace(id=uuid.uuid4())
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock(side_effect=RuntimeError("relational commit failed"))
    session.rollback = AsyncMock()
    storage = MagicMock()
    storage.upload_file = AsyncMock()
    storage.delete_files = AsyncMock(return_value=1)
    validated = SimpleNamespace(
        content=b"%PDF-1.7\nvalidated",
        content_type="application/pdf",
        filename="travel-tips.pdf",
        sha256_hex="a" * 64,
    )

    with (
        patch(
            "app.presentation.api.v1.routes.gc_app_content._validated_common_pdf",
            new=AsyncMock(return_value=validated),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content.MinioStorageRepository",
            return_value=storage,
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app_content._content_audit",
            new=AsyncMock(),
        ),
    ):
        with pytest.raises(RuntimeError, match="relational commit failed"):
            await _store_common_document_version(
                session,
                request=request,
                current_user=current_user,
                access=access,
                file=MagicMock(),
                category="travel_tips",
                display_name="Travel tips",
                available_from=None,
                available_until=None,
                offline_available=True,
                logical_document_id=uuid.uuid4(),
                version=1,
            )

    uploaded_key = storage.upload_file.await_args.args[1]
    assert uploaded_key.startswith(f"gc-app/{agency_id}/{group_id}/common/")
    storage.delete_files.assert_awaited_once_with([uploaded_key])
    session.rollback.assert_awaited_once()
