from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository


@pytest.mark.asyncio
async def test_consume_valid_token_is_one_conditional_update_with_returning() -> None:
    session = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    consumed = MagicMock()
    result.scalar_one_or_none.return_value = consumed
    session.execute.return_value = result
    repository = RefreshTokenRepository(session)

    returned = await repository.consume_valid_token("refresh-token")

    statement = session.execute.await_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": False},
        )
    )
    assert sql.startswith("UPDATE refresh_tokens SET")
    assert "refresh_tokens.is_revoked IS false" in sql
    assert "refresh_tokens.expires_at >" in sql
    assert "RETURNING refresh_tokens.id" in sql
    assert returned is consumed


@pytest.mark.asyncio
async def test_consume_valid_token_returns_none_after_atomic_claim_is_lost() -> None:
    session = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result
    repository = RefreshTokenRepository(session)

    returned = await repository.consume_valid_token("already-consumed-token")

    assert returned is None
