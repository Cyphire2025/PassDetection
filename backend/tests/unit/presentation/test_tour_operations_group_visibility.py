from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.domain.entities.entities import User, UserRole
from app.domain.value_objects.trip_lifecycle import trip_has_ended
from app.presentation.api.v1.routes import tour_operations as routes
from app.presentation.api.v1.routes.tour_operations import (
    list_tour_operation_groups,
)
from app.presentation.api.v1.schemas.tour_operations_schemas import AssignGroupCoordinatorsRequest


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
    assert "coalesce(client_groups.return_date, client_groups.travel_date)" not in sql
    assert response == []


@pytest.mark.asyncio
async def test_assignment_picker_uses_trip_dates_without_losing_agency_scope() -> None:
    manager = _manager()
    session = SimpleNamespace(execute=AsyncMock(return_value=_Rows()))
    await list_tour_operation_groups(
        current_user=manager,
        session=session,  # type: ignore[arg-type]
        assignment_eligible_only=True,
    )
    sql = str(session.execute.await_args.args[0].compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
    ))
    assert "coalesce(client_groups.return_date, client_groups.travel_date)" in sql
    assert "IS NOT NULL" in sql
    assert "timezone" in sql
    assert str(manager.agency_id) in sql


@pytest.mark.asyncio
@pytest.mark.parametrize("end_date,expected_status", [(date(2026, 9, 5), 409), (None, 400)])
async def test_past_and_undated_trips_reject_new_assignments_before_any_write(
    monkeypatch: pytest.MonkeyPatch, end_date: date | None, expected_status: int,
) -> None:
    manager = _manager()
    group = SimpleNamespace(
        id=uuid.uuid4(), travel_date=end_date, return_date=None, timezone="Asia/Kolkata",
    )
    manageable = AsyncMock(return_value=group)
    monkeypatch.setattr(routes, "_get_manageable_group", manageable)
    monkeypatch.setattr(routes, "trip_has_ended", lambda **values: trip_has_ended(
        **values, now=datetime(2026, 9, 6, 0, tzinfo=UTC),
    ))
    session = SimpleNamespace(execute=AsyncMock(), flush=AsyncMock(), add=Mock())
    with pytest.raises(HTTPException) as error:
        await routes.assign_group_coordinators(
            group.id, AssignGroupCoordinatorsRequest(coordinator_ids=[uuid.uuid4()]),
            current_user=manager, session=session,  # type: ignore[arg-type]
        )
    assert error.value.status_code == expected_status
    assert manageable.await_args.kwargs["lock_for_update"] is True
    session.execute.assert_not_awaited()
    session.flush.assert_not_awaited()
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_completed_trip_can_still_be_explicitly_unassigned_without_deleting_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager()
    group = SimpleNamespace(
        id=uuid.uuid4(), travel_date=date(2000, 1, 1), return_date=None,
        timezone="Asia/Kolkata",
    )
    monkeypatch.setattr(routes, "_get_manageable_group", AsyncMock(return_value=group))
    monkeypatch.setattr(routes, "_group_responses", AsyncMock(return_value=[group]))
    session = SimpleNamespace(execute=AsyncMock(), flush=AsyncMock(), add=Mock())
    result = await routes.assign_group_coordinators(
        group.id, AssignGroupCoordinatorsRequest(coordinator_ids=[]),
        current_user=manager, session=session,  # type: ignore[arg-type]
    )
    assert result is group
    assert session.execute.await_count == 2
    for call in session.execute.await_args_list:
        sql = str(call.args[0].compile(dialect=postgresql.dialect()))
        assert sql.startswith("UPDATE coordinator_")
        assert "unassigned_at" in sql
        assert call.args[0].compile().params["active"] is False
    session.add.assert_not_called()


def test_departed_trip_remains_assignable_until_its_return_day_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(routes, "trip_has_ended", lambda **values: trip_has_ended(
        **values, now=datetime(2026, 9, 6, 17, 59, tzinfo=UTC),
    ))
    group = SimpleNamespace(
        travel_date=date(2026, 9, 1), return_date=date(2026, 9, 6), timezone="Asia/Kolkata",
    )
    routes._require_assignable_trip(group)  # type: ignore[arg-type]
