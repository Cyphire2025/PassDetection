from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel


def _user(role: UserRole, agency_id: uuid.UUID | None = None) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{role.value}-{uuid.uuid4()}@example.com",
        hashed_password="hash",
        full_name=role.value,
        role=role,
        agency_id=agency_id,
    )


def _group(agency_id: uuid.UUID, *, created_by_user_id: uuid.UUID | None = None):
    return SimpleNamespace(id=uuid.uuid4(), agency_id=agency_id, created_by_user_id=created_by_user_id)


def _passport(agency_id: uuid.UUID, group_id: uuid.UUID):
    return SimpleNamespace(id=uuid.uuid4(), agency_id=agency_id, group_id=group_id)


@pytest.mark.asyncio
async def test_super_admin_can_view_cross_tenant_group() -> None:
    policy = AuthorizationPolicy(AsyncMock())
    user = _user(UserRole.SUPER_ADMIN, None)
    group = _group(uuid.uuid4())

    assert await policy.can_view_group(user, group) is True
    assert await policy.can_manage_group(user, group) is True


@pytest.mark.asyncio
async def test_agency_admin_is_limited_to_own_tenant() -> None:
    policy = AuthorizationPolicy(AsyncMock())
    agency_id = uuid.uuid4()
    user = _user(UserRole.AGENCY_ADMIN, agency_id)

    assert await policy.can_view_group(user, _group(agency_id)) is True
    assert await policy.can_view_group(user, _group(uuid.uuid4())) is False


@pytest.mark.asyncio
async def test_manager_can_view_every_group_in_own_agency() -> None:
    policy = AuthorizationPolicy(AsyncMock())
    agency_id = uuid.uuid4()
    manager = _user(UserRole.AGENCY_MANAGER, agency_id)
    owned_group = _group(agency_id, created_by_user_id=manager.id)
    other_manager_group = _group(agency_id, created_by_user_id=uuid.uuid4())

    assert await policy.can_view_group(manager, owned_group) is True
    assert await policy.can_view_group(manager, other_manager_group) is True
    assert await policy.can_view_group(manager, _group(uuid.uuid4())) is False


@pytest.mark.asyncio
async def test_manager_can_access_every_passport_in_own_agency() -> None:
    policy = AuthorizationPolicy(AsyncMock())
    agency_id = uuid.uuid4()
    manager = _user(UserRole.AGENCY_MANAGER, agency_id)
    passport = _passport(agency_id, uuid.uuid4())
    other_agency_passport = _passport(uuid.uuid4(), uuid.uuid4())

    assert await policy.can_view_passport(manager, passport) is True
    assert await policy.can_confirm_passport(manager, passport) is True
    assert (
        await policy.can_staff_approve_passport(manager, passport)
        is True
    )
    assert await policy.can_view_passport(manager, other_agency_passport) is False


@pytest.mark.asyncio
async def test_staff_direct_group_and_passport_access_respects_assignment() -> None:
    policy = AuthorizationPolicy(AsyncMock())
    agency_id = uuid.uuid4()
    staff = _user(UserRole.AGENCY_STAFF, agency_id)
    assigned_group = _group(agency_id, created_by_user_id=uuid.uuid4())
    unrelated_group = _group(agency_id, created_by_user_id=uuid.uuid4())
    assigned_passport = _passport(agency_id, assigned_group.id)
    unrelated_passport = _passport(agency_id, unrelated_group.id)

    policy.staff_can_access_group = AsyncMock(
        side_effect=lambda staff_id, group_id: (
            staff_id == staff.id and group_id == assigned_group.id
        )
    )

    assert await policy.can_view_group(staff, assigned_group) is True
    assert await policy.can_manage_group(staff, assigned_group) is True
    assert await policy.can_view_passport(staff, assigned_passport) is True
    assert await policy.can_view_group(staff, unrelated_group) is False
    assert await policy.can_view_passport(staff, unrelated_passport) is False


@pytest.mark.asyncio
async def test_removed_group_is_not_accessible_through_an_old_assignment() -> None:
    result = SimpleNamespace(scalar_one_or_none=lambda: None)
    session = SimpleNamespace(execute=AsyncMock(return_value=result))
    policy = AuthorizationPolicy(session)  # type: ignore[arg-type]

    assert await policy.staff_can_access_group(uuid.uuid4(), uuid.uuid4()) is False

    statement = session.execute.await_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "client_groups.status NOT IN ('archived', 'deleted')" in sql


def test_manager_passport_query_scope_is_the_whole_agency() -> None:
    agency_id = uuid.uuid4()
    manager = _user(UserRole.AGENCY_MANAGER, agency_id)

    statement = AuthorizationPolicy.apply_passport_visibility_scope(
        select(PassportSubmissionModel),
        manager,
    )
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert [from_clause.name for from_clause in statement.get_final_froms()] == [
        "passport_submissions"
    ]
    assert "passport_submissions.agency_id" in sql
    assert "passport_submissions.group_id IN" not in sql
    assert "manager_group_access.manager_id" not in sql


