"""Anonymous number/date access through real HTTP, cookies and persisted proof."""

from datetime import datetime

import pytest
from sqlalchemy import event, func, select

from app.application.travellers.passport_lookup_index import backfill_passport_lookup
from app.infrastructure.database.traveller_reuse_models import (
    TravellerAttemptBudgetModel,
    TravellerClaimModel,
    TravellerContactBindingModel,
    TravellerHistoryGrantModel,
)
from app.presentation.api.v1.routes import returning_claims, returning_dependencies
from tests.integration.traveller_reuse_fixtures import (
    FakeLimiter,
    FakeOTP,
    reuse_context,
    seed_person,
)

BASE = "/api/v1/returning"


@pytest.fixture
async def portal(client, db_session, test_settings, monkeypatch):
    service, _, group = await reuse_context(db_session, test_settings)
    person = await seed_person(service, group)
    assert await backfill_passport_lookup(db_session, service.crypto) == 1
    await db_session.commit()
    client._transport.app.dependency_overrides[returning_dependencies.returning_service] = lambda: service
    monkeypatch.setattr(returning_dependencies, "get_traveller_request_limiter", FakeLimiter)
    monkeypatch.setattr(returning_dependencies, "get_settings", lambda: test_settings)
    provider = FakeOTP()
    monkeypatch.setattr(returning_claims, "get_otp_provider", lambda _: provider)
    monkeypatch.setattr(returning_claims, "TravellerReuseRateLimiter", FakeLimiter)
    return service, group, person, provider


async def begin(client, group, number):
    started = await client.post(BASE + "/claims", json={
        "group_token": group.token, "method": "passport", "passport_number": number,
    })
    assert started.status_code == 200, started.text
    response = await client.post(BASE + "/passport", json={"passport_number": number})
    assert response.status_code == 200, response.text
    return response


async def current_claim(client, service):
    secret = client.cookies[returning_dependencies.CLAIM_COOKIE]
    return await service.session.scalar(select(TravellerClaimModel).where(
        TravellerClaimModel.secret_hash == service.crypto.digest("claim", secret)))


@pytest.mark.asyncio
async def test_first_passport_and_alternate_date_responses_never_look_up_a_person(client, db_session, portal):
    service, group, person, _ = portal
    statements = []
    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())
    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", observe)
    try:
        responses = []
        for number in (person.number, "ABSENT1234"):
            responses.append((await begin(client, group, number)).json())
            alternative = await client.post(BASE + "/challenge/change", json={"field": "issue_date"})
            assert alternative.status_code == 200
            assert alternative.json()["questions"] == ["issue_date"]
            claim = await current_claim(client, service)
            assert claim.traveller_id is None and claim.passport_id is None
            assert claim.status == "created" and claim.failed_answer_sets == 0
            assert (await client.get(BASE + "/history")).status_code == 410
        assert responses[0] == responses[1]
        assert responses[0]["questions"] == ["date_of_birth"]
        assert responses[0]["available_questions"] == ["date_of_birth", "issue_date", "expiry_date"]
        assert not any("traveller_passports" in sql or "traveller_profiles" in sql for sql in statements)
    finally:
        event.remove(engine, "before_cursor_execute", observe)


@pytest.mark.asyncio
@pytest.mark.parametrize("field,answer", [
    ("date_of_birth", "1990-02-03"), ("issue_date", "2024-04-05"), ("expiry_date", "2035-04-04"),
])
async def test_number_and_correct_date_open_proof_only_access_without_declaration(client, db_session, portal, field, answer):
    service, group, person, _ = portal
    before = (person.profile.revision, person.profile.contact_revision, person.profile.authorization_version)
    await begin(client, group, person.number)
    if field != "date_of_birth":
        changed = await client.post(BASE + "/challenge/change", json={"field": field})
        assert changed.status_code == 200
    assert (await client.post(BASE + "/confirm", json={})).status_code == 403
    verified = await client.post(BASE + "/challenge", json={"answers": {field: answer}})
    assert verified.status_code == 200, verified.text
    assert verified.json()["stage"] == "confirm"
    confirmed = await client.post(BASE + "/confirm", json={})
    assert confirmed.status_code == 200, confirmed.text
    token = client.cookies[returning_dependencies.GRANT_COOKIE]
    assert (await client.post(BASE + "/confirm", json={})).status_code == 200
    assert client.cookies[returning_dependencies.GRANT_COOKIE] == token
    result = await client.get(BASE + "/history")
    assert result.status_code == 200 and result.json()["passport"]["number"] == person.number
    assert "no-store" in result.headers["cache-control"]
    claim = await current_claim(client, service)
    grant = await db_session.scalar(select(TravellerHistoryGrantModel))
    assert grant.actor_kind == claim.actor_kind == "verified"
    assert grant.actor_evidence == {
        "policy": "verified_portal_access_v3", "verification_method": "passport",
        "passport_checked": True, "date_checks": 1, "ownership_proven": False,
    }
    assert claim.otp_verified_at is None
    assert before == (person.profile.revision, person.profile.contact_revision, person.profile.authorization_version)
    assert await db_session.scalar(select(func.count()).select_from(TravellerContactBindingModel)) == 1
    assert await db_session.scalar(select(func.count()).select_from(TravellerHistoryGrantModel)) == 1


