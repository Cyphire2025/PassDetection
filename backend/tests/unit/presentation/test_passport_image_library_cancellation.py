"""Synthetic native image writes cannot outlive their request's compensation."""

from __future__ import annotations

import asyncio
import threading
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks

from app.domain.value_objects.passport_image_crop import (
    PassportImageType,
    passport_image_storage_key,
)
from app.domain.value_objects.passport_image_library import PassportImageLibrarySource
from app.presentation.api.v1.routes import passport_image_library as route
from app.presentation.api.v1.schemas.passport_schemas import PassportVisaAiImageUseRequest
from tests.route_dependencies import set_route_dependency
from tests.unit.presentation.test_passport_image_library_routes import _item, _submission


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["native", "persistence"])
@pytest.mark.parametrize("operation", ["manual", "select"])
@pytest.mark.parametrize("cancel", [False, True], ids=["ordinary", "cancel-native-write"])
async def test_native_image_write_finishes_before_cancellation_compensation(
    monkeypatch, operation, cancel, phase
):
    submission = _submission()
    image_type = PassportImageType.PASSPORT_BACK_COVER
    source = passport_image_storage_key(submission, image_type)
    item = _item(
        submission.id,
        image_type=image_type,
        source=PassportImageLibrarySource.MANUAL,
        storage_key="passport-image-library/synthetic-existing.jpg",
    )
    objects = {source: b"source", item.storage_key: b"existing"}
    original_keys = set(objects)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    transaction_entered, transaction_release = asyncio.Event(), asyncio.Event()

    def write(content, key):
        entered.set()
        if phase == "native" and not release.wait(5):
            raise TimeoutError("Synthetic image writer was not released")
        objects[key] = content
        finished.set()
        return key

    async def upload(content, key, _content_type):
        return await asyncio.to_thread(write, content, key)

    async def delete(keys):
        for key in keys:
            objects.pop(key, None)
        return len(keys)

    storage = SimpleNamespace(
        get_file=AsyncMock(return_value=b"existing"),
        upload_file=upload,
        delete_files=delete,
    )
    library = SimpleNamespace(
        ensure_original=AsyncMock(return_value=(item, False)),
        create_manual=AsyncMock(
            side_effect=lambda **values: _item(
                submission.id,
                image_type=image_type,
                source=PassportImageLibrarySource.MANUAL,
                storage_key=values["storage_key"],
            )
        ),
        get_for_image=AsyncMock(return_value=item),
    )
    crop = SimpleNamespace(upsert=AsyncMock(return_value=(SimpleNamespace(revision=1), None, None)))

    async def locked_submission(_submission_id):
        if phase == "persistence":
            transaction_entered.set()
            await transaction_release.wait()
        return submission

    passport = SimpleNamespace(get_by_id_for_update=AsyncMock(side_effect=locked_submission))
    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    actor = SimpleNamespace(id=uuid.uuid4(), email="native-image@example.test")
    set_route_dependency(
        monkeypatch,
        route,
        "_resolve_authorized_staff_passport_image",
        AsyncMock(return_value=(submission, source)),
    )
    set_route_dependency(monkeypatch, route, "MinioStorageRepository", lambda: storage)
    set_route_dependency(
        monkeypatch, route, "PassportImageLibraryRepository", lambda _session: library
    )
    set_route_dependency(monkeypatch, route, "PassportImageCropRepository", lambda _session: crop)
    set_route_dependency(
        monkeypatch, route, "PassportSubmissionRepository", lambda _session: passport
    )

    async def lock_scope(_session, *, current_user, submission, image_type, source_key):
        return current_user, await passport.get_by_id_for_update(submission.id)

    set_route_dependency(monkeypatch, route, "lock_passport_image_mutation", lock_scope)
    set_route_dependency(
        monkeypatch,
        route,
        "AuditLogRepository",
        lambda _session: SimpleNamespace(record=AsyncMock()),
    )
    set_route_dependency(
        monkeypatch,
        route,
        "_validated_upload_file",
        AsyncMock(return_value=SimpleNamespace(content=b"upload", content_type="image/jpeg")),
    )
    set_route_dependency(
        monkeypatch,
        route,
        "render_passport_image_crop",
        lambda *_args, **_kwargs: SimpleNamespace(
            content=b"derivative",
            content_type="image/jpeg",
            extension=".jpg",
            source_width=800,
            source_height=600,
        ),
    )
    set_route_dependency(monkeypatch, route, "_crop_response", lambda **_kwargs: SimpleNamespace())

    async def execute():
        if operation == "manual":
            return await route.upload_passport_image_library_item(
                submission_id=submission.id,
                image_type=image_type,
                background_tasks=BackgroundTasks(),
                image=SimpleNamespace(),
                expected_revision=0,
                _csrf=None,
                current_user=actor,
                session=session,
            )
        return await route.use_passport_image_library_item(
            submission_id=submission.id,
            image_type=image_type,
            item_id=item.id,
            body=PassportVisaAiImageUseRequest(x=0, y=0, width=1, height=1, expected_revision=0),
            background_tasks=BackgroundTasks(),
            _csrf=None,
            current_user=actor,
            session=session,
        )

    task = asyncio.create_task(execute())
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        if phase == "persistence":
            await asyncio.wait_for(transaction_entered.wait(), timeout=3)
        if cancel:
            task.cancel()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            abandoned = task.done()
        release.set()
        transaction_release.set()
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await task
        assert await asyncio.to_thread(finished.wait, 3)
        if cancel:
            assert set(objects) == original_keys, (
                "A cancelled image write left sensitive orphaned bytes"
            )
            if phase == "native":
                assert not abandoned, "The request released its native write before it finished"
            crop.upsert.assert_not_awaited()
            session.commit.assert_not_awaited()
        else:
            assert set(objects) > original_keys
            crop.upsert.assert_awaited_once()
            session.commit.assert_awaited_once()
    finally:
        release.set()
        transaction_release.set()
        if not task.done():
            await asyncio.gather(task, return_exceptions=True)
