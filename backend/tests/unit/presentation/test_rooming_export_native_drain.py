"""Route cancellation must drain its already-running detached workbook render."""

from __future__ import annotations

import asyncio
import threading
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.application.use_cases.rooming.prepare_excel import PreparedRoomingExcel
from app.presentation.api.v1.routes import rooming_exports


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["rooming_list", "checkins"])
async def test_cancelled_rooming_export_drains_native_worker_before_return(kind, monkeypatch):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    prepared = PreparedRoomingExcel(
        kind=kind,
        arguments={},
        scope=(),
        filename="synthetic.xlsx",
        passenger_count=1,
        priority_fields=[],
    )

    def render(_self):
        started.set()
        try:
            assert release.wait(timeout=5)
            return b"PK-synthetic-workbook"
        finally:
            finished.set()

    monkeypatch.setattr(PreparedRoomingExcel, "render_sync", render)
    monkeypatch.setattr(
        rooming_exports,
        "_get_rooming_hotel",
        AsyncMock(return_value=(SimpleNamespace(), SimpleNamespace())),
    )
    prepare_name = "prepare_rooming_list" if kind == "rooming_list" else "prepare_checkins"
    monkeypatch.setattr(rooming_exports, prepare_name, AsyncMock(return_value=prepared))
    route = (
        rooming_exports.export_hotel_rooming_list
        if kind == "rooming_list"
        else rooming_exports.export_hotel_checkins
    )
    task = asyncio.create_task(
        route(
            hotel_id=uuid.uuid4(),
            request=SimpleNamespace(),
            current_user=SimpleNamespace(),
            session=AsyncMock(),
        )
    )
    try:
        assert await asyncio.to_thread(started.wait, 3)
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=0.05)
        returned_before_worker_finished = bool(done)
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await asyncio.to_thread(finished.wait, 3)

    assert not returned_before_worker_finished
