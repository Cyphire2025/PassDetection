from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from app.domain.entities.entities import User, UserRole
from app.presentation.api.v1.routes.tour_operations import (
    list_tour_operation_groups,
)


class _Rows:
    def scalars(self) -> _Rows:
        return self

    def all(self) -> list[object]:
        return []


def _manager() -> User:
    return User(
        id=uuid.uuid4(),
        email="manager@example.test",
        hashed_password="hash",
        full_name="Manager",
        role=UserRole.AGENCY_MANAGER,
        agency_id=uuid.uuid4(),
    )


@pytest.mark.asyncio
async def test_rooming_and_tour_ops_list_only_active_or_closed_groups() -> None:
    session = SimpleNamespace(execute=AsyncMock(return_value=_Rows()))

    response = await list_tour_operation_groups(
        current_user=_manager(),
        session=session,  # type: ignore[arg-type]
    )

    statement = session.execute.await_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "client_groups.status IN ('active', 'closed')" in sql
    assert "client_groups.status != 'deleted'" not in sql
    assert response == []
