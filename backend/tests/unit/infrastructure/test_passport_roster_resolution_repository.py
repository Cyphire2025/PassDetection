from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.infrastructure.repositories.passport_roster_resolution_repository import (
    active_replacement_resolution_id_for_recipient,
    suppress_active_replacement_recipients,
)


def _scalars_result(values: list[object]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


@pytest.mark.asyncio
async def test_later_same_phone_row_is_attached_to_active_replacement() -> None:
    agency_id = uuid.uuid4()
    broadcast_id = uuid.uuid4()
    resolution_id = uuid.uuid4()
    recipient = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        broadcast_group_id=broadcast_id,
        normalized_phone_number="+919876543210",
        removed_at=None,
        suppressed_by_roster_resolution_id=None,
    )
    resolution = SimpleNamespace(
        id=resolution_id,
        suppressed_recipient_ids=["existing-recipient-id"],
    )
    matches_result = MagicMock()
    matches_result.all.return_value = [(recipient, resolution)]
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[
            _scalars_result([broadcast_id]),
            matches_result,
            MagicMock(),
            MagicMock(),
            MagicMock(),
        ]
    )
    now = datetime.now(tz=UTC)

    suppressed = await suppress_active_replacement_recipients(
        session,
        agency_id=agency_id,
        broadcast_group_ids=[broadcast_id],
        now=now,
    )

    assert suppressed == [recipient]
    assert recipient.removed_at == now
    assert recipient.suppressed_by_roster_resolution_id == resolution_id
    assert resolution.suppressed_recipient_ids == [
        "existing-recipient-id",
        str(recipient.id),
    ]
    assert session.execute.await_count == 5


@pytest.mark.asyncio
async def test_worker_guard_resolves_replacement_by_linked_phone_identity() -> None:
    resolution_id = uuid.uuid4()
    result = MagicMock()
    result.scalar_one_or_none.return_value = resolution_id
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    recipient = SimpleNamespace(
        agency_id=uuid.uuid4(),
        broadcast_group_id=uuid.uuid4(),
        normalized_phone_number="+919876543210",
    )

    matched = await active_replacement_resolution_id_for_recipient(
        session,
        recipient=recipient,
    )

    assert matched == resolution_id
    statement = session.execute.await_args.args[0]
    rendered = str(statement)
    assert "passport_roster_resolutions.status" in rendered
    assert "client_group_whatsapp_broadcast_links" in rendered
    assert "replaced_recipient_normalized_phone" in rendered
    assert "whatsapp_broadcast_recipients" not in rendered
