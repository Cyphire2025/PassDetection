"""Frozen checkpoints must detect changes under the same submission ID."""

import io
import json
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from openpyxl import load_workbook

from app.application.use_cases.passports.export_changes import export_changes
from app.domain.entities.entities import PassportSubmission
from app.infrastructure.export.passport_excel_exporter import PassportExcelExporter
from app.infrastructure.export.passport_image_zip_exporter import PassportImageZipExporter


def submission():
    return PassportSubmission.create(group_id=uuid.uuid4(), agency_id=uuid.uuid4(),
        client_name="Synthetic Traveller", client_email=None, image_s3_key="synthetic/front.png")


def checkpoint(items):
    return SimpleNamespace(snapshot_submission_ids=[str(row.id) for row in items],
        artifact_metadata={"submission_revisions": export_changes(items, None).revisions})


def test_same_id_field_revision_and_removal_are_exported_without_unchanged_people():
    unchanged, corrected, removed, added = [submission() for _ in range(4)]
    baseline = checkpoint([unchanged, corrected, removed])
    corrected.confirmed_fields = {"passport_number": "NEW00123"}
    delta = export_changes([unchanged, corrected, added], baseline)
    assert [(row["submission_id"], row["change"]) for row in delta.rows] == [
        (str(corrected.id), "changed"), (str(added.id), "added"), (str(removed.id), "removed")]
    assert delta.included_ids == {corrected.id, added.id}
    # A second checkpoint is cumulative even though its file has only two people.
    next_baseline = SimpleNamespace(snapshot_submission_ids=list(delta.revisions),
        artifact_metadata={"submission_revisions": delta.revisions})
    assert export_changes([unchanged, corrected, added], next_baseline).rows == []


def test_legacy_checkpoint_detects_later_correction_by_timestamp():
    item = submission()
    prepared = datetime.now(UTC)
    baseline = SimpleNamespace(snapshot_submission_ids=[str(item.id)], created_at=prepared)
    item.updated_at = prepared + timedelta(seconds=1)
    assert export_changes([item], baseline).rows[0]["change"] == "changed"


def test_removed_only_workbook_contains_explicit_change_sheet():
    item = submission()
    changes = export_changes([], checkpoint([item]))
    content = PassportExcelExporter().export_group([], group_name="Synthetic", change_rows=changes.rows)
    book = load_workbook(io.BytesIO(content))
    assert book["Changes"]["A2"].value == str(item.id)
    assert book["Changes"]["B2"].value == "removed"


@pytest.mark.asyncio
async def test_removed_only_zip_contains_manifest_without_storage_fetch():
    item = submission()
    changes = export_changes([], checkpoint([item]))
    storage = AsyncMock()
    spool, entry_count, total = await PassportImageZipExporter().export_group([], group_name="Synthetic",
        staff_code_enabled=False, storage=storage, change_rows=changes.rows)
    try:
        with zipfile.ZipFile(spool) as archive:
            manifest = archive.read("Synthetic_PASSPORT_IMAGES/changes.json")
            assert json.loads(manifest)["changes"][0]["change"] == "removed"
            assert entry_count == 1 and total == len(manifest)
        storage.get_file.assert_not_awaited()
    finally:
        spool.close()
