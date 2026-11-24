"""The web route owns a rendered ZIP until its streaming response takes over."""

from __future__ import annotations

import asyncio
import tempfile
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.presentation.api.v1.routes.passport_routes import image_exports as route


@pytest.fixture
def export_context(monkeypatch: pytest.MonkeyPatch):
    agency_id, group_id, history_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    actor = User(
        id=uuid.uuid4(), email="synthetic@example.test", hashed_password="synthetic",
        full_name="Synthetic staff", role=UserRole.AGENCY_ADMIN, agency_id=agency_id,
    )
    group = SimpleNamespace(id=group_id, name="Synthetic group")
    session = AsyncMock(spec=AsyncSession)
    spool = tempfile.SpooledTemporaryFile(max_size=1, mode="w+b")
    spool.write(b"synthetic ZIP bytes")
    prepared = SimpleNamespace(
        history_fields={"group_id": group_id, "artifact_metadata": {"synthetic": True}},
        render=AsyncMock(return_value=(spool, 2, 19)),
    )
    record = AsyncMock(return_value=SimpleNamespace(id=history_id))
    monkeypatch.setattr(route, "ClientGroupRepository", lambda session: SimpleNamespace(
        get_by_id=AsyncMock(return_value=group),
    ))
    monkeypatch.setattr(route, "AuthorizationPolicy", lambda session: SimpleNamespace(
        require_export_data=AsyncMock(),
    ))
    monkeypatch.setattr(route, "_require_new_export_request", AsyncMock())
    monkeypatch.setattr(route, "prepare_image_export", AsyncMock(return_value=prepared))
    monkeypatch.setattr(route, "PassportExportHistoryRepository", lambda session: SimpleNamespace(record=record))
    monkeypatch.setattr(route, "MinioStorageRepository", lambda: object())
    monkeypatch.setattr(route, "PassportImageZipExporter", lambda: object())
    context = SimpleNamespace(
        actor=actor, group=group, session=session, spool=spool,
        record=record, prepared=prepared, history_id=history_id,
    )
    try:
        yield context
    finally:
        spool.close()


async def invoke(context):
    return await route.export_passport_images_by_group(
        context.group.id, export_mode="all", baseline_export_id=None,
        request_id=uuid.uuid4(), current_user=context.actor, session=context.session,
    )


@pytest.mark.parametrize("boundary", [
    "history_error", "history_cancel", "history_integrity", "commit_error", "commit_cancel",
])
async def test_failed_history_or_commit_releases_rendered_spool(export_context, boundary):
    context = export_context
    if boundary == "history_integrity":
        failure = IntegrityError("synthetic history insert", {}, RuntimeError("duplicate"))
        expected = HTTPException
    elif boundary.endswith("cancel"):
        failure = asyncio.CancelledError()
        expected = asyncio.CancelledError
    else:
        failure = RuntimeError("synthetic persistence outage")
        expected = RuntimeError
    target = context.record if boundary.startswith("history") else context.session.commit
    target.side_effect = failure

    with pytest.raises(expected) as raised:
        await invoke(context)

    if boundary == "history_integrity":
        assert raised.value.status_code == 409
        assert "already prepared" in raised.value.detail
        assert raised.value.__cause__ is failure
    else:
        assert raised.value is failure
    assert context.spool.closed
    if boundary.startswith("history"):
        context.session.commit.assert_not_awaited()
    else:
        context.record.assert_awaited_once()
        context.session.commit.assert_awaited_once()


async def test_success_transfers_spool_to_stream_after_history_commit(export_context):
    context = export_context
    response = await invoke(context)

    assert not context.spool.closed
    context.record.assert_awaited_once()
    context.session.commit.assert_awaited_once()
    assert response.headers["x-passport-export-history-id"] == str(context.history_id)
    assert response.headers["content-length"] == "19"
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["x-content-type-options"] == "nosniff"
    chunks = [chunk async for chunk in response.body_iterator]
    assert b"".join(chunks) == b"synthetic ZIP bytes"
    assert context.spool.closed
