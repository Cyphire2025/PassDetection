"""Exercise closed-link and staff-delete restrictions at the HTTP boundary."""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.domain.entities.entities import UserRole
from app.domain.exceptions.exceptions import GroupClosedError
from app.presentation.api.v1.routes import client_groups as routes


@pytest.mark.asyncio
async def test_closed_link_lookup_returns_closed_code_and_message() -> None:
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1/upload-links")
    use_case = AsyncMock()
    use_case.execute.side_effect = GroupClosedError()
    app.dependency_overrides[routes._get_get_by_token_use_case] = lambda: use_case
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/api/v1/upload-links/token/closed-test-link")
    assert response.status_code == 410
    assert response.json()["detail"] == {"code": "CLIENT_GROUP_CLOSED", "message": "This link is closed."}


@pytest.mark.asyncio
async def test_staff_cannot_archive_accessible_group_by_direct_request(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1/upload-links")
    agency, user_id, group_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    staff = SimpleNamespace(id=user_id, role=UserRole.AGENCY_STAFF, agency_id=agency)
    group = SimpleNamespace(id=group_id, agency_id=agency, created_by_user_id=user_id, status="active")
    use_case = AsyncMock()
    session = AsyncMock()
    monkeypatch.setattr(routes.ClientGroupRepository, "get_by_id", AsyncMock(return_value=group))
    app.dependency_overrides[routes.get_current_active_user] = lambda: staff
    app.dependency_overrides[routes.get_db_session] = lambda: session
    app.dependency_overrides[routes._get_delete_use_case] = lambda: use_case
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.delete(f"/api/v1/upload-links/{group_id}")
    assert response.status_code == 403
    use_case.execute.assert_not_awaited()
    session.commit.assert_not_awaited()
    assert group.status == "active"
