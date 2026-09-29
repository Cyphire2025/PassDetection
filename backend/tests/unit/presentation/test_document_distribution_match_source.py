"""Optional source bounds reject truncation while preserving canonical lock ordering."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.presentation.api.v1.routes.document_distribution_match_source import (
    _read_linked_document_match_source,
)


@pytest.mark.parametrize("lock", [False, True])
async def test_source_bound_is_in_sql_and_oversize_is_rejected_never_truncated(lock):
    result = MagicMock()
    result.all.return_value = [(None, None, None)] * 3
    result.scalars.return_value.all.return_value = [uuid.uuid4() for _ in range(3)]
    session = SimpleNamespace(execute=AsyncMock(return_value=result))
    group = SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4())
    with pytest.raises(HTTPException) as denied:
        await _read_linked_document_match_source(session, group=group, lock=lock, max_source_rows=2)
    assert denied.value.status_code == 413
    assert session.execute.await_count == 1
    statement = session.execute.await_args.args[0]
    assert "LIMIT" in str(statement)
    assert statement.compile().params["param_1"] == 3


async def test_default_source_contract_has_no_added_row_limit():
    result = MagicMock()
    result.all.return_value = []
    session = SimpleNamespace(execute=AsyncMock(return_value=result))
    group = SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4())
    source = await _read_linked_document_match_source(session, group=group, lock=False)
    assert source.recipients == () and not source.linked_broadcasts
    assert "LIMIT" not in str(session.execute.await_args.args[0])
