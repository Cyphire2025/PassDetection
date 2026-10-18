"""The private-history DELETE route preserves cookie CSRF and AI access checks."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
from fastapi import FastAPI

from app.application.assistant.contracts import AssistantError
from app.core.config.settings import get_settings
from app.domain.entities.entities import User, UserRole
from app.infrastructure.assistant.settings_store import AssistantSnapshot
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes import ai_assistant
from app.presentation.dependencies.auth import get_current_active_user


async def test_private_delete_checks_identity_csrf_uuid_and_errors_without_requiring_provider_key(monkeypatch):
    app = FastAPI()
    app.include_router(ai_assistant.router, prefix="/api/v1/ai-assistant")
    actor = User.create("assistant@example.test", "fixture-hash", "Synthetic administrator", UserRole.SUPER_ADMIN)
    app.dependency_overrides[get_current_active_user] = lambda: actor
    app.dependency_overrides[get_db_session] = lambda: SimpleNamespace(rollback=AsyncMock())
    monkeypatch.setattr(ai_assistant, "load_snapshot", AsyncMock(return_value=AssistantSnapshot()))
    fresh = AsyncMock(return_value=actor)
    remove = AsyncMock()
    monkeypatch.setattr(ai_assistant, "fresh_actor", fresh)
    monkeypatch.setattr(ai_assistant, "assistant_store", lambda user: SimpleNamespace(delete_conversation=remove))
    identifier = uuid4()
    url = f"/api/v1/ai-assistant/conversations/{identifier}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        result = await client.delete(url)
        assert result.status_code == 204 and not result.content
        assert result.headers["cache-control"] == "private, no-store"
        remove.assert_awaited_once_with(identifier)
        fresh.assert_awaited_once_with(actor)
        remove.reset_mock()
        client.cookies.set(get_settings().jwt.access_cookie_name, "synthetic-cookie")
        denied = await client.delete(url, headers={"Origin": "https://untrusted.example.test"})
        assert denied.status_code == 403
        remove.assert_not_awaited()
        client.cookies.clear()
        app.dependency_overrides[get_current_active_user] = lambda: replace(actor, role=UserRole.AGENCY_ADMIN)
        assert (await client.delete(url)).status_code == 403
        remove.assert_not_awaited()
        app.dependency_overrides[get_current_active_user] = lambda: actor
        assert (await client.delete("/api/v1/ai-assistant/conversations/not-a-uuid")).status_code == 422
        remove.side_effect = AssistantError("not_found", "This item is not in your workspace.", 404)
        assert (await client.delete(url)).status_code == 404
        remove.side_effect = TimeoutError()
        timed_out = await client.delete(url)
        assert timed_out.status_code == 503 and timed_out.json()["detail"]["code"] == "deletion_incomplete"
