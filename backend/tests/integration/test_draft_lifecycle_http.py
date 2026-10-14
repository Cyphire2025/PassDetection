"""Lifecycle endpoints cannot cross returning or fresh capability boundaries."""
import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select

from app.application.travellers import draft_activity
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftAssetModel as Asset,
)
from app.presentation.api.v1.routes import fresh_draft_dependencies, returning_dependencies
from tests.integration.test_draft_retention import uploaded
from tests.integration.test_fresh_drafts import fresh_context
from tests.integration.traveller_reuse_fixtures import FakeLimiter


@pytest.mark.asyncio
async def test_returning_discard_requires_matching_cookie_and_displayed_owner(client, db_session, test_settings, monkeypatch):
    service, _, token, _, secret, view = await uploaded(db_session, test_settings)
    client._transport.app.dependency_overrides[returning_dependencies.returning_service] = lambda: service
    monkeypatch.setattr(returning_dependencies, "get_traveller_request_limiter", FakeLimiter)
    client.cookies.set(returning_dependencies.GRANT_COOKIE, token)
    client.cookies.set("pd_returning_draft", secret)
    path = "/api/v1/returning/draft/discard-documents"
    body = {"expected_revision": view.revision}
    assert (await client.post(path, json=body)).status_code == 422
    assert (await client.post(path, json=body, headers={"X-Returning-Draft-ID": str(uuid.uuid4())})).status_code == 409
    asset = await db_session.scalar(select(Asset).where(Asset.draft_id == view.id))
    assert asset.state == "ready"
    result = await client.post(path, json=body, headers={"X-Returning-Draft-ID": str(view.id)})
    assert result.status_code == 200 and result.json()["documents"] == []
    assert result.json()["passport_fields"] == view.passport_fields
    assert "no-store" in result.headers["cache-control"]
    image = await client.get(f"/api/v1/returning/draft/documents/{asset.id}",
        headers={"X-Returning-Draft-ID": str(view.id)})
    assert image.status_code in {403, 404}


@pytest.mark.asyncio
async def test_fresh_discard_requires_own_member_capability(client, db_session, test_settings, monkeypatch):
    store, group, browser, member, _, view = await fresh_context(db_session, test_settings)
    client._transport.app.dependency_overrides[fresh_draft_dependencies.fresh_store] = lambda: store
    monkeypatch.setattr(returning_dependencies, "get_traveller_request_limiter", FakeLimiter)
    client.cookies.set("pd_fresh_drafts", browser)
    path = f"/api/v1/public-drafts/{group.token}/discard-documents"
    body = {"expected_revision": view.revision}
    wrong = await client.post(path, json=body, headers={"X-Upload-Session-ID": uuid.uuid4().hex})
    assert wrong.status_code in {403, 410}
    asset = await db_session.scalar(select(Asset).where(Asset.draft_id == view.id))
    assert asset.state == "ready"
    result = await client.post(path, json=body, headers={"X-Upload-Session-ID": member})
    assert result.status_code == 200 and result.json()["documents"] == []
    assert result.json()["current_details"] == view.current_details
    assert result.json()["passport_fields"] == view.passport_fields


@pytest.mark.asyncio
async def test_activity_requires_current_capability_and_does_not_change_revision(client, db_session, test_settings, monkeypatch):
    service, _, token, _, secret, view = await uploaded(db_session, test_settings)
    calls = []

    class Presence:
        async def touch(self, agency_id, draft_id):
            calls.append((agency_id, draft_id))

    @asynccontextmanager
    async def presence(settings):
        yield Presence()

    monkeypatch.setattr(draft_activity, "draft_presence", presence)
    monkeypatch.setattr(returning_dependencies, "get_traveller_request_limiter", FakeLimiter)
    client._transport.app.dependency_overrides[returning_dependencies.returning_service] = lambda: service
    client.cookies.set(returning_dependencies.GRANT_COOKIE, token)
    client.cookies.set("pd_returning_draft", secret)
    headers = {"X-Returning-Draft-ID": str(view.id)}
    result = await client.post("/api/v1/returning/draft/activity", headers=headers)
    assert result.status_code == 200
    assert result.json() == {"images_present": True, "presence_recorded": True, "heartbeat_after_seconds": 60}
    assert len(calls) == 1 and calls[0][1] == view.id
    assert (await client.get("/api/v1/returning/draft", headers=headers)).json()["revision"] == view.revision
    client.cookies.delete(returning_dependencies.GRANT_COOKIE)
    assert (await client.get("/api/v1/returning/draft", headers=headers)).status_code in {403, 410}
    assert (await client.post("/api/v1/returning/draft/activity", headers=headers)).status_code == 200
    assert (await client.post("/api/v1/returning/draft/activity",
        headers={"X-Returning-Draft-ID": str(uuid.uuid4())})).status_code == 409
    assert len(calls) == 2
    _, _, _, _, _, other = await uploaded(db_session, test_settings)
    assert other.id != view.id
    assert (await client.post("/api/v1/returning/draft/activity",
        headers={"X-Returning-Draft-ID": str(other.id)})).status_code == 409
    assert len(calls) == 2