@pytest.mark.asyncio
async def test_incorrect_and_unavailable_dates_share_the_durable_failure_budget(client, db_session, portal):
    service, group, person, _ = portal
    person.document.reliable_fields = {"date_of_birth": {"accepted": True, "source": "staff_review"}}
    await db_session.commit()
    for attempt in range(5):
        await begin(client, group, person.number)
        field = "issue_date" if attempt % 2 else "date_of_birth"
        if field == "issue_date":
            assert (await client.post(BASE + "/challenge/change", json={"field": field})).status_code == 200
        denied = await client.post(BASE + "/challenge", json={"answers": {field: "2000-01-01"}})
        assert denied.status_code == 403, denied.text
        assert denied.json()["error"]["code"] == "verification_failed"
        assert (await client.post(BASE + "/confirm", json={})).status_code == 403
        claim = await current_claim(client, service)
        assert claim.failed_answer_sets == 1
    budget = await db_session.get(TravellerAttemptBudgetModel, person.profile.id)
    assert budget.failure_count == 5
    cooldown = budget.cooldown_until
    await begin(client, group, person.number)
    blocked = await client.post(BASE + "/challenge", json={"answers": {"date_of_birth": "1990-02-03"}})
    assert blocked.status_code == 429
    assert budget.cooldown_until == cooldown
    assert await db_session.scalar(select(func.count()).select_from(TravellerHistoryGrantModel)) == 0


@pytest.mark.asyncio
async def test_unknown_passport_wrong_date_consumes_claim_budget_without_disclosure(client, db_session, portal):
    service, group, _, _ = portal
    await begin(client, group, "ABSENT1234")
    for _ in range(5):
        denied = await client.post(BASE + "/challenge", json={"answers": {"date_of_birth": "1990-02-03"}})
        assert denied.status_code == 403
    claim = await current_claim(client, service)
    assert claim.failed_answer_sets == 5 and claim.status == "locked"
    assert claim.traveller_id is None and claim.passport_id is None
    assert (await client.post(BASE + "/challenge", json={"answers": {"date_of_birth": "1990-02-03"}})).status_code == 410
    assert await db_session.scalar(select(func.count()).select_from(TravellerHistoryGrantModel)) == 0


@pytest.mark.asyncio
async def test_number_only_lookup_rejects_cross_issuer_ambiguity_before_binding(client, db_session, portal):
    service, group, first, _ = portal
    second = await seed_person(service, group, 2)
    second.passport.number_ciphertext = service.crypto.encrypt(first.number)
    second.passport.issuing_country = "GBR"
    second.passport.number_fingerprint = service.crypto.passport_fingerprint(
        group.agency_id, group.company_id, first.number, "GBR", "P")
    assert await backfill_passport_lookup(db_session, service.crypto) == 1
    await db_session.commit()
    await begin(client, group, first.number)
    denied = await client.post(BASE + "/challenge", json={"answers": {"date_of_birth": "1990-02-03"}})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "verification_failed"
    claim = await current_claim(client, service)
    assert claim.traveller_id is None and claim.passport_id is None
    assert claim.failed_answer_sets == 1


@pytest.mark.asyncio
async def test_number_only_lookup_remains_company_scoped(client, db_session, portal, test_settings):
    service, _, person, _ = portal
    _, _, other_group = await reuse_context(db_session, test_settings)
    await db_session.commit()
    await begin(client, other_group, person.number)
    denied = await client.post(BASE + "/challenge", json={"answers": {"date_of_birth": "1990-02-03"}})
    assert denied.status_code == 403
    claim = await current_claim(client, service)
    assert claim.company_id == other_group.company_id and claim.traveller_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("answers", [{}, {"date_of_birth": "bad-date"}, {"expiry_date": "2035-04-04"}])
