from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories.client_group_repository import (
    ClientGroupRepository,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "lookup_value"),
    [
        ("get_by_id", uuid.uuid4()),
        ("get_by_token", "public-group-token"),
    ],
)
async def test_client_group_mutation_reads_request_a_row_lock(
    method_name: str,
    lookup_value: object,
) -> None:
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = result
    repository = ClientGroupRepository(session)

    method = getattr(repository, method_name)
    assert await method(lookup_value, for_update=True) is None

    statement = session.execute.await_args.args[0]
    assert "FOR UPDATE" in str(statement)
