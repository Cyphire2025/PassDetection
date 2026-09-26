import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.presentation.api.v1.routes import frontend_errors as module
from app.presentation.middleware.error_handler import register_exception_handlers


@pytest.fixture
def payload():
    return dict(event_id=str(uuid4()), fingerprint="a" * 32, release="abc123", route="unknown",
                boundary="shared", error_kind="TypeError")


@pytest.fixture
def reporter(monkeypatch, payload):
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(module.router)
    monkeypatch.setattr(module, "get_settings", lambda: type("Settings", (), {
        "allowed_origins": ["https://example.test"]})())
    admission, logger = AsyncMock(return_value=module.ReportAdmission(1, payload["event_id"])), Mock()
    monkeypatch.setattr(module, "_admit", admission)
    monkeypatch.setattr(module, "logger", logger)
    return app, admission, logger


async def test_metadata_only_report_is_centrally_recorded(reporter, payload):
    app, admission, logger = reporter
    async with AsyncClient(transport=ASGITransport(app), base_url="https://example.test") as client:
        response = await client.post("/frontend-errors", json=payload,
                                     headers={"Origin": "https://example.test"})
    assert response.status_code == 202
    assert response.json() == {"event_id": payload["event_id"]}
    admission.assert_awaited_once()
    logger.warning.assert_called_once_with("frontend_render_failure", source="untrusted_browser",
                                           **payload)


@pytest.mark.parametrize("change", [
    {"message": "a private passport"}, {"stack": "secret URL"}, {"route": "/upload/private-token"},
    {"route": "unknown?secret=value"}, {"release": "https://private.test"},
    {"fingerprint": "not-a-hash"}, {"error_kind": "private-content"},
])
async def test_untrusted_content_never_reaches_logger(reporter, payload, change):
    app, admission, logger = reporter
    async with AsyncClient(transport=ASGITransport(app), base_url="https://example.test") as client:
        response = await client.post("/frontend-errors", json={**payload, **change},
                                     headers={"Origin": "https://example.test"})
    assert response.status_code == 422
    admission.assert_not_awaited()
    logger.warning.assert_not_called()
    assert "private" not in response.text


@pytest.mark.parametrize("origin", [None, "https://attacker.test", "null", "https://[invalid"])
async def test_missing_or_foreign_origin_is_rejected(reporter, payload, origin):
    app, admission, logger = reporter
    async with AsyncClient(transport=ASGITransport(app), base_url="https://example.test") as client:
        response = await client.post("/frontend-errors", json=payload,
                                     headers={"Origin": origin} if origin else {})
    assert response.status_code == 403
    admission.assert_not_awaited()


async def test_size_limit_and_distributed_admission_outcomes(reporter, payload):
    app, admission, logger = reporter
    headers = {"Origin": "https://example.test", "Content-Type": "application/json"}
    async with AsyncClient(transport=ASGITransport(app), base_url="https://example.test") as client:
        oversized = await client.post("/frontend-errors", content=b"x" * 2049, headers=headers)
        assert oversized.status_code == 413
        admission.assert_not_awaited()
        admission.return_value = module.ReportAdmission(-1, None)
        limited = await client.post("/frontend-errors", json=payload, headers=headers)
        assert limited.status_code == 429 and limited.headers["retry-after"] == "60"
        original_event = uuid4()
        admission.return_value = module.ReportAdmission(0, original_event)
        duplicate = await client.post("/frontend-errors", json=payload, headers=headers)
        assert duplicate.status_code == 202
        assert duplicate.json()["event_id"] == str(original_event)
    logger.warning.assert_not_called()


def test_frontend_backend_route_contracts_are_identical():
    root = Path(__file__).resolve().parents[4]
    frontend = json.loads((root / "frontend/lib/observability/route-templates.json").read_text("utf-8"))
    assert frozenset(frontend) == module.ROUTES
