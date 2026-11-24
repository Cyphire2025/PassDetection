"""A queued command may reject a changed actor, but cannot choose its authority."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends, FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.domain.entities.entities import UserRole
from app.domain.exceptions.exceptions import AuthenticationError
from app.presentation.dependencies import auth


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["cookie", "bearer"])
@pytest.mark.parametrize("expected_actor", ["matching", "different", "malformed", "absent"])
async def test_expected_actor_precondition_precedes_command_effect(
    monkeypatch, transport: str, expected_actor: str
) -> None:
    actor_id = uuid.uuid4()
    actor = SimpleNamespace(id=actor_id, role=UserRole.AGENCY_STAFF)
    repository = AsyncMock()
    repository.get_by_id.return_value = actor
    session_guard = AsyncMock()
    csrf_guard = AsyncMock()
    monkeypatch.setattr(auth, "require_dashboard_session", session_guard)
    monkeypatch.setattr(auth, "require_cookie_csrf", csrf_guard)
    monkeypatch.setattr(auth, "decode_access_token", lambda _: {"sub": str(actor_id)})
    monkeypatch.setattr(
        auth, "get_settings",
        lambda: SimpleNamespace(jwt=SimpleNamespace(access_cookie_name="access_token")),
    )
    application = FastAPI()
    application.dependency_overrides[auth.get_user_repository] = lambda: repository
    application.dependency_overrides[auth.get_db_session] = lambda: None
    effects: list[uuid.UUID] = []

    @application.post("/command")
    async def command(user=Depends(auth.get_authenticated_user)):
        effects.append(user.id)
        return {"actor_id": str(user.id)}

    headers = {"Authorization": "Bearer synthetic-token"} if transport == "bearer" else {}
    if expected_actor != "absent":
        headers["X-Expected-Actor-Id"] = {
            "matching": str(actor_id), "different": str(uuid.uuid4()), "malformed": "invalid-actor",
        }[expected_actor]
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test",
        cookies={"access_token": "synthetic-token"} if transport == "cookie" else {},
    ) as client:
        result = await client.post("/command", headers=headers, json={"scan": "synthetic-only"})

    session_guard.assert_awaited_once()
    repository.get_by_id.assert_awaited_once_with(actor_id)
    if transport == "cookie":
        csrf_guard.assert_awaited_once()
    else:
        csrf_guard.assert_not_awaited()
    if expected_actor in {"different", "malformed"}:
        assert result.status_code == 409
        assert result.json()["detail"]["code"] == "AUTH_REQUEST_OWNER_CHANGED"
        assert effects == []
    else:
        assert result.status_code == 200
        assert result.json() == {"actor_id": str(actor_id)}
        assert effects == [actor_id]


@pytest.mark.asyncio
async def test_expected_actor_header_cannot_replace_authentication() -> None:
    request = Request({
        "type": "http", "method": "GET", "path": "/command",
        "headers": [(b"x-expected-actor-id", str(uuid.uuid4()).encode())],
    })
    repository = AsyncMock()
    with pytest.raises(AuthenticationError, match="Authorization header missing"):
        await auth.get_authenticated_user(request, credentials=None, user_repo=repository)
    repository.get_by_id.assert_not_awaited()
