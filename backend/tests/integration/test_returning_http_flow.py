"""Real ASGI routing, cookies and database authority; providers are synthetic."""

import json

import pytest
from sqlalchemy import select

from app.infrastructure.database.models import AuditLogModel
from app.presentation.api.v1.routes import (
    returning_claims,
    returning_dependencies,
    returning_history,
)
from tests.integration.traveller_reuse_fixtures import (
    FakeLimiter,
    FakeOTP,
    reuse_context,
    seed_person,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["phone", "passport", "code"])
async def test_cookie_bound_http_flow_and_document_tampering(client, db_session, test_settings, monkeypatch, method):
    service, _, group = await reuse_context(db_session, test_settings)
    person, other = await seed_person(service, group), await seed_person(service, group, 2)
    await db_session.commit()
    app = client._transport.app
    app.dependency_overrides[returning_dependencies.returning_service] = lambda: service
    provider = FakeOTP()
    monkeypatch.setattr(returning_claims, "get_otp_provider", lambda _: provider)
    monkeypatch.setattr(returning_claims, "TravellerReuseRateLimiter", FakeLimiter)
    monkeypatch.setattr(returning_dependencies, "get_traveller_request_limiter", FakeLimiter)
    monkeypatch.setattr(returning_dependencies, "get_settings", lambda: test_settings)
    fetched = []
    class Storage:
        async def stream_file(self, key, *, start, expected_bytes):
            fetched.append(key)
            assert start == 0 and expected_bytes == 10
            yield b"0123456789"
    monkeypatch.setattr(returning_history, "MinioStorageRepository", Storage)
    base = "/api/v1/returning"
    assert (await client.get(base + "/history", params={"grant": "invented"})).status_code == 410
    args = {"group_token": group.token, "method": method, "issuing_country": "IND"}
    if method == "phone":
        args["phone_number"] = person.phone
    elif method == "passport":
        args["passport_number"] = person.number
    else:
        args["individual_code"] = person.code
    start = await client.post(base + "/claims", json=args)
    assert start.status_code == 200, start.text
    cookie = start.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api/v1/returning" in cookie
    assert person.number not in start.text and person.phone not in start.text
    assert (await client.get(base + "/history")).status_code == 410
    if method == "phone":
        assert (await client.get(base + "/candidates")).status_code == 403
        assert (await client.post(base + "/otp/request")).status_code == 200
        assert (await client.post(base + "/otp/verify", json={"code": provider.code})).status_code == 200
        candidates = await client.get(base + "/candidates")
        assert candidates.status_code == 200
        assert person.number not in candidates.text and other.number not in candidates.text
        chosen = next(row for row in candidates.json()["items"] if row["passport_hint"].endswith(person.number[-2:]))
        assert (await client.post(base + "/candidate", json={"handle": chosen["handle"]})).status_code == 200
    matched = await client.post(base + "/passport", json={"passport_number": person.number, "issuing_country": "IND"})
    assert matched.status_code == 200, matched.text
    if method == "passport":
        assert matched.json()["questions"] == ["date_of_birth"]
        assert (await client.post(base + "/confirm", json={"acting_for": "self"})).status_code == 403
        challenge = await client.post(base + "/challenge", json={"answers": {"date_of_birth": "1990-02-03"}})
        assert challenge.status_code == 200, challenge.text
    confirmed = await client.post(base + "/confirm", json={"acting_for": "self"})
    assert confirmed.status_code == 200, confirmed.text
    review = await client.get(base + "/history", params={"traveller_id": str(other.profile.id)})
    assert review.status_code == 200 and review.json()["passport"]["number"] == person.number
    assert "no-store" in review.headers["cache-control"]
    denied = await client.get(base + f"/documents/{other.asset.id}")
    assert denied.status_code == 403 and fetched == []
    hostile = await client.get(base + f"/documents/{person.asset.id}", headers={"Origin": "https://untrusted.invalid"})
    assert hostile.status_code == 403 and fetched == []
    document = await client.get(base + f"/documents/{person.asset.id}")
    assert document.status_code == 200 and document.content == b"0123456789"
    assert fetched == [person.asset.object_key] and "no-store" in document.headers["cache-control"]
    audit = (await db_session.scalars(select(AuditLogModel))).all()
    assert {"traveller.claim_started", "traveller.claim_authorized", "traveller.history_viewed", "traveller.document_viewed"} <= {row.action for row in audit}
    encoded = json.dumps([row.metadata_json for row in audit])
    assert person.number not in encoded and person.phone not in encoded and person.asset.object_key not in encoded
