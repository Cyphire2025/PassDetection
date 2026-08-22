from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.domain.entities.entities import GroupStatus, User, UserRole
from app.infrastructure.database.models import ManagerGroupAccessModel
from app.presentation.api.v1.routes.admin import (
    assign_staff_groups,
    list_admin_groups,
)
from app.presentation.api.v1.schemas.operations_schemas import (
    AssignManagerGroupsRequest,
)


class _Rows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> _Rows:
        return self

    def all(self) -> list[object]:
        return self._rows

    def scalar_one_or_none(self) -> object | None:
        return self._rows[0] if self._rows else None


def _user(role: UserRole, agency_id: uuid.UUID | None = None) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{role.value}-{uuid.uuid4()}@example.test",
        hashed_password="hash",
        full_name=role.value,
        role=role,
        agency_id=agency_id,
    )


def _group(*, agency_id: uuid.UUID, status: GroupStatus = GroupStatus.ACTIVE) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        name="Vietnam 2026",
        status=status.value,
        created_by_user_id=uuid.uuid4(),
    )


@pytest.mark.asyncio
async def test_admin_group_choices_exclude_removed_groups_and_include_agency_id() -> None:
    agency_id = uuid.uuid4()
    group = _group(agency_id=agency_id)
    session = SimpleNamespace(execute=AsyncMock(return_value=_Rows([group])))

    response = await list_admin_groups(
        current_user=_user(UserRole.SUPER_ADMIN),
        session=session,  # type: ignore[arg-type]
    )

    statement = session.execute.await_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "client_groups.status NOT IN ('archived', 'deleted')" in sql
    assert response[0].agency_id == agency_id


@pytest.mark.asyncio
async def test_removed_group_cannot_be_assigned_to_staff() -> None:
    agency_id = uuid.uuid4()
    staff = SimpleNamespace(id=uuid.uuid4(), agency_id=agency_id)
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=[_Rows([staff]), _Rows([])]),
    )

    with pytest.raises(HTTPException) as exc_info:
        await assign_staff_groups(
            staff_id=staff.id,
            body=AssignManagerGroupsRequest(group_ids=[uuid.uuid4()]),
            current_user=_user(UserRole.SUPER_ADMIN),
            session=session,  # type: ignore[arg-type]
        )

    assignment_statement = session.execute.await_args_list[1].args[0]
    sql = str(
        assignment_statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "client_groups.status NOT IN ('archived', 'deleted')" in sql
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_valid_staff_assignment_is_returned_immediately() -> None:
    agency_id = uuid.uuid4()
    staff_id = uuid.uuid4()
    staff = SimpleNamespace(
        id=staff_id,
        agency_id=agency_id,
        full_name="Mohit",
        email="mohit@example.test",
        role=UserRole.AGENCY_STAFF.value,
        is_active=True,
        created_at=datetime.now(UTC),
        last_login_at=None,
    )
    group = _group(agency_id=agency_id)
    access = SimpleNamespace(group_id=group.id)
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Rows([staff]),
                _Rows([group]),
                _Rows([]),
                _Rows([group]),
                _Rows([access]),
                _Rows([]),
            ]
        ),
        add=Mock(),
        flush=AsyncMock(),
    )

    response = await assign_staff_groups(
        staff_id=staff_id,
        body=AssignManagerGroupsRequest(group_ids=[group.id]),
        current_user=_user(UserRole.SUPER_ADMIN),
        session=session,  # type: ignore[arg-type]
    )

    added_access = session.add.call_args.args[0]
    assert isinstance(added_access, ManagerGroupAccessModel)
    assert added_access.manager_id == staff_id
    assert added_access.group_id == group.id
    assert response.assigned_groups[0].id == group.id
    assert response.assigned_groups[0].agency_id == agency_id
