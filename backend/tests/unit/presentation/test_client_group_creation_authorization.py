from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.domain.entities.entities import UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.presentation.api.v1.routes.client_groups import (
    _require_client_group_creation_access,
)


def _session_with_settings(value: dict[str, object] | None) -> SimpleNamespace:
    result = Mock()
    result.scalar_one_or_none.return_value = value
    return SimpleNamespace(execute=AsyncMock(return_value=result))


@pytest.mark.asyncio
async def test_coordinator_cannot_create_upload_group() -> None:
    session = _session_with_settings(None)

    with pytest.raises(AuthorizationError, match="cannot create"):
        await _require_client_group_creation_access(
            SimpleNamespace(role=UserRole.AGENCY_COORDINATOR),
            session,
        )

    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_manager_creation_respects_platform_setting() -> None:
    session = _session_with_settings({"allow_manager_group_creation": False})

    with pytest.raises(AuthorizationError, match="disabled"):
        await _require_client_group_creation_access(
            SimpleNamespace(role=UserRole.AGENCY_MANAGER),
            session,
        )


@pytest.mark.asyncio
async def test_manager_creation_defaults_to_enabled_for_legacy_settings() -> None:
    session = _session_with_settings({})

    await _require_client_group_creation_access(
        SimpleNamespace(role=UserRole.AGENCY_MANAGER),
        session,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role",
    [
        UserRole.SUPER_ADMIN,
        UserRole.AGENCY_ADMIN,
        UserRole.AGENCY_STAFF,
    ],
)
async def test_existing_creation_roles_remain_allowed(role: UserRole) -> None:
    session = _session_with_settings(None)

    await _require_client_group_creation_access(SimpleNamespace(role=role), session)

    session.execute.assert_not_awaited()
