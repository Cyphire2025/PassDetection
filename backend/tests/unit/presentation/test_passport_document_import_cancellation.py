"""Request exit must not close framework or canonical spools under native IO."""

import asyncio

import pytest

from app.infrastructure.imports.passport_document_importer import (
    PassportDocumentImporter,
    StagedValidatedUpload,
)
from app.presentation.api.v1.routes.passport_routes import document_import as route
from app.presentation.api.v1.routes.passport_routes import document_import_preview
from tests.unit.presentation.passport_document_import_fixture import (
    NativeBarrier,
    cancel_held_operation,
    install_import_context,
    invoke,
)


@pytest.mark.parametrize(
    "endpoint,phase",
    [
        ("preview", "measure"),
        ("preview", "collect"),
        ("save", "measure"),
        ("save", "collect"),
        ("save", "read"),
    ],
)
@pytest.mark.parametrize("cancel_twice", [False, True])
async def test_request_waits_for_native_import_before_closing_spools(
    monkeypatch,
    endpoint,
    phase,
    cancel_twice,
):
    context = install_import_context(monkeypatch)
    if phase == "measure":
        barrier = NativeBarrier(route._passport_document_upload_sources)
        monkeypatch.setattr(document_import_preview, "_passport_document_upload_sources", barrier)
    elif phase == "collect":
        barrier = NativeBarrier(PassportDocumentImporter.collect)
        monkeypatch.setattr(
            PassportDocumentImporter, "collect", lambda self, *a, **kw: barrier(self, *a, **kw)
        )
    else:
        barrier = NativeBarrier(StagedValidatedUpload.read_content)
        monkeypatch.setattr(StagedValidatedUpload, "read_content", lambda self: barrier(self))
    task = asyncio.create_task(invoke(context, endpoint))
    returned_early = await cancel_held_operation(task, barrier, twice=cancel_twice)
    closed = [workspace._closed for workspace in context.workspaces]
    # Always release test-owned streams, even on an intentionally failing baseline.
    for workspace in context.workspaces:
        workspace.close()
    assert not returned_early, (
        "Request released its spools while actual native import work was held"
    )
    assert closed == [True], "Cancelled save leaked its request-owned staging workspace"
    context.storage.upload_file.assert_not_awaited()


@pytest.mark.parametrize("endpoint", ["preview", "save"])
async def test_ordinary_import_still_reads_canonical_spools_and_closes_them(monkeypatch, endpoint):
    context = install_import_context(monkeypatch)
    result = await invoke(context, endpoint)
    assert result.accepted_count == 1 and result.rejected_count == 0
    assert context.workspaces[0]._closed
    if endpoint == "save":
        assert result.saved_count == 1
        content, key, media_type = context.storage.upload_file.await_args.args
        assert content == b"canonical:synthetic-source" and media_type == "image/jpeg"
        assert key == context.submission.image_s3_key and key.startswith("passport-bulk/")
        context.session.commit.assert_awaited_once()
    else:
        context.storage.upload_file.assert_not_awaited()
    context.reconciliation.assert_not_awaited()


async def test_cancelled_locked_lookup_closes_staging_workspace(monkeypatch):
    context = install_import_context(monkeypatch)
    original_execute = context.session.execute
    entered = asyncio.Event()

    async def execute(statement):
        if original_execute.await_count:
            entered.set()
            await asyncio.Event().wait()
        return await original_execute(statement)

    context.session.execute = execute
    task = asyncio.create_task(invoke(context, "save"))
    await asyncio.wait_for(entered.wait(), 3)
    task.cancel()
    outcome = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 3)
    closed = context.workspaces[0]._closed
    context.workspaces[0].close()
    assert isinstance(outcome[0], asyncio.CancelledError)
    assert closed, "Cancellation during the locked lookup skipped workspace.close"
