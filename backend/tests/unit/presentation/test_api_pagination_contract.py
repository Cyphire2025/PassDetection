import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.domain.entities.entities import UserRole
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes import admin, client_groups, notifications
from app.presentation.api.v1.routes.passport_routes import queries
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.middleware.error_handler import register_exception_handlers

# Collection identifiers must match across isolated parallel pytest workers.
ENDPOINTS = ("/passports", "/passports/groups", "/passports/groups/11111111-2222-4333-8444-555555555555",
             "/upload-links", "/admin/managers", "/notifications")


@pytest.mark.parametrize("path", ENDPOINTS)
@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": -1}, {"limit": 201},
                                    {"skip": -1}, {"skip": 100001}])
async def test_legacy_list_bounds_fail_before_data_query(path, params):
    app = FastAPI()
    register_exception_handlers(app)
    for router, prefix in ((queries.router, "/passports"), (client_groups.router, "/upload-links"),
                           (admin.router, "/admin"), (notifications.router, "/notifications")):
        app.include_router(router, prefix=prefix)
    session = AsyncMock()
    app.dependency_overrides[get_db_session] = lambda: session
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(
        role=UserRole.SUPER_ADMIN, id=uuid.uuid4(), agency_id=uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.get(path, params=params)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"
    session.execute.assert_not_awaited()
    session.scalar.assert_not_awaited()


def test_legacy_list_openapi_exposes_bounds_without_breaking_array_response():
    app = FastAPI()
    for router, prefix in ((queries.router, "/passports"), (client_groups.router, "/upload-links"),
                           (admin.router, "/admin"), (notifications.router, "/notifications")):
        app.include_router(router, prefix=prefix)
    paths = app.openapi()["paths"]
    for path in ("/passports", "/passports/groups", "/passports/groups/{group_id}",
                 "/upload-links", "/admin/managers", "/notifications"):
        operation = paths[path]["get"]
        params = {value["name"]: value["schema"] for value in operation["parameters"]}
        assert (params["limit"]["minimum"], params["limit"]["maximum"]) == (1, 200)
        assert (params["skip"]["minimum"], params["skip"]["maximum"]) == (0, 100000)
        assert operation["responses"]["200"]["content"]["application/json"]["schema"]["type"] == "array"
