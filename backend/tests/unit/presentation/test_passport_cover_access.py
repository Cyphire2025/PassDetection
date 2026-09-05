import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.domain.exceptions.exceptions import AuthorizationError
from app.presentation.api.v1.routes.passport_routes import covers


@pytest.mark.asyncio
async def test_cover_access_checks_staff_visibility_before_reading_storage(monkeypatch):
    row = SimpleNamespace(id=uuid.uuid4(), passport_cover_s3_key="private/front-cover.jpg")
    repo = AsyncMock()
    repo.get_by_id.return_value = row
    policy = AsyncMock()
    policy.require_view_passport.side_effect = AuthorizationError("Access denied")
    storage = MagicMock()
    monkeypatch.setattr(covers, "PassportSubmissionRepository", lambda _session: repo)
    monkeypatch.setattr(covers, "AuthorizationPolicy", lambda _session: policy)
    monkeypatch.setattr(covers, "MinioStorageRepository", storage)
    with pytest.raises(HTTPException) as caught:
        await covers.get_passport_cover(row.id, "cover", current_user=object(), session=object())
    assert caught.value.status_code == 403
    storage.assert_not_called()


@pytest.mark.asyncio
async def test_cover_access_streams_authoritative_key_with_range_header(monkeypatch):
    row = SimpleNamespace(id=uuid.uuid4(), passport_back_cover_s3_key="private/back-cover.jpg")
    repo = AsyncMock()
    repo.get_by_id.return_value = row
    policy = AsyncMock()
    stream = AsyncMock(return_value="streamed-cover")
    monkeypatch.setattr(covers, "PassportSubmissionRepository", lambda _session: repo)
    monkeypatch.setattr(covers, "AuthorizationPolicy", lambda _session: policy)
    monkeypatch.setattr(covers, "MinioStorageRepository", MagicMock())
    monkeypatch.setattr(covers, "private_object_streaming_response", stream)
    assert (
        await covers.get_passport_cover(
            row.id, "back_cover", range_header="bytes=0-99", current_user=object(), session=object()
        )
        == "streamed-cover"
    )
    assert stream.await_args.kwargs["key"] == "private/back-cover.jpg"
    assert stream.await_args.kwargs["range_header"] == "bytes=0-99"
    policy.require_view_passport.assert_awaited_once()
