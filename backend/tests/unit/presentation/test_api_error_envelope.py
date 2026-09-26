from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException, Query
from httpx import ASGITransport, AsyncClient

from app.domain.exceptions.exceptions import AuthorizationError, StorageError
from app.presentation.middleware.error_handler import register_exception_handlers
from app.presentation.middleware.error_response import ApiErrorResponse
from app.presentation.middleware.request_id import RequestIDMiddleware


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 410, 413, 415, 422, 429, 500, 503])
async def test_http_error_matches_envelope_and_retains_headers(status: int) -> None:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)

    @app.get("/denied")
    async def denied():
        raise HTTPException(status, "Intentionally denied", headers={
            "Retry-After": "30", "WWW-Authenticate": "Bearer"})

    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/denied", headers={"X-Request-ID": "sensitive-invalid-value"})
    assert response.status_code == status
    parsed = ApiErrorResponse.model_validate(response.json())
    assert parsed.error.code and parsed.error.message
    assert parsed.detail == ("Intentionally denied" if status != 500 else parsed.error.message)
    assert response.headers["retry-after"] == "30"
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "no-store"
    UUID(response.headers["x-request-id"])


async def test_domain_http_validation_and_unknown_paths_share_contract() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/domain")
    async def domain():
        raise AuthorizationError("Denied")

    @app.get("/http")
    async def http():
        raise HTTPException(403, "Denied")

    @app.get("/input")
    async def input_value(value: int = Query(ge=1)):
        return value

    @app.get("/structured")
    async def structured():
        raise HTTPException(409, {"code": "REVISION_CHANGED", "message": "Refresh", "revision": 4})

    @app.get("/internal")
    async def internal():
        raise StorageError("private-secret-and-storage-location")

    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        domain_response, http_response = await client.get("/domain"), await client.get("/http")
        assert domain_response.json()["error"] == http_response.json()["error"]
        invalid = await client.get("/input?value=private-token")
        assert invalid.status_code == 422 and "private-token" not in invalid.text
        for path in ("/not-found", "/structured", "/internal"):
            response = await client.get(path)
            ApiErrorResponse.model_validate(response.json())
            assert "private-secret" not in response.text
        conflict = (await client.get("/structured")).json()
        assert conflict["error"]["code"] == "REVISION_CHANGED"
        assert conflict["detail"]["revision"] == 4


async def test_unhandled_failure_retains_request_id_without_reflecting_exception() -> None:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)

    @app.get("/failure")
    async def failure():
        raise RuntimeError("private-password-and-database-address")

    async with AsyncClient(transport=ASGITransport(app, raise_app_exceptions=False), base_url="http://test") as client:
        response = await client.get("/failure")
    assert response.status_code == 500
    UUID(response.headers["x-request-id"])
    ApiErrorResponse.model_validate(response.json())
    assert "private-password" not in response.text
