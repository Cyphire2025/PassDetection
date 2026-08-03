from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.mobile.sync_journal import append_mobile_sync_change


def _access() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        access_generation=3,
    )


@pytest.mark.asyncio
async def test_sync_journal_preserves_immediate_flush_by_default() -> None:
    session = MagicMock()
    session.flush = AsyncMock()

    change = await append_mobile_sync_change(
        session,
        access=_access(),
        entity_type="coordinator_passenger",
        entity_id=uuid.uuid4(),
        operation="upsert",
        version=1,
        changed_by_user_id=uuid.uuid4(),
    )

    session.add.assert_called_once_with(change)
    session.flush.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_sync_journal_allows_explicit_bounded_batch_flush() -> None:
    session = MagicMock()
    session.flush = AsyncMock()
    change_id = uuid.uuid4()

    change = await append_mobile_sync_change(
        session,
        access=_access(),
        change_id=change_id,
        entity_type="coordinator_passenger",
        entity_id=uuid.uuid4(),
        operation="upsert",
        version=1,
        changed_by_user_id=uuid.uuid4(),
        flush=False,
    )

    assert change.id == change_id
    session.add.assert_called_once_with(change)
    session.flush.assert_not_awaited()
