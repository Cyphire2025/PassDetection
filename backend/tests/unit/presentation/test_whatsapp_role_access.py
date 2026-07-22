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
from app.presentation.api.v1.routes.whatsapp import WHATSAPP_ROLES
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


def test_whatsapp_broadcast_roles_exclude_staff() -> None:
    assert WHATSAPP_ROLES == WHATSAPP_BROADCAST_ROLES
    assert UserRole.AGENCY_STAFF not in WHATSAPP_BROADCAST_ROLES
    assert set(WHATSAPP_BROADCAST_ROLES) == {
        UserRole.SUPER_ADMIN,
        UserRole.AGENCY_ADMIN,
        UserRole.AGENCY_MANAGER,
    }


@pytest.mark.asyncio
async def test_whatsapp_role_dependency_rejects_staff() -> None:
    guard = require_role(WHATSAPP_BROADCAST_ROLES)

    with pytest.raises(AuthorizationError):
        await guard(user=_user(UserRole.AGENCY_STAFF))

    manager = _user(UserRole.AGENCY_MANAGER)
    assert await guard(user=manager) is manager


@pytest.mark.asyncio
async def test_staff_cannot_read_broadcast_options() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await list_whatsapp_broadcast_options_for_create(
            current_user=_user(UserRole.AGENCY_STAFF),
            session=SimpleNamespace(),  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_staff_cannot_link_broadcast_during_group_creation() -> None:
    use_case = SimpleNamespace(execute=AsyncMock())
    request = CreateClientGroupRequest(
        name="Vietnam 2026",
        destination="Vietnam",
        travel_date=date(2026, 9, 1),
        return_date=date(2026, 9, 7),
        whatsapp_broadcast_group_ids=[uuid.uuid4()],
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_client_group(
            request=request,
            current_user=_user(UserRole.AGENCY_STAFF),
            use_case=use_case,
            session=SimpleNamespace(),  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 403
    use_case.execute.assert_not_awaited()
