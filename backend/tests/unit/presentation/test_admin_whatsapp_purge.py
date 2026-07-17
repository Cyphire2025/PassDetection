from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.presentation.api.v1.routes.admin import _delete_whatsapp_broadcast_data


class _DeleteResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


@pytest.mark.asyncio
async def test_whatsapp_purge_deletes_children_before_groups_without_committing() -> None:
    session = AsyncMock()
    session.execute.side_effect = [
        _DeleteResult(7),
        _DeleteResult(5),
        _DeleteResult(2),
        _DeleteResult(4),
        _DeleteResult(1),
    ]

    counts = await _delete_whatsapp_broadcast_data(session, agency_id=None)

    statements = [call.args[0] for call in session.execute.await_args_list]
    assert [statement.table.name for statement in statements] == [
        "whatsapp_message_logs",
        "whatsapp_recipient_message_states",
        "whatsapp_broadcast_support_contacts",
        "whatsapp_broadcast_recipients",
        "whatsapp_broadcast_groups",
    ]
    assert all(statement.whereclause is None for statement in statements)
    assert counts.message_logs == 7
    assert counts.delivery_states == 5
    assert counts.support_contacts == 2
    assert counts.recipients == 4
    assert counts.broadcast_groups == 1
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_whatsapp_purge_scopes_every_delete_to_the_admin_agency() -> None:
    agency_id = uuid.uuid4()
    session = AsyncMock()
    session.execute.side_effect = [_DeleteResult(0) for _ in range(5)]

    await _delete_whatsapp_broadcast_data(session, agency_id=agency_id)

    statements = [call.args[0] for call in session.execute.await_args_list]
    assert len(statements) == 5
    for statement in statements:
        compiled = statement.compile()
        assert statement.whereclause is not None
        assert agency_id in compiled.params.values()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_whatsapp_purge_stops_before_parent_deletes_when_a_child_delete_fails() -> None:
    session = AsyncMock()
    session.execute.side_effect = [
        _DeleteResult(3),
        RuntimeError("delivery ledger delete failed"),
    ]

    with pytest.raises(RuntimeError, match="delivery ledger delete failed"):
        await _delete_whatsapp_broadcast_data(session, agency_id=None)

    assert session.execute.await_count == 2
    session.commit.assert_not_awaited()
