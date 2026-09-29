"""Shared family admission and passport XLSX budgets before retaining artifacts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.application.mcp import exports
from app.application.mcp.artifacts import ArtifactError
from app.application.mcp.authorization import MCPAuthError
from app.application.mcp.image_exports import MCPImageExportService
from app.application.mcp.rooming_exports import MCPRoomingExportService
from app.application.mcp.tracking_exports import MCPTrackingExportService
from app.application.use_cases.passports.excel_snapshot import (
    ExcelSnapshotTooLarge,
    snapshot_digest,
)
from app.application.use_cases.passports.prepare_group_excel import (
    ExcelPreparationError,
    _canonical,
)
from app.core.mcp_export_admission import export_slot
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_models import MCPGrantModel
from app.infrastructure.database.models import PassportExportHistoryModel
from app.infrastructure.documents.storage_transfers import run_bounded_storage_operations
from app.infrastructure.export.passport_excel_exporter import PassportExcelExporter
from tests.integration.test_mcp_artifacts import artifacts as artifacts
from tests.integration.test_mcp_exports import generate, person, queue, service


@pytest.mark.parametrize(
    "kind",
    [
        exports.MCPExcelExportService,
        MCPImageExportService,
        MCPTrackingExportService,
        MCPRoomingExportService,
    ],
)
@pytest.mark.parametrize("method", ["inspect", "prepare", "generate"])
async def test_every_family_rejects_before_touching_session_or_bulk_sources(kind, method):
    # Uninitialized service has no session/support: reaching either is a failure.
    instance = object.__new__(kind)
    with export_slot():
        arguments = (
            {"access_token": "unused", "operation_id": uuid.uuid4()} if method == "generate" else {}
        )
        positional = () if method == "generate" else (None, None)
        with pytest.raises(ArtifactError, match="capacity is busy") as error:
            await asyncio.create_task(getattr(instance, method)(*positional, **arguments))
        assert error.value.status_code == 503


def test_streamed_digest_preserves_existing_format_and_bounds_escaped_strings():
    @dataclass
    class Snapshot:
        identifier: uuid.UUID
        time: datetime
        data: dict

    value = Snapshot(uuid.uuid4(), datetime.now(UTC), {uuid.uuid4(): ['é\\"\n' * 1200, 1.25, None]})
    previous = json.dumps(
        _canonical(value), sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    assert snapshot_digest(value) == hashlib.sha256(previous).hexdigest()
    assert (
        snapshot_digest(value, maximum_bytes=len(previous)) == hashlib.sha256(previous).hexdigest()
    )
    with pytest.raises(ExcelSnapshotTooLarge):
        snapshot_digest(value, maximum_bytes=len(previous) - 1)


@pytest.mark.parametrize("selection", ["group", "selected_groups", "selected_passports"])
async def test_snapshot_bound_applies_to_all_passport_selection_modes(
    artifacts, monkeypatch, selection
):
    f = artifacts
    member = person(f, 1)
    f.session.add(member)
    await f.session.commit()
    request = exports.ExcelExportRequest(
        agency_id=f.agency.id,
        group_ids=[f.group.id],
        selection=selection,
        submission_ids=[member.id] if selection == "selected_passports" else [],
    )
    monkeypatch.setattr(exports, "MAX_SNAPSHOT_BYTES", 10)
    with pytest.raises(ArtifactError, match="snapshot") as error:
        await service(f).inspect(f.principal, request)
    assert error.value.status_code == 413
    assert not f.storage.objects


async def test_default_catalog_is_bounded_before_workbook_render(artifacts):
    f = artifacts
    original = service(f)

    def large_catalog(*args):
        return [{"key": str(index)} for index in range(257)]

    support = replace(
        original.support, group=replace(original.support.group, _export_field_catalog=large_catalog)
    )
    limited = exports.MCPExcelExportService(f.session, f.settings, support, artifacts=f.service)
    with pytest.raises(ExcelPreparationError, match="field limit"):
        await limited.inspect(
            f.principal, exports.ExcelExportRequest(agency_id=f.agency.id, group_ids=[f.group.id])
        )
    assert not f.storage.objects


@pytest.mark.parametrize(
    "bound", ["MAX_WORKBOOK_CELLS", "MAX_WORKBOOK_COLUMNS", "MAX_WORKBOOK_BYTES"]
)
async def test_workbook_budget_rejects_without_artifact_or_history(artifacts, monkeypatch, bound):
    f = artifacts
    f.session.add(person(f, 1))
    await f.session.commit()
    receipt, _, _ = await queue(f)
    monkeypatch.setattr(exports, bound, 1)
    with pytest.raises(ArtifactError, match="limit") as error:
        await generate(f, receipt)
    assert error.value.status_code == 413
    await f.session.rollback()
    assert not f.storage.objects
    for model in (MCPArtifactModel, PassportExportHistoryModel):
        assert await f.session.scalar(select(func.count()).select_from(model)) == 0


async def test_current_grant_is_revalidated_after_preparation_and_admission(artifacts):
    f = artifacts
    f.session.add(person(f, 1))
    await f.session.commit()
    receipt, _, _ = await queue(f)
    grant = await f.session.get(MCPGrantModel, f.principal.grant_id)
    grant.revoked_at = datetime.now(UTC)
    await f.session.commit()
    with pytest.raises(MCPAuthError):
        await generate(f, receipt)
    assert not f.storage.objects
    # A rejected authorization does not strand export admission.
    with export_slot():
        assert True


async def test_render_deadline_keeps_admission_until_native_render_drains(artifacts, monkeypatch):
    f = artifacts
    f.session.add(person(f, 1))
    await f.session.commit()
    receipt, _, _ = await queue(f)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = PassportExcelExporter.export_group

    def slow_render(self, *args, **kwargs):
        try:
            entered.set()
            assert release.wait(10)
            return original(self, *args, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(PassportExcelExporter, "export_group", slow_render)
    monkeypatch.setattr(exports, "RENDER_TIMEOUT_SECONDS", 0.01)
    task = asyncio.create_task(generate(f, receipt))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        await asyncio.sleep(0.03)
        assert not task.done() and not finished.is_set()
        with pytest.raises(ArtifactError, match="capacity is busy"):
            await service(f).inspect(f.principal, None)
    finally:
        release.set()
        with pytest.raises(TimeoutError):
            await task
        await f.session.rollback()
    assert finished.is_set() and not f.storage.objects
    with export_slot():
        assert exports._GENERATIONS.borrowed_tokens == 0


async def test_output_failure_cleans_openpyxl_owned_temporary_xml(artifacts, monkeypatch):
    from openpyxl.worksheet._writer import ALL_TEMP_FILES

    f = artifacts
    f.session.add_all([person(f, index) for index in range(20)])
    await f.session.commit()
    receipt, _, _ = await queue(f)
    before = set(ALL_TEMP_FILES)
    monkeypatch.setattr(exports, "MAX_WORKBOOK_BYTES", 3000)
    with pytest.raises(ArtifactError, match="output limit"):
        await generate(f, receipt)
    assert set(ALL_TEMP_FILES) == before
    await f.session.rollback()


async def test_large_retained_json_is_rejected_but_never_removed_or_rewritten(
    artifacts, monkeypatch
):
    f = artifacts
    member = person(f, 1)
    retained = {"passport_number": "TEST1", "historical_unrendered_text": "retained" * 4096}
    member.confirmed_fields = retained
    f.session.add(member)
    await f.session.commit()
    member_id = member.id
    monkeypatch.setattr(exports, "MAX_SNAPSHOT_BYTES", 1024)
    with pytest.raises(ArtifactError, match="snapshot"):
        await service(f).inspect(
            f.principal, exports.ExcelExportRequest(agency_id=f.agency.id, group_ids=[f.group.id])
        )
    await f.session.rollback()
    assert (await f.session.get(type(member), member_id)).confirmed_fields == retained
    assert not f.storage.objects
    # This proves safe rejection, not a bound on pre-check ORM materialization.


async def test_repeated_storage_cancellation_retains_temporary_file_and_export_lease(
    artifacts, monkeypatch
):
    f = artifacts
    f.session.add(person(f, 1))
    await f.session.commit()
    receipt, _, _ = await queue(f)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    async def delayed_put(source, *, key, size, sha256, media_type):
        def put():
            try:
                entered.set()
                assert release.wait(10)
                assert not source.closed
                source.seek(0)
                data = source.read()
                assert len(data) == size and hashlib.sha256(data).hexdigest() == sha256
                f.storage.objects[key] = (data, sha256, media_type)
            finally:
                finished.set()

        await run_bounded_storage_operations([lambda: asyncio.to_thread(put)], concurrency=1)

    monkeypatch.setattr(f.storage, "put_transfer", delayed_put)
    task = asyncio.create_task(generate(f, receipt))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and not finished.is_set()
            with pytest.raises(ArtifactError, match="capacity is busy"):
                await service(f).inspect(f.principal, None)
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await f.session.rollback()
    assert finished.is_set()
    # A completed private PUT can be orphaned by rollback; the TTL storage
    # lifecycle owns it. No business history or accessible artifact was saved.
    assert len(f.storage.objects) == 1
    for model in (MCPArtifactModel, PassportExportHistoryModel):
        assert await f.session.scalar(select(func.count()).select_from(model)) == 0
    with export_slot():
        assert exports._GENERATIONS.borrowed_tokens == 0