async def test_missing_malformed_or_unselected_dates_do_not_bypass_proof(client, db_session, portal, answers):
    service, group, person, _ = portal
    await begin(client, group, person.number)
    denied = await client.post(BASE + "/challenge", json={"answers": answers})
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "verification_failed"
    claim = await current_claim(client, service)
    assert claim.failed_answer_sets == 1
    assert (await client.post(BASE + "/confirm", json={})).status_code == 403
    assert await db_session.scalar(select(func.count()).select_from(TravellerHistoryGrantModel)) == 0


@pytest.mark.asyncio
async def test_unreliable_dates_consume_a_failure_and_never_unlock_history(client, db_session, portal):
    service, group, person, _ = portal
    person.document.reliable_fields = {}
    await db_session.commit()
    await begin(client, group, person.number)
    denied = await client.post(BASE + "/challenge", json={"answers": {"date_of_birth": "1990-02-03"}})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "verification_failed"
    claim = await current_claim(client, service)
    assert claim.failed_answer_sets == 1
    assert (await client.get(BASE + "/history")).status_code == 410


@pytest.mark.asyncio
async def test_new_phone_proof_opens_review_but_does_not_rewrite_contact(client, db_session, portal):
    service, group, person, provider = portal
    before = (person.profile.contact_revision, person.profile.authorization_version)
    started = await client.post(BASE + "/claims", json={
        "group_token": group.token, "method": "phone", "phone_number": "+919876543211",
    })
    assert started.status_code == 200
    assert (await client.post(BASE + "/otp/request")).status_code == 200
    assert (await client.post(BASE + "/otp/verify", json={"code": provider.code})).status_code == 200
    matched = await client.post(BASE + "/passport", json={"passport_number": person.number})
    assert matched.status_code == 200, matched.text
    dates = {"date_of_birth": "1990-02-03", "issue_date": "2024-04-05", "expiry_date": "2035-04-04"}
    assert len(matched.json()["questions"]) == 2
    verified = await client.post(BASE + "/challenge", json={"answers": {
        key: dates[key] for key in matched.json()["questions"]
    }})
    assert verified.status_code == 200 and verified.json()["stage"] == "recovery"
    assert (await client.post(BASE + "/confirm", json={})).status_code == 200
    grant = await db_session.scalar(select(TravellerHistoryGrantModel))
    evidence = grant.actor_evidence["pending_contact_change"]
    assert evidence["fingerprint"] == service.crypto.scoped_digest("phone", group.agency_id, group.company_id, "+919876543211")
    assert datetime.fromisoformat(evidence["verified_at"]).tzinfo is not None
    assert before == (person.profile.contact_revision, person.profile.authorization_version)
    contacts = (await db_session.scalars(select(TravellerContactBindingModel))).all()
    assert len(contacts) == 1 and contacts[0].status == "current"
    assert service.crypto.decrypt(contacts[0].value_ciphertext) == person.phone


@pytest.mark.asyncio
async def test_other_tab_group_cannot_resume_or_change_the_active_grant(client, db_session, portal):
    _, group, person, _ = portal
    await begin(client, group, person.number)
    assert (await client.post(BASE + "/challenge", json={"answers": {"date_of_birth": "1990-02-03"}})).status_code == 200
    assert (await client.post(BASE + "/confirm", json={})).status_code == 200
    grant = await db_session.scalar(select(TravellerHistoryGrantModel))
    before = dict(grant.actor_evidence)
    denied = await client.get(BASE + "/history", params={"group_token": "different-tab-trip"})
    assert denied.status_code == 409 and person.number not in denied.text
    denied_selection = await client.post(BASE + "/passport-selection", json={
        "passport_id": str(person.passport.id), "group_token": "different-tab-trip",
    })
    assert denied_selection.status_code == 409 and person.number not in denied_selection.text
    await db_session.refresh(grant)
    assert grant.actor_evidence == before
    allowed = await client.get(BASE + "/history", params={"group_token": group.token})
    assert allowed.status_code == 200 and allowed.json()["passport"]["number"] == person.number
