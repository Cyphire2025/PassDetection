"""Retained-person failures stay closed and stale directory pages can restart."""

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.companies.directory_projection import refresh_directory_person
from app.application.companies.people import current_person
from app.core.config.traveller_reuse import TravellerReuseSettings
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentRevisionModel as Document,
)
from app.presentation.api.v1.routes import company_people
from tests.integration.test_company_directory_index import person as add_person
from tests.integration.test_company_people import people_fixture
from tests.integration.test_company_people_http import application


@pytest.mark.asyncio
async def test_non_object_retained_fields_are_rejected_without_partial_person_data(db_session):
    ctx, person, _user = await people_fixture(db_session)
    document = await db_session.scalar(select(Document))
    ciphertext = document.fields_ciphertext
    source_fields = dict(ctx.source.confirmed_fields)
    for invalid in (None, [source_fields], "Synthetic retained identity"):
        document.fields_ciphertext = ctx.crypto.encrypt(json.dumps(invalid))
        await db_session.flush()
        with pytest.raises(ValueError, match="^invalid_retained_fields$"):
            await current_person(db_session, person, ctx.crypto)
        assert person.revision == 1
        assert ctx.source.confirmed_fields == source_fields
    document.fields_ciphertext = ciphertext
    await db_session.flush()
    recovered = await current_person(db_session, person, ctx.crypto)
    assert recovered.current_document.fields["passport_number"] == "001234567"


@pytest.mark.asyncio
async def test_missing_retained_crypto_returns_retryable_generic_http_error(db_session, monkeypatch):
    ctx, person, user = await people_fixture(db_session)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    app = application(factory, user, ctx.crypto)
    del app.dependency_overrides[company_people.crypto_dependency]
    monkeypatch.setattr(company_people, "get_traveller_reuse_settings", lambda: TravellerReuseSettings(
        lookup_key=None, encryption_key=None, _env_file=None,
    ))
    url = f"/api/v1/companies/{person.company_id}/people/{person.id}/record"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        unavailable = await http.get(url)
        assert unavailable.status_code == 503
        assert unavailable.json()["detail"] == "Retained traveller data is temporarily unavailable."
        assert "001234567" not in unavailable.text
        assert "keys are not configured" not in unavailable.text
        app.dependency_overrides[company_people.crypto_dependency] = lambda: ctx.crypto
        recovered = await http.get(url)
        assert recovered.status_code == 200
        assert recovered.json()["current_document"]["fields"]["passport_number"] == "001234567"
        assert recovered.json()["revision"] == 1


@pytest.mark.asyncio
async def test_directory_reindex_invalidates_http_cursor_and_allows_fresh_page(db_session):
    ctx, first, user = await people_fixture(db_session)
    second = await add_person(db_session, ctx, "Another Synthetic Person")
    for person in (first, second):
        assert await refresh_directory_person(db_session, person.id, ctx.crypto)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    app = application(factory, user, ctx.crypto)
    url = f"/api/v1/companies/{first.company_id}/people"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        initial = await http.get(url, params={"page_size": 1})
        assert initial.status_code == 200 and initial.json()["has_more"]
        cursor = initial.json()["next_cursor"]
        first.display_name_ciphertext = ctx.crypto.encrypt("Updated Synthetic Person")
        first.revision += 1
        await db_session.flush()
        assert await refresh_directory_person(db_session, first.id, ctx.crypto)
        await db_session.commit()
        stale = await http.get(url, params={"page_size": 1, "cursor": cursor})
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "DIRECTORY_CHANGED"
        assert "Restart from the first page" in stale.json()["error"]["message"]
        restarted = await http.get(url)
        assert restarted.status_code == 200 and not restarted.json()["has_more"]
        assert {(item["id"], item["display_name"]) for item in restarted.json()["items"]} == {
            (str(first.id), "Updated Synthetic Person"), (str(second.id), "Another Synthetic Person"),
        }
