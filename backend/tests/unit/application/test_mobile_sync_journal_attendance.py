from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.sync_journal import (
    append_attendance_realtime_change,
    append_attendance_realtime_invalidation,
)
from app.infrastructure.database.gc_mobile_models import MobileSyncChangeModel


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one(self) -> object:
        return self.value


@pytest.mark.asyncio
async def test_attendance_change_uses_disabled_anchor_and_existing_post_commit_journal() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    coordinator_id = uuid.uuid4()
    record_id = uuid.uuid4()
    access = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        group_id=group_id,
        access_generation=0,
    )
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _ScalarResult(None),
                _ScalarResult(access),
            ]
        ),
        add=Mock(),
        flush=AsyncMock(),
    )
    observed = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)

    change = await append_attendance_realtime_change(
        cast(AsyncSession, session),
        agency_id=agency_id,
        group_id=group_id,
        attendance_record_id=record_id,
        coordinator_user_id=coordinator_id,
        occurred_at=observed,
    )

    assert isinstance(change, MobileSyncChangeModel)
    assert change.id == record_id
    assert change.entity_type == "attendance_record"
    assert change.entity_id == record_id
    assert change.audience == "coordinator"
    assert change.payload == {}
    assert change.changed_by_user_id == coordinator_id
    assert change.version == int(observed.timestamp() * 1_000)
    session.add.assert_called_once_with(change)
    session.flush.assert_awaited_once()

    anchor_statement = session.execute.await_args_list[0].args[0]
    anchor_sql = str(anchor_statement.compile(dialect=postgresql.dialect())).lower()
    assert "insert into gc_group_access" in anchor_sql
    assert "on conflict (group_id) do nothing" in anchor_sql
    assert anchor_statement.compile(dialect=postgresql.dialect()).params["is_enabled"] is False

    access_statement = session.execute.await_args_list[1].args[0]
    access_sql = str(access_statement.compile(dialect=postgresql.dialect())).lower()
    assert "gc_group_access.agency_id" in access_sql
    assert "gc_group_access.group_id" in access_sql


@pytest.mark.asyncio
async def test_attendance_checkpoint_uses_unique_change_and_pii_free_payload() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    coordinator_id = uuid.uuid4()
    session_id = uuid.uuid4()
    access = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        group_id=group_id,
        access_generation=0,
    )
    database = SimpleNamespace(
        execute=AsyncMock(side_effect=[_ScalarResult(None), _ScalarResult(access)]),
        add=Mock(),
        flush=AsyncMock(),
    )
    observed = datetime(2026, 8, 25, 12, 5, tzinfo=UTC)

    change = await append_attendance_realtime_invalidation(
        cast(AsyncSession, database),
        agency_id=agency_id,
        group_id=group_id,
        entity_type="attendance_checkpoint",
        entity_id=session_id,
        changed_by_user_id=coordinator_id,
        occurred_at=observed,
    )

    assert isinstance(change, MobileSyncChangeModel)
    assert change.id != session_id
    assert change.entity_type == "attendance_checkpoint"
    assert change.entity_id == session_id
    assert change.audience == "coordinator"
    assert change.payload == {}
    assert change.changed_by_user_id == coordinator_id
    assert change.version == int(observed.timestamp() * 1_000)
