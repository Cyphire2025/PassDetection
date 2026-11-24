"""Tracking snapshot hashing must not deep-copy the complete source graph."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from dataclasses import replace

import pytest

from app.application.mcp import tracking_exports
from app.application.mcp.tracking_exports import TrackingExportRequest
from app.application.use_cases.passports.prepare_group_excel import (
    ExcelPreparationError,
    _canonical,
)
from tests.integration.test_mcp_artifacts import artifacts as artifacts
from tests.integration.test_mcp_tracking_exports import seed, service


@pytest.mark.parametrize("snapshot_limit", [None, 1])
async def test_actual_tracking_preparation_avoids_canonical_source_deepcopies(
    artifacts, monkeypatch, snapshot_limit
):
    fixture = await seed(artifacts)
    expected_ids = {row.id for row in fixture.passengers}
    original_copy = copy.deepcopy
    canonical_copy_calls = 0

    def counted_copy(value, *args, **kwargs):
        nonlocal canonical_copy_calls
        frame = sys._getframe(1)
        try:
            while frame is not None:
                if frame.f_code is _canonical.__code__:
                    canonical_copy_calls += 1
                    break
                frame = frame.f_back
        finally:
            del frame
        return original_copy(value, *args, **kwargs)

    monkeypatch.setattr(copy, "deepcopy", counted_copy)
    if snapshot_limit is not None:
        monkeypatch.setattr(tracking_exports, "MAX_SNAPSHOT_BYTES", snapshot_limit)
    request = TrackingExportRequest(agency_id=fixture.agency.id, group_id=fixture.group.id)
    if snapshot_limit is None:
        result = await service(fixture).prepare(fixture.principal, request)
        assert {row.id for row in result.submissions} == expected_ids
        assert result.render_arguments["group_name"] == fixture.group.name
        assert len(result.revision) == 64 and result.history_fields == {}
    else:
        with pytest.raises(ExcelPreparationError) as rejected:
            await service(fixture).prepare(fixture.principal, request)
        assert rejected.value.status_code == 413
        assert rejected.value.detail == "Tracking exceeds the snapshot size limit"
    assert canonical_copy_calls == 0


@pytest.mark.parametrize("status", ["all", "submitted", "not_submitted", "unmatched_submission"])
@pytest.mark.parametrize("selected_broadcast", [False, True])
async def test_tracking_revision_and_exact_byte_limit_match_existing_canonical_format(
    artifacts, monkeypatch, status, selected_broadcast
):
    fixture = await seed(artifacts)
    fixture.group.name = 'Synthetic Café "Group"'
    await fixture.session.commit()
    instance = service(fixture)
    source_rows = instance.support.tracking_rows
    captured = {}

    async def capture_source(session, *, group, submissions):
        linked, rows = await source_rows(session, group=group, submissions=submissions)
        captured.update(group=group, submissions=submissions, linked=linked, rows=rows)
        return linked, rows

    instance.support = replace(instance.support, tracking_rows=capture_source)
    request = TrackingExportRequest(
        agency_id=fixture.agency.id,
        group_id=fixture.group.id,
        status=status,
        broadcast_id=fixture.broadcast.id if selected_broadcast else None,
    )
    prepared = await instance.prepare(fixture.principal, request)
    payload = json.dumps(
        _canonical(
            {
                **captured,
                "status": status,
                "broadcast_id": request.broadcast_id,
                "arguments": prepared.render_arguments,
            }
        ),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    assert prepared.revision == hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(tracking_exports, "MAX_SNAPSHOT_BYTES", len(payload))
    assert (await instance.prepare(fixture.principal, request)).revision == prepared.revision
    monkeypatch.setattr(tracking_exports, "MAX_SNAPSHOT_BYTES", len(payload) - 1)
    with pytest.raises(ExcelPreparationError) as rejected:
        await instance.prepare(fixture.principal, request)
    assert rejected.value.status_code == 413
    assert rejected.value.detail == "Tracking exceeds the snapshot size limit"
    assert not fixture.storage.objects
