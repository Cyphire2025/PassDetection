"""Synthetic route boundaries; actual importer spools and S3 adapter stay active."""

from __future__ import annotations

import asyncio
import io
import threading
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import BackgroundTasks, UploadFile

from app.infrastructure.imports.passport_document_importer import (
    PassportDocumentImporter,
    PassportDocumentImportWorkspace,
)
from app.infrastructure.security.upload_validator import ValidatedUpload
from app.presentation.api.v1.routes.passport_routes import document_import as route
from app.presentation.api.v1.routes.passport_routes import (
    document_import_failure,
    document_import_preview,
)


class NativeBarrier:
    """Hold a real to_thread operation without replacing asyncio or its cancellation."""

    def __init__(self, operation):
        self.operation = operation
        self.loop = asyncio.get_running_loop()
        self.entered = asyncio.Event()
        self.completed = asyncio.Event()
        self.release = threading.Event()

    def __call__(self, *args, **kwargs):
        self.loop.call_soon_threadsafe(self.entered.set)
        try:
            if not self.release.wait(5):
                raise RuntimeError("Synthetic native import work was not released")
            return self.operation(*args, **kwargs)
        finally:
            self.loop.call_soon_threadsafe(self.completed.set)


class SyntheticValidator:
    def validate(self, *, content, filename, declared_content_type):
        return ValidatedUpload(
            content=b"canonical:" + content,
            filename=filename,
            content_type="image/jpeg",
            width=10,
            height=10,
            format="JPEG",
        )


def install_import_context(monkeypatch, *, session=None, group=None, actor=None, submission=None):
    """Isolate authorization/provider sends while exercising real route orchestration."""
    group = group or SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4())
    actor = actor or SimpleNamespace(id=uuid.uuid4(), email="synthetic@example.test")
    submission = submission or SimpleNamespace(
        id=uuid.uuid4(),
        group_id=group.id,
        client_name="Synthetic",
        staff_metadata={"staff_code": "A1"},
        confirmed_fields={},
        extracted_fields={},
        image_s3_key=None,
        passport_photo_s3_key=None,
        passport_back_s3_key=None,
    )
    if session is None:
        result = MagicMock()
        result.scalars.return_value.all.return_value = [submission]
        session = SimpleNamespace(
            execute=AsyncMock(return_value=result),
            scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [submission])),
            flush=AsyncMock(),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
    workspaces = []

    def workspace_factory():
        workspace = PassportDocumentImportWorkspace()
        workspaces.append(workspace)
        return workspace

    monkeypatch.setattr(route, "PassportDocumentImportWorkspace", workspace_factory)
    monkeypatch.setattr(
        document_import_preview,
        "PassportDocumentImporter",
        lambda: PassportDocumentImporter(validator=SyntheticValidator()),
    )
    monkeypatch.setattr(route, "_authorized_passport_document_group", AsyncMock(return_value=group))
    # These older cases isolate native/commit lifetime; authority has actual-DB cases.
    monkeypatch.setattr(route, "lock_document_import_authority", AsyncMock(return_value=actor))
    monkeypatch.setattr(route, "propagate_mobile_passenger_change", AsyncMock())
    audit = SimpleNamespace(record=AsyncMock())
    monkeypatch.setattr(route, "AuditLogRepository", lambda _session: audit)
    monkeypatch.setattr(route, "_stage_ocr_for_complete_staff_bundles", AsyncMock(return_value=[]))
    monkeypatch.setattr(route, "_delete_unreferenced_passport_image_keys_best_effort", AsyncMock())
    reconciliation = AsyncMock(return_value=True)
    monkeypatch.setattr(document_import_failure, "reconcile_failed_passport_import", reconciliation)
    storage = SimpleNamespace(upload_file=AsyncMock())
    monkeypatch.setattr(route, "MinioStorageRepository", lambda: storage)
    return SimpleNamespace(
        group=group,
        actor=actor,
        submission=submission,
        session=session,
        workspaces=workspaces,
        reconciliation=reconciliation,
        storage=storage,
    )


async def invoke(context, endpoint):
    upload = UploadFile(io.BytesIO(b"synthetic-source"), filename="STF_A1_FRONT.jpg")
    try:
        arguments = dict(
            group_id=context.group.id,
            current_user=context.actor,
            session=context.session,
            files=[upload],
        )
        if endpoint == "save":
            return await route.save_passport_documents_by_group(
                **arguments,
                background_tasks=BackgroundTasks(),
            )
        return await route.preview_passport_documents_by_group(**arguments)
    finally:
        await upload.close()


async def cancel_held_operation(task, barrier, *, twice):
    try:
        await asyncio.wait_for(barrier.entered.wait(), 3)
        task.cancel()
        await asyncio.wait({task}, timeout=0.03)
        if twice:
            task.cancel()
            await asyncio.wait({task}, timeout=0.03)
        returned_while_native_active = task.done()
    finally:
        barrier.release.set()
        outcomes = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 3)
        await asyncio.wait_for(barrier.completed.wait(), 3)
    assert isinstance(outcomes[0], asyncio.CancelledError)
    return returned_while_native_active
