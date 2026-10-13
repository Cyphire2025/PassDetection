"""All three selected routes and denial paths on durable database state."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.application.travellers.document_challenge import (
    change_document_question,
    verify_document_answers,
)
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.grants import confirm_claim, require_grant
from app.application.travellers.history import read_history
from app.application.travellers.matching import phone_candidates, select_candidate
from app.application.travellers.otp import request_code, verify_code
from app.domain.services.traveller_verification import DocumentQuestion, VerificationFailure
from app.infrastructure.database.traveller_reuse_models import (
    TravellerAttemptBudgetModel,
    TravellerHistoryGrantModel,
)
from app.presentation.api.v1.routes.returning_history import historical_document
from app.presentation.api.v1.schemas.returning_history_schemas import ReturningHistoryResponse
from tests.integration.traveller_reuse_fixtures import (
    FakeLimiter,
    FakeOTP,
    reuse_context,
    seed_person,
)


async def phone_claim(service, group, person):
    secret, claim = await service.start(group_token=group.token, method="phone", phone=person.phone)
    provider = FakeOTP()
    await request_code(service, secret, provider=provider, ip_address="127.0.0.1", limiter=FakeLimiter())
    await verify_code(service, secret, provider.code)
    return secret, claim


async def successful_claim(service, group, person, method):
    if method == "phone":
        secret, claim = await phone_claim(service, group, person)
    else:
        secret, claim = await service.start(group_token=group.token, method=method,
            passport_number=person.number if method == "passport" else None,
            issuing_country="IND", individual_code=person.code if method == "code" else None)
    claim, questions = await service.bind_passport(secret, passport_number=person.number, issuing_country="IND")
    if method == "passport":
        assert questions == (DocumentQuestion.DATE_OF_BIRTH,)
        await verify_document_answers(service.session, claim, person.document,
                                       {"date_of_birth": "1990-02-03"}, datetime.now(UTC))
        await service.session.commit()
    else:
        assert not questions
    token = await confirm_claim(service, secret, acting_for="self", contact_change_confirmed=False)
    return secret, claim, token


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["phone", "passport", "code"])
async def test_all_selected_routes_complete_and_history_is_allowlisted(db_session, test_settings, method):
    service, _, group = await reuse_context(db_session, test_settings)
    person = await seed_person(service, group)
    secret, claim, token = await successful_claim(service, group, person, method)
    result = ReturningHistoryResponse.model_validate(await read_history(service, token)).model_dump(mode="json")
    assert result["passport"]["number"] == person.number
    assert result["contact_phone"] == person.phone
    assert result["display_name"] == "Synthetic1 Surname1"
    encoded = json.dumps(result)
    for forbidden in ("MUST-NOT-LEAK", "private-secret", "object_key", "secret_hash", "expected_answer", str(person.profile.id)):
        assert forbidden not in encoded
    assert (claim.otp_verified_at is not None) == (method == "phone")
    assert await confirm_claim(service, secret, acting_for="self", contact_change_confirmed=False) == token


@pytest.mark.asyncio
async def test_otp_and_candidate_selection_alone_do_not_disclose(db_session, test_settings):
    service, _, group = await reuse_context(db_session, test_settings)
    person = await seed_person(service, group)
    secret, claim = await service.start(group_token=group.token, method="phone", phone=person.phone)
    locked, scope = await service.locked(secret)
    with pytest.raises(ReuseError):
        await phone_candidates(db_session, scope, locked, service.crypto, datetime.now(UTC))
    provider = FakeOTP()
    await request_code(service, secret, provider=provider, ip_address="127.0.0.1", limiter=FakeLimiter())
    await verify_code(service, secret, provider.code)
    locked, scope = await service.locked(secret)
    items, narrowing = await phone_candidates(db_session, scope, locked, service.crypto, datetime.now(UTC))
    assert not narrowing and len(items) == 1
    assert person.number not in items[0].passport_hint and "Synthetic1" not in items[0].label
    await db_session.flush()
    await select_candidate(db_session, scope, locked, service.crypto, items[0].handle, datetime.now(UTC))
    await db_session.commit()
    with pytest.raises((ReuseError, VerificationFailure)):
        await confirm_claim(service, secret, acting_for="self", contact_change_confirmed=False)
    with pytest.raises(ReuseError):
        await require_grant(service, str(person.profile.id), "history:read")


@pytest.mark.asyncio
async def test_shared_candidate_cannot_switch_to_another_person(db_session, test_settings):
    service, _, group = await reuse_context(db_session, test_settings)
    first, second = await seed_person(service, group), await seed_person(service, group, 2)
    secret, _ = await phone_claim(service, group, first)
    claim, scope = await service.locked(secret)
    items, _ = await phone_candidates(db_session, scope, claim, service.crypto, datetime.now(UTC))
    await db_session.flush()
    handle = next(item.handle for item in items if "Surname1" in item.label)
    await select_candidate(db_session, scope, claim, service.crypto, handle, datetime.now(UTC))
    await db_session.commit()
    with pytest.raises(ReuseError):
        await service.bind_passport(secret, passport_number=second.number, issuing_country="IND")
    assert claim.traveller_id == first.profile.id


@pytest.mark.asyncio
async def test_large_shared_phone_requires_narrowing(db_session, test_settings):
    service, _, group = await reuse_context(db_session, test_settings)
    first = await seed_person(service, group)
    for index in range(2, 22):
        await seed_person(service, group, index)
    secret, _ = await phone_claim(service, group, first)
    claim, scope = await service.locked(secret)
    items, narrowing = await phone_candidates(db_session, scope, claim, service.crypto, datetime.now(UTC))
    assert items == () and narrowing


@pytest.mark.asyncio
async def test_alternate_question_preserves_person_budget_across_claims(db_session, test_settings):
    service, _, group = await reuse_context(db_session, test_settings)
    person = await seed_person(service, group)
    for attempt in range(5):
        secret, _ = await service.start(group_token=group.token, method="passport", passport_number=person.number, issuing_country="IND")
        claim, questions = await service.bind_passport(secret)
        previous_expiry = claim.expires_at
        selected = await change_document_question(db_session, claim, person.document, DocumentQuestion.ISSUE_DATE, datetime.now(UTC))
        assert selected == (DocumentQuestion.ISSUE_DATE,)
        assert claim.expires_at == previous_expiry
        with pytest.raises(ReuseError) as failure:
            await verify_document_answers(db_session, claim, person.document, {"issue_date": "2000-01-01"}, datetime.now(UTC))
        assert failure.value.reason == ReuseReason.VERIFICATION_FAILED
    budget = await db_session.get(TravellerAttemptBudgetModel, person.profile.id)
    assert budget.failure_count == 5
    fixed_cooldown = budget.cooldown_until
    secret, _ = await service.start(group_token=group.token, method="passport", passport_number=person.number, issuing_country="IND")
    with pytest.raises(ReuseError) as limited:
        await service.bind_passport(secret)
    assert limited.value.reason == ReuseReason.RATE_LIMITED and budget.cooldown_until == fixed_cooldown


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["company", "group", "profile", "contact", "revoked", "source_claim", "expired", "withdrawn", "permission", "document"])
async def test_grant_rechecks_live_authority_on_every_read(db_session, test_settings, mutation):
    service, company, group = await reuse_context(db_session, test_settings)
    person = await seed_person(service, group)
    _, claim, token = await successful_claim(service, group, person, "code")
    grant = await db_session.scalar(select(TravellerHistoryGrantModel))
    if mutation == "company":
        company.revision += 1
    elif mutation == "group":
        group.company_revision += 1
    elif mutation == "profile":
        person.profile.revision += 1
    elif mutation == "contact":
        person.profile.contact_revision += 1
    elif mutation == "revoked":
        grant.revoked_at = datetime.now(UTC)
    elif mutation == "source_claim":
        claim.revoked_at, claim.status = datetime.now(UTC), "revoked"
    elif mutation == "expired":
        grant.inactivity_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    elif mutation == "withdrawn":
        person.profile.reuse_permission_status = "withdrawn"
    elif mutation == "permission":
        person.profile.reuse_permission_evidence = {}
    else:
        person.passport.is_default = False
        person.passport.status = "lost"
    await db_session.commit()
    with pytest.raises(ReuseError):
        await read_history(service, token)


@pytest.mark.asyncio
async def test_document_fetch_cannot_use_someone_elses_asset_id(db_session, test_settings):
    service, _, group = await reuse_context(db_session, test_settings)
    first, second = await seed_person(service, group), await seed_person(service, group, 2)
    _, _, token = await successful_claim(service, group, first, "code")
    for identifier in (second.asset.id, uuid.uuid4()):
        with pytest.raises(ReuseError):
            await historical_document(identifier, token=token, service=service)


@pytest.mark.asyncio
async def test_wrong_individual_code_uses_person_budget_across_new_claims(db_session, test_settings):
    service, _, group = await reuse_context(db_session, test_settings)
    person = await seed_person(service, group)
    for _ in range(5):
        secret, _ = await service.start(group_token=group.token, method="code", individual_code="incorrect")
        with pytest.raises(ReuseError) as failure:
            await service.bind_passport(secret, passport_number=person.number, issuing_country="IND")
        assert failure.value.reason == ReuseReason.VERIFICATION_FAILED
    secret, _ = await service.start(group_token=group.token, method="code", individual_code=person.code)
    with pytest.raises(ReuseError) as limited:
        await service.bind_passport(secret, passport_number=person.number, issuing_country="IND")
    assert limited.value.reason == ReuseReason.RATE_LIMITED


@pytest.mark.asyncio
async def test_unproved_typo_can_be_corrected_without_resetting_budget(db_session, test_settings):
    service, _, group = await reuse_context(db_session, test_settings)
    person = await seed_person(service, group)
    secret, _ = await service.start(group_token=group.token, method="code", individual_code="typo")
    with pytest.raises(ReuseError):
        await service.bind_passport(secret, passport_number=person.number, issuing_country="IND")
    claim, questions = await service.bind_passport(secret, individual_code=person.code)
    assert not questions and claim.failed_answer_sets == 1
    budget = await db_session.get(TravellerAttemptBudgetModel, person.profile.id)
    assert budget.failure_count == 1


@pytest.mark.asyncio
async def test_missing_permission_evidence_excludes_even_masked_candidates(db_session, test_settings):
    service, _, group = await reuse_context(db_session, test_settings)
    person = await seed_person(service, group)
    person.profile.reuse_permission_evidence = {}
    await db_session.commit()
    secret, _ = await phone_claim(service, group, person)
    claim, scope = await service.locked(secret)
    items, _ = await phone_candidates(db_session, scope, claim, service.crypto, datetime.now(UTC))
    assert items == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["retention_expired", "purged", "oversized", "unsupported_mime", "no_basis"])
async def test_review_and_private_delivery_share_document_availability(db_session, test_settings, mutation):
    service, _, group = await reuse_context(db_session, test_settings)
    person = await seed_person(service, group)
    _, _, token = await successful_claim(service, group, person, "code")
    if mutation == "retention_expired":
        person.asset.retention_until = datetime.now(UTC) - timedelta(seconds=1)
    elif mutation == "purged":
        person.asset.purged_at = datetime.now(UTC)
    elif mutation == "oversized":
        person.asset.byte_size = 21 * 1024 * 1024
    elif mutation == "unsupported_mime":
        person.asset.content_type = "text/html"
    else:
        person.asset.retention_basis = ""
    await db_session.commit()
    result = await read_history(service, token)
    assert result["documents"][0]["available"] is False
    assert result["suitability"]["outcome"] == "replacement_required"
    with pytest.raises(ReuseError):
        await historical_document(person.asset.id, token=token, service=service)
