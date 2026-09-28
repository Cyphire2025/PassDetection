import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.domain.exceptions.exceptions import AuthorizationError
from app.domain.value_objects.passport_image_crop import PassportImageType
from app.presentation.api.v1.routes.passport_routes import covers
from app.presentation.api.v1.routes.passport_routes.response_support import _staff_image_urls


@pytest.mark.parametrize("image_type,field", [
    (PassportImageType.PASSPORT_COVER, "passport_cover"),
    (PassportImageType.PASSPORT_BACK_COVER, "passport_back_cover"),
])
def test_staff_cover_urls_use_current_edit_revision(image_type, field):
    submission = SimpleNamespace(id=uuid.uuid4(), **{f"{field}_s3_key": "original/cover.jpg"})
    urls = _staff_image_urls(submission, {image_type: SimpleNamespace(revision=7)})
    assert urls[f"{field}_url"] == f"/api/v1/passports/{submission.id}/images/{image_type.value}?crop_revision=7"
    setattr(submission, f"{field}_s3_key", None)
    assert _staff_image_urls(submission)[f"{field}_url"] is None


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
    row = SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4(), passport_back_cover_s3_key="private/back-cover.jpg")
    repo = AsyncMock()
    repo.get_by_id.return_value = row
    policy = AsyncMock()
    stream = AsyncMock(return_value="streamed-cover")
    monkeypatch.setattr(covers, "PassportSubmissionRepository", lambda _session: repo)
    monkeypatch.setattr(covers, "AuthorizationPolicy", lambda _session: policy)
    monkeypatch.setattr(covers, "MinioStorageRepository", MagicMock())
    monkeypatch.setattr(covers, "private_object_streaming_response", stream)
    audit = AsyncMock()
    monkeypatch.setattr(covers, "record_sensitive_read", audit)
    assert (
        await covers.get_passport_cover(
            row.id, "back_cover", range_header="bytes=0-99", current_user=object(), session=object()
        )
        == "streamed-cover"
    )
    assert stream.await_args.kwargs["key"] == "private/back-cover.jpg"
    assert stream.await_args.kwargs["range_header"] == "bytes=0-99"
    policy.require_view_passport.assert_awaited_once()
    audit.assert_awaited_once()
