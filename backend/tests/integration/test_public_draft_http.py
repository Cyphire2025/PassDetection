"""HTTP draft binding rejects shared-cookie context switches before disclosure."""
import uuid
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.presentation.api.v1.routes import returning_dependencies
from app.presentation.middleware.request_path import safe_request_path
from tests.integration.test_returning_drafts import draft_context, save_body
from tests.integration.traveller_reuse_fixtures import FakeLimiter


@pytest.mark.asyncio
async def test_returning_routes_require_exact_displayed_draft_id(client, db_session, test_settings, monkeypatch):
    service, _, _, _, token, _, secret, view = await draft_context(db_session, test_settings)
    client._transport.app.dependency_overrides[returning_dependencies.returning_service] = lambda: service
    monkeypatch.setattr(returning_dependencies, "get_traveller_request_limiter", FakeLimiter)
    client.cookies.set(returning_dependencies.GRANT_COOKIE, token)
    client.cookies.set("pd_returning_draft", secret)
    base = "/api/v1/returning/draft"
    assert (await client.get(base)).status_code == 422
    wrong = {"X-Returning-Draft-ID": str(uuid.uuid4())}
    assert (await client.get(base, headers=wrong)).status_code == 409
    assert (await client.put(base, headers=wrong, json=save_body(view).model_dump(mode="json"))).status_code == 409
    good = {"X-Returning-Draft-ID": str(view.id)}
    result = await client.get(base, headers=good)
    assert result.status_code == 200 and result.json()["id"] == str(view.id)
    assert "no-store" in result.headers["cache-control"]
    assert (await client.get(base + "/documents/" + str(uuid.uuid4()), headers=good)).status_code in {403, 404}


@pytest.mark.asyncio
async def test_fresh_boundary_counts_browser_session_and_redacts_group_capability(monkeypatch):
    limiter = AsyncMock()
    monkeypatch.setattr(returning_dependencies, "get_traveller_request_limiter", lambda: limiter)
    monkeypatch.setattr(returning_dependencies, "require_trusted_request_origin", AsyncMock())
    request = Request({"type": "http", "method": "GET", "path": "/api/v1/public-drafts/private-group-token/documents/" + str(uuid.uuid4()),
        "headers": [(b"cookie", b"pd_fresh_drafts=browser-capability; pd_returning_claim=unrelated-claim")]})
    await returning_dependencies.private_boundary(request, Response())
    assert limiter.consume.await_args.kwargs["session_secret"] == "browser-capability"
    assert safe_request_path(request) == "/api/v1/public-drafts/{token}/documents/{id}"
