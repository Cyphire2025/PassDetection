"""Owned image-write failures keep public errors and sequential compensation."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.domain.exceptions.exceptions import StorageError
from app.presentation.api.v1.routes.passport_image_storage_write import write_passport_image_objects


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_at", [1, 2])
@pytest.mark.parametrize(
    "storage_error", [False, True], ids=["original-error", "public-storage-error"]
)
async def test_failed_sequential_write_compensates_claimed_keys_and_preserves_error(
    fail_at, storage_error
):
    objects = [
        (b"one", "passport-image-library/synthetic.jpg", "image/jpeg"),
        (b"two", "passport-crops/synthetic.jpg", "image/jpeg"),
    ]
    calls, deleted = [], []
    failure = (
        StorageError("Synthetic storage is unavailable")
        if storage_error
        else RuntimeError("Synthetic adapter failure")
    )

    async def upload(content, key, content_type):
        calls.append((content, key, content_type))
        if len(calls) == fail_at:
            raise failure
        return key

    async def delete(keys):
        deleted.extend(keys)
        return len(keys)

    with pytest.raises(HTTPException if storage_error else RuntimeError) as caught:
        await write_passport_image_objects(
            SimpleNamespace(upload_file=upload, delete_files=delete),
            objects,
            submission_id=uuid.uuid4(),
        )
    assert calls == objects[:fail_at]
    assert deleted == [key for _, key, _ in objects]
    if storage_error:
        assert caught.value.status_code == 503
        assert caught.value.detail == failure.message
        assert caught.value.__cause__ is failure
    else:
        assert caught.value is failure
