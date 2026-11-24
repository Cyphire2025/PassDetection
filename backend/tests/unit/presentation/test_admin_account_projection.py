from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.domain.entities.entities import User, UserRole
from app.presentation.api.v1.routes.admin import list_managers


class _Rows:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def scalars(self) -> _Rows:
        return self

    def all(self) -> list[object]:
        return self.rows


class _CountedAccess:
    def __init__(self, manager_id: uuid.UUID, group_id: uuid.UUID, reads: list[int]) -> None:
        self._manager_id = manager_id
        self.group_id = group_id
        self.reads = reads

    @property
    def manager_id(self) -> uuid.UUID:
        self.reads[0] += 1
        return self._manager_id


def _fixture(
    manager_count: int = 12,
    group_count: int = 160,
    access_count: int = 240,
) -> tuple[
    SimpleNamespace,
    User,
    list[SimpleNamespace],
    list[SimpleNamespace],
    list[tuple[uuid.UUID, uuid.UUID]],
    list[int],
]:
    agency_id = uuid.UUID(int=1)
    managers = [
        SimpleNamespace(
            id=uuid.UUID(int=100 + index),
            full_name=f"Synthetic manager {index}",
            email=f"manager-{index}@example.test",
            role="agency_manager",
            agency_id=agency_id,
            is_active=True,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            last_login_at=None,
        )
        for index in range(manager_count)
    ]
    groups = [
        SimpleNamespace(
            id=uuid.UUID(int=1000 + index),
            agency_id=agency_id,
            name=f"Synthetic group {index}",
            status="archived" if index % 9 == 0 else "active",
            created_by_user_id=managers[index % manager_count].id,
        )
        for index in range(group_count)
    ]
    raw_access = [
        (managers[index % manager_count].id, groups[index % group_count].id)
        for index in range(access_count)
    ]
    reads = [0]
    access = [_CountedAccess(manager_id, group_id, reads) for manager_id, group_id in raw_access]
    states = [SimpleNamespace(user_id=managers[0].id, credential_state="invited")]
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Rows(managers),
                _Rows(groups),
                _Rows(access),
                _Rows(states),
            ]
        )
    )
    actor = User(
        id=uuid.UUID(int=2),
        email="synthetic-owner@example.test",
        hashed_password="not-a-password",
        full_name="Synthetic owner",
        role=UserRole.SUPER_ADMIN,
        agency_id=None,
    )
    return session, actor, managers, groups, raw_access, reads


@pytest.mark.asyncio
async def test_manager_list_preserves_ownership_membership_order_and_invitation_state() -> None:
    session, actor, managers, groups, access, _ = _fixture()
    response = await list_managers(current_user=actor, session=session)  # type: ignore[arg-type]

    assert [row.id for row in response] == [manager.id for manager in managers]
    for row in response:
        assert [group.id for group in row.created_groups] == [
            group.id for group in groups if group.created_by_user_id == row.id
        ]
        assert [group.id for group in row.assigned_groups] == [
            group.id
            for manager_id, group_id in access
            for group in groups
            if manager_id == row.id and group.id == group_id
        ]
    assert response[0].credential_state == "invited"
    assert all(row.credential_state == "active" for row in response[1:])
    assert any(group.status == "archived" for row in response for group in row.created_groups)
    assert session.execute.await_count == 4


@pytest.mark.asyncio
async def test_manager_projection_does_not_rescan_every_membership_for_every_group_and_account() -> (
    None
):
    session, actor, _, _, _, reads = _fixture()
    response = await list_managers(current_user=actor, session=session)  # type: ignore[arg-type]

    assert len(response) == 12
    assert sum(len(row.assigned_groups) for row in response) == 240
    assert session.execute.await_count == 4
    assert reads[0] <= 3000
