"""Public upload cancellation drains actual native S3 calls before compensation."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest
from sqlalchemy import update

from app.application.use_cases.passports.submit_passport_use_case import SubmitPassportUseCase
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.storage import minio_repository
from tests.passport_image_mutations import seed_image_mutation_context


class NativeObjectStore:
    def __init__(self, *, hold_back: bool = False, hold: bool = True):
        self.hold_back = hold_back
        self.hold = hold
        self.entered = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.objects = {}
        self.events = []

    def put_object(self, **kwargs):
        held = self.hold and (not self.hold_back or kwargs["Body"] == b"back")
        if held:
            self.entered.set()
            assert self.release.wait(3), "test must release the native write"
        self.objects[kwargs["Key"]] = kwargs["Body"]
        self.events.append(("write", kwargs["Key"]))
        if held:
            self.finished.set()

    def delete_objects(self, **kwargs):
        for item in kwargs["Delete"]["Objects"]:
            self.objects.pop(item["Key"], None)
            self.events.append(("delete", item["Key"]))
        return {}


async def public_upload_context(session, monkeypatch, native, *, back=False):
    context = await seed_image_mutation_context(session)
    pages = ["front", "back"] if back else ["front"]
    await session.execute(
        update(ClientGroupModel).where(ClientGroupModel.id == context.submission.group_id)
        .values(allow_files_from_device=True, require_selfie=False,
                upload_configuration={"passport_upload_pages": pages})
    )
    await session.commit()
    group = await ClientGroupRepository(session).get_by_id(context.submission.group_id)
    assert group is not None
    monkeypatch.setattr(minio_repository, "get_settings", lambda: SimpleNamespace(
        s3=SimpleNamespace(bucket_name="synthetic-private-bucket")
    ))
    monkeypatch.setattr(minio_repository, "_shared_s3_clients", lambda: (native, native))
    storage = minio_repository.MinioStorageRepository()
    repo = PassportSubmissionRepository(session)
    use_case = SubmitPassportUseCase(ClientGroupRepository(session), repo, storage)
    kwargs = dict(token=group.token, file_content=b"front", content_type="image/jpeg",
                  filename="front.jpg", client_name="Synthetic Traveller",
                  upload_idempotency_key="synthetic-native-upload-" + "a" * 40)
    if back:
        kwargs["passport_back"] = (b"back", "image/jpeg", "back.jpg")
    return use_case, repo, group.id, kwargs


@pytest.mark.asyncio
async def test_normal_native_public_upload_keeps_its_stored_object_and_durable_draft(
    db_session, monkeypatch
):
    native = NativeObjectStore(hold=False)
    use_case, repo, group_id, kwargs = await public_upload_context(db_session, monkeypatch, native)
    result = await use_case.execute(**kwargs)
    await db_session.commit()
    persisted = await repo.get_by_upload_idempotency_key(group_id, kwargs["upload_idempotency_key"])
    assert persisted is not None and result.id == persisted.id
    assert native.objects == {persisted.image_s3_key: b"front"}
    assert [kind for kind, _ in native.events] == ["write"]


@pytest.mark.asyncio
@pytest.mark.parametrize("back", [False, True])
@pytest.mark.parametrize("repeat_cancel", [False, True])
async def test_cancelled_public_upload_waits_for_late_native_page_and_removes_owned_bytes(
    db_session, monkeypatch, back, repeat_cancel
):
    native = NativeObjectStore(hold_back=back)
    use_case, repo, group_id, kwargs = await public_upload_context(
        db_session, monkeypatch, native, back=back
    )
    task = asyncio.create_task(use_case.execute(**kwargs))
    try:
        assert await asyncio.to_thread(native.entered.wait, 2)
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=0.05)
        returned_before_native_write = bool(done)
        if repeat_cancel:
            task.cancel()
            done, _ = await asyncio.wait({task}, timeout=0.05)
            returned_before_native_write |= bool(done)
    finally:
        native.release.set()
    assert await asyncio.to_thread(native.finished.wait, 2)
    with pytest.raises(asyncio.CancelledError):
        await task
    await db_session.rollback()
    assert await repo.get_by_upload_idempotency_key(group_id, kwargs["upload_idempotency_key"]) is None
    assert not returned_before_native_write, native.events
    assert native.objects == {}, native.events
    last_write = max(i for i, (kind, _) in enumerate(native.events) if kind == "write")
    assert all(kind == "delete" for kind, _ in native.events[last_write + 1:])


@pytest.mark.asyncio
async def test_cancelled_persistence_cleans_already_completed_native_upload(db_session, monkeypatch):
    native = NativeObjectStore(hold=False)
    use_case, repo, group_id, kwargs = await public_upload_context(db_session, monkeypatch, native)
    entered = asyncio.Event()
    hold = asyncio.Event()
    original_save = repo.save_idempotent

    async def save(submission):
        entered.set()
        await hold.wait()
        return await original_save(submission)

    monkeypatch.setattr(repo, "save_idempotent", save)
    task = asyncio.create_task(use_case.execute(**kwargs))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert len(native.objects) == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        hold.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    await db_session.rollback()
    assert native.objects == {}
    assert await repo.get_by_upload_idempotency_key(group_id, kwargs["upload_idempotency_key"]) is None
