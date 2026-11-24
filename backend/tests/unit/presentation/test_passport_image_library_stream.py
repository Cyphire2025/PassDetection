"""Private library streams keep authorization, item scope, and response headers."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.domain.exceptions.exceptions import StorageError
from app.domain.value_objects.passport_image_crop import PassportImageType
from app.presentation.api.v1.routes import passport_image_library as routes
from tests.route_dependencies import set_route_dependency


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "key", "expected_status", "mime"),
    [
        ("success", "passport-image-library/synthetic.png", 200, "image/png"),
        ("success", "passport-image-library/synthetic", 200, "image/jpeg"),
        ("missing", "passport-image-library/synthetic.png", 404, None),
        ("storage-error", "passport-image-library/synthetic.png", 503, None),
        ("forbidden", "passport-image-library/synthetic.png", 403, None),
    ],
    ids=["png", "mime-fallback", "missing", "unavailable", "forbidden"],
)
async def test_private_item_stream(monkeypatch, outcome, key, expected_status, mime):
    submission_id, item_id = uuid.uuid4(), uuid.uuid4()
    image_type = PassportImageType.PASSPORT_FRONT
    actor, session = SimpleNamespace(), MagicMock()
    authorized = AsyncMock(return_value=(SimpleNamespace(id=submission_id), "original.jpg"))
    if outcome == "forbidden":
        authorized.side_effect = HTTPException(403, "Synthetic denied scope")
    item = None if outcome == "missing" else SimpleNamespace(id=item_id, storage_key=key)
    repository = SimpleNamespace(get_for_image=AsyncMock(return_value=item))
    repository_factory = MagicMock(return_value=repository)
    content = b"synthetic private image bytes"
    storage = SimpleNamespace(get_file=AsyncMock(return_value=content))
    if outcome == "storage-error":
        storage.get_file.side_effect = StorageError("Synthetic storage is unavailable")
    storage_factory = MagicMock(return_value=storage)
    for name, value in [
        ("_authorized_staff_passport_image", authorized),
        ("PassportImageLibraryRepository", repository_factory),
        ("MinioStorageRepository", storage_factory),
    ]:
        set_route_dependency(monkeypatch, routes, name, value)

    args = dict(
        submission_id=submission_id,
        image_type=image_type,
        item_id=item_id,
        current_user=actor,
        session=session,
    )
    if expected_status == 200:
        response = await routes.get_passport_image_library_item(**args)
        assert response.status_code == 200
        assert response.media_type == mime
        assert b"".join([chunk async for chunk in response.body_iterator]) == content
        assert response.headers["Cache-Control"] == "private, no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        extension = ".png" if mime == "image/png" else ".jpg"
        assert response.headers["Content-Disposition"] == (
            f'inline; filename="{image_type.value}-library-{item_id}{extension}"'
        )
    else:
        with pytest.raises(HTTPException) as caught:
            await routes.get_passport_image_library_item(**args)
        assert caught.value.status_code == expected_status
        if outcome == "storage-error":
            assert caught.value.detail == "Synthetic storage is unavailable"
            assert caught.value.__cause__ is storage.get_file.side_effect

    authorized.assert_awaited_once_with(
        submission_id=submission_id,
        image_type=image_type,
        current_user=actor,
        session=session,
        require_editor=True,
    )
    if outcome == "forbidden":
        repository_factory.assert_not_called()
        repository.get_for_image.assert_not_awaited()
    else:
        repository_factory.assert_called_once_with(session)
        repository.get_for_image.assert_awaited_once_with(
            submission_id=submission_id, image_type=image_type, item_id=item_id
        )
    if outcome in {"missing", "forbidden"}:
        storage_factory.assert_not_called()
        storage.get_file.assert_not_awaited()
    else:
        storage.get_file.assert_awaited_once_with(key)