def test_manager_group_query_scope_is_the_whole_agency() -> None:
    agency_id = uuid.uuid4()
    manager = _user(UserRole.AGENCY_MANAGER, agency_id)

    statement = AuthorizationPolicy.apply_group_visibility_scope(
        select(ClientGroupModel),
        manager,
    )
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    where_sql = sql.split("WHERE", maxsplit=1)[1]
    assert "client_groups.agency_id" in where_sql
    assert "client_groups.created_by_user_id" not in where_sql
    assert "manager_group_access.manager_id" not in where_sql


def test_staff_passport_query_scope_remains_assignment_based() -> None:
    agency_id = uuid.uuid4()
    staff = _user(UserRole.AGENCY_STAFF, agency_id)

    statement = AuthorizationPolicy.apply_passport_visibility_scope(
        select(PassportSubmissionModel),
        staff,
    )
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "passport_submissions.agency_id" in sql
    assert "passport_submissions.group_id IN" in sql
    assert "manager_group_access.manager_id" in sql


@pytest.mark.asyncio
async def test_manager_can_manage_every_group_in_own_agency() -> None:
    policy = AuthorizationPolicy(AsyncMock())
    agency_id = uuid.uuid4()
    manager = _user(UserRole.AGENCY_MANAGER, agency_id)

    assert await policy.can_manage_group(manager, _group(agency_id, created_by_user_id=manager.id)) is True
    assert await policy.can_manage_group(manager, _group(agency_id, created_by_user_id=uuid.uuid4())) is True
    assert await policy.can_manage_group(manager, _group(uuid.uuid4())) is False


@pytest.mark.asyncio
async def test_coordinator_can_view_assigned_group_and_passenger_only() -> None:
    policy = AuthorizationPolicy(AsyncMock())
    agency_id = uuid.uuid4()
    coordinator = _user(UserRole.AGENCY_COORDINATOR, agency_id)
    group = _group(agency_id)
    passport = _passport(agency_id, group.id)
    other_passport = _passport(agency_id, group.id)

    policy.coordinator_has_group = AsyncMock(return_value=True)
    policy.coordinator_has_passenger = AsyncMock(
        side_effect=lambda _coordinator_id, _group_id, passenger_id: (
            passenger_id == passport.id
        )
    )

    assert await policy.can_view_group(coordinator, group) is True
    assert await policy.can_view_passport(coordinator, passport) is True
    assert await policy.can_view_passport(coordinator, other_passport) is False
    assert await policy.can_confirm_passport(coordinator, passport) is False
    assert await policy.can_export_data(coordinator, group) is False


@pytest.mark.asyncio
async def test_coordinator_scan_uses_group_assignment_not_session_or_passenger_ownership() -> None:
    policy = AuthorizationPolicy(AsyncMock())
    agency_id = uuid.uuid4()
    coordinator = _user(UserRole.AGENCY_COORDINATOR, agency_id)
    group_id = uuid.uuid4()
    passenger = _passport(agency_id, group_id)
    own_session = SimpleNamespace(agency_id=agency_id, group_id=group_id, created_by_user_id=coordinator.id)
    other_session = SimpleNamespace(agency_id=agency_id, group_id=group_id, created_by_user_id=uuid.uuid4())

    policy.coordinator_has_group = AsyncMock(
        side_effect=lambda coordinator_id, assigned_group_id: (
            coordinator_id == coordinator.id and assigned_group_id == group_id
        )
    )

    assert await policy.can_scan_passenger(coordinator, own_session, passenger) is True
    assert await policy.can_scan_passenger(coordinator, other_session, passenger) is True
    assert await policy.can_scan_passenger(coordinator, own_session, _passport(uuid.uuid4(), group_id)) is False


def test_coordinator_passport_query_scope_remains_passenger_specific() -> None:
    agency_id = uuid.uuid4()
    coordinator = _user(UserRole.AGENCY_COORDINATOR, agency_id)

    statement = AuthorizationPolicy.apply_passport_visibility_scope(
        select(PassportSubmissionModel),
        coordinator,
    )
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "passport_submissions.id IN" in sql
    assert "coordinator_assignments.passenger_id" in sql
    assert "coordinator_group_assignments.group_id" not in sql


@pytest.mark.asyncio
async def test_delete_policy_separates_archive_from_permanent_delete() -> None:
    policy = AuthorizationPolicy(AsyncMock())
    agency_id = uuid.uuid4()
    admin = _user(UserRole.AGENCY_ADMIN, agency_id)
    manager = _user(UserRole.AGENCY_MANAGER, agency_id)
    group = _group(agency_id, created_by_user_id=manager.id)

    assert await policy.can_delete_data(admin, group) is True
    assert await policy.can_delete_data(admin, group, permanent=True) is True
    assert await policy.can_delete_data(manager, group) is True
    assert await policy.can_delete_data(manager, group, permanent=True) is False

    other_manager_group = _group(
        agency_id,
        created_by_user_id=uuid.uuid4(),
    )
    assert await policy.can_delete_data(manager, other_manager_group) is True
    assert await policy.can_delete_data(manager, _group(uuid.uuid4())) is False
