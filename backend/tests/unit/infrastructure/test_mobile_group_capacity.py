from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.exceptions.exceptions import EntityNotFoundError, ValidationError
from app.infrastructure.mobile_group_capacity import (
    SqlAlchemyGroupPassengerCapacityGuard,
)


@pytest.mark.asyncio
async def test_group_capacity_lock_is_tenant_scoped_and_fail_closed() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    session = MagicMock()
    session.scalar = AsyncMock(return_value=None)
    guard = SqlAlchemyGroupPassengerCapacityGuard(session)

    with pytest.raises(EntityNotFoundError):
        await guard.lock_group(agency_id=agency_id, group_id=group_id)

    statement = session.scalar.await_args.args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert agency_id.hex in sql
    assert group_id.hex in sql
    assert "client_groups.deleted_at IS NULL" in sql
    assert "FOR UPDATE" in sql


@pytest.mark.asyncio
async def test_group_capacity_accepts_last_slot_and_rejects_overflow() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    session = MagicMock()
    session.scalar = AsyncMock(side_effect=[9_999, 10_000])
    guard = SqlAlchemyGroupPassengerCapacityGuard(session)
    settings = SimpleNamespace(mobile=SimpleNamespace(max_group_passengers=10_000))

    with patch(
        "app.infrastructure.mobile_group_capacity.get_settings",
        return_value=settings,
    ):
        await guard.assert_available(
            agency_id=agency_id,
            group_id=group_id,
            additional_passengers=1,
        )
        with pytest.raises(ValidationError, match="at most 10,000") as caught:
            await guard.assert_available(
                agency_id=agency_id,
                group_id=group_id,
                additional_passengers=1,
            )

    assert caught.value.field == "group_capacity"
    statement = session.scalar.await_args_list[0].args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "passport_submissions.agency_id" in sql
    assert "passport_submissions.group_id" in sql


@pytest.mark.asyncio
async def test_existing_group_over_capacity_cannot_be_newly_enabled() -> None:
    session = MagicMock()
    session.scalar = AsyncMock(return_value=10_001)
    guard = SqlAlchemyGroupPassengerCapacityGuard(session)
    settings = SimpleNamespace(mobile=SimpleNamespace(max_group_passengers=10_000))

    with (
        patch(
            "app.infrastructure.mobile_group_capacity.get_settings",
            return_value=settings,
        ),
        pytest.raises(ValidationError, match="at most 10,000"),
    ):
        await guard.assert_available(
            agency_id=uuid.uuid4(),
            group_id=uuid.uuid4(),
            additional_passengers=0,
        )
