from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.domain.entities.entities import UserRole
from app.presentation.dependencies import auth as auth_dependencies


@pytest.mark.asyncio
async def test_unsafe_cookie_auth_runs_central_csrf_guard(monkeypatch) -> None:
    user_id = uuid.uuid4()
    request = SimpleNamespace(method="POST", cookies={"access_token": "cookie-token"})
    repository = AsyncMock()
    repository.get_by_id.return_value = SimpleNamespace(role=UserRole.AGENCY_STAFF)
    csrf_guard = AsyncMock()
    monkeypatch.setattr(auth_dependencies, "require_cookie_csrf", csrf_guard)
    monkeypatch.setattr(
        auth_dependencies,
        "get_settings",
        lambda: SimpleNamespace(jwt=SimpleNamespace(access_cookie_name="access_token")),
    )
    monkeypatch.setattr(
        auth_dependencies,
        "decode_access_token",
        lambda _token: {"sub": str(user_id)},
    )

    await auth_dependencies.get_current_user(
        request=request,
        credentials=None,
        user_repo=repository,
    )

    csrf_guard.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_unsafe_bearer_auth_bypasses_cookie_csrf_guard(monkeypatch) -> None:
    user_id = uuid.uuid4()
    request = SimpleNamespace(method="POST", cookies={})
    repository = AsyncMock()
    repository.get_by_id.return_value = SimpleNamespace(role=UserRole.AGENCY_STAFF)
    csrf_guard = AsyncMock()
    monkeypatch.setattr(auth_dependencies, "require_cookie_csrf", csrf_guard)
    monkeypatch.setattr(
        auth_dependencies,
        "decode_access_token",
        lambda _token: {"sub": str(user_id)},
    )

    await auth_dependencies.get_current_user(
        request=request,
        credentials=HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="api-token",
        ),
        user_repo=repository,
    )

    csrf_guard.assert_not_awaited()
