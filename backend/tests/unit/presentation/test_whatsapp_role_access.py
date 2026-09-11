from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.presentation.api.v1.routes.client_groups import (
    create_client_group,
    list_whatsapp_broadcast_options_for_create,
)
from app.presentation.api.v1.routes.whatsapp import WHATSAPP_ROLES, router
from app.presentation.api.v1.schemas.client_group_schemas import (
    CreateClientGroupRequest,
)
from app.presentation.dependencies.auth import (
    WHATSAPP_BROADCAST_ROLES,
    require_role,
)


def _user(role: UserRole) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{role.value}-{uuid.uuid4()}@example.test",
        hashed_password="hash",
        full_name=role.value,
        role=role,
        agency_id=uuid.uuid4(),
    )


def test_whatsapp_broadcast_roles_include_office_staff() -> None:
    assert WHATSAPP_ROLES == WHATSAPP_BROADCAST_ROLES
    assert set(WHATSAPP_BROADCAST_ROLES) == {
        UserRole.SUPER_ADMIN,
        UserRole.AGENCY_ADMIN,
        UserRole.AGENCY_MANAGER,
        UserRole.AGENCY_STAFF,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("role", list(UserRole))
async def test_whatsapp_role_dependency_preserves_office_only_access(role: UserRole) -> None:
    guard = require_role(WHATSAPP_BROADCAST_ROLES)
    user = _user(role)

    if role in {UserRole.AGENCY_COORDINATOR, UserRole.CLIENT_MANAGER}:
        with pytest.raises(AuthorizationError):
            await guard(user=user)
    else:
        assert await guard(user=user) is user


@pytest.mark.asyncio
async def test_all_broadcast_route_guards_allow_staff_and_reject_coordinators() -> None:
    staff = _user(UserRole.AGENCY_STAFF)
    coordinator = _user(UserRole.AGENCY_COORDINATOR)
    guarded_routes = [route for route in router.routes if route.path != "/webhook"]
    assert guarded_routes
    for route in guarded_routes:
        guards = [
            dependency.call
            for dependency in route.dependant.dependencies
            if dependency.name == "current_user"
        ]
        assert len(guards) == 1, route.path
        assert await guards[0](user=staff) is staff, route.path
        with pytest.raises(AuthorizationError):
            await guards[0](user=coordinator)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.AGENCY_COORDINATOR, UserRole.CLIENT_MANAGER])
async def test_non_office_roles_cannot_read_broadcast_options(role: UserRole) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await list_whatsapp_broadcast_options_for_create(
            current_user=_user(role),
            session=SimpleNamespace(),  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.AGENCY_COORDINATOR, UserRole.CLIENT_MANAGER])
async def test_non_office_roles_cannot_link_broadcast_during_group_creation(role: UserRole) -> None:
    use_case = SimpleNamespace(execute=AsyncMock())
    request = CreateClientGroupRequest(
        name="Vietnam 2026",
        destination="Vietnam",
        travel_date=date(2026, 9, 1),
        return_date=date(2026, 9, 7),
        whatsapp_broadcast_group_ids=[uuid.uuid4()],
    )

    with pytest.raises(AuthorizationError):
        await create_client_group(
            request=request,
            current_user=_user(role),
            use_case=use_case,
            session=SimpleNamespace(),  # type: ignore[arg-type]
        )

    use_case.execute.assert_not_awaited()
