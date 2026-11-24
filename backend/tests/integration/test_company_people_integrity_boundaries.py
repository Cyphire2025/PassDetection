"""Retained record integrity and recoverable directory failures at real boundaries."""

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.companies.current_record import edit_current_record
from app.application.companies.directory_projection import refresh_directory_person
from app.application.companies.people import current_document, current_person
from app.application.companies.people_contracts import PersonEdit
from app.core.config.traveller_reuse import TravellerReuseSettings
from app.presentation.api.v1.routes import company_people
from tests.integration.test_company_directory_index import person as directory_person
from tests.integration.test_company_people import people_fixture
from tests.integration.test_company_people_http import application


@pytest.mark.asyncio
async def test_corrupt_retained_fields_never_escape_as_a_person_record(db_session):
    ctx, person, user = await people_fixture(db_session)
    selected = await current_document(db_session, person)
    assert selected is not None
    private_marker = "SYNTHETIC-PRIVATE-RETAINED-CONTENT"
    selected[1].fields_ciphertext = ctx.crypto.encrypt(json.dumps([private_marker]))
    await db_session.flush()

    with pytest.raises(ValueError, match="^invalid_retained_fields$"):
        await current_person(db_session, person, ctx.crypto, user=user)
    await db_session.commit()

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    app = application(factory, user, ctx.crypto)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.get(
            f"/api/v1/companies/{person.company_id}/people/{person.id}/record"
        )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert "no-store" in response.headers["Cache-Control"]
    assert private_marker not in response.text
    assert "invalid_retained_fields" not in response.text
    assert "fields_ciphertext" not in response.text


@pytest.mark.asyncio
async def test_missing_reuse_keys_return_safe_unavailable_response(db_session, monkeypatch):
    ctx, person, user = await people_fixture(db_session)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    app = application(factory, user, ctx.crypto)
    app.dependency_overrides.pop(company_people.crypto_dependency)
    unconfigured = TravellerReuseSettings(
        _env_file=None, lookup_key=None, encryption_key=None
    )
    monkeypatch.setattr(company_people, "get_traveller_reuse_settings", lambda: unconfigured)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.get(f"/api/v1/companies/{person.company_id}/people")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert response.json()["error"]["message"] == (
        "Retained traveller data is temporarily unavailable."
    )
    assert "no-store" in response.headers["Cache-Control"]
    assert "lookup_key" not in response.text
    assert "encryption_key" not in response.text
    assert "items" not in response.json()


@pytest.mark.asyncio
async def test_directory_edit_invalidates_old_http_cursor_and_allows_restart(db_session):
    ctx, person, user = await people_fixture(db_session)
    second = await directory_person(db_session, ctx, "Synthetic Second Person")
    for entry in (person, second):
        assert await refresh_directory_person(db_session, entry.id, ctx.crypto)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    app = application(factory, user, ctx.crypto)
    url = f"/api/v1/companies/{person.company_id}/people"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        first = await http.get(url, params={"page_size": 1})
        assert first.status_code == 200
        cursor = first.json()["next_cursor"]
        assert first.json()["has_more"] and cursor

        await edit_current_record(
            db_session,
            person=person,
            actor_id=user.id,
            crypto=ctx.crypto,
            body=PersonEdit(
                expected_revision=person.revision,
                idempotency_key="directory-cursor-current-edit",
                reason="Reviewed directory correction",
                display_name="Synthetic Updated Person",
            ),
        )
        assert await refresh_directory_person(db_session, person.id, ctx.crypto)
        await db_session.commit()

        stale = await http.get(url, params={"page_size": 1, "cursor": cursor})
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "DIRECTORY_CHANGED"
        assert "no-store" in stale.headers["Cache-Control"]
        assert "items" not in stale.json()

        restarted = await http.get(url)
        assert restarted.status_code == 200
        assert {item["id"] for item in restarted.json()["items"]} == {
            str(person.id), str(second.id)
        }
        assert "Synthetic Updated Person" in {
            item["display_name"] for item in restarted.json()["items"]
        }
