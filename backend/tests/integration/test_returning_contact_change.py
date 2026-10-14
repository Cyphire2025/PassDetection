"""Contact possession changes exactly one authorized person's future binding."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.application.travellers.contact_change import (
    begin_contact_change,
    send_contact_change_code,
)
from app.application.travellers.draft_completion import complete_draft
from app.application.travellers.draft_contact import begin_draft_contact, verify_draft_contact
from app.application.travellers.drafts import draft_view, require_draft, start_draft
from app.application.travellers.errors import ReuseError
from app.application.travellers.grants import require_grant
from app.application.travellers.history import read_history
from app.infrastructure.database.traveller_reuse_models import (
    TravellerClaimModel,
    TravellerContactBindingModel,
)
from tests.integration.test_returning_claims import successful_claim
from tests.integration.test_returning_completion import completion_context
from tests.integration.test_returning_drafts import completion_body
from tests.integration.traveller_reuse_fixtures import (
    FakeLimiter,
    FakeOTP,
    seed_person,
)

NEW_PHONE = "+919876540001"


async def pending_change(service, token):
    secret, _ = await contact_draft(service, token)
    claim_token = await begin_draft_contact(service, token, secret, phone_number=NEW_PHONE)
    provider = FakeOTP()
    await send_contact_change_code(service, claim_token, provider=provider, ip_address="127.0.0.1", limiter=FakeLimiter())
    return claim_token, provider


async def contact_draft(service, token):
    review = await read_history(service, token)
    return await start_draft(service, token, expected_review_version=review["review_version"])


async def verify_change(service, token, pending, code):
    secret, _ = await contact_draft(service, token)
    await verify_draft_contact(service, token, secret, pending, code)
    review = await read_history(service, token)
    view = await draft_view(service, await require_draft(service, token, secret))
    return secret, completion_body(review, view)


async def submit_change(service, token, pending, code):
    secret, body = await verify_change(service, token, pending, code)
    return await complete_draft(service, token, secret, body)


@pytest.mark.asyncio
async def test_retry_after_otp_commit_gap_stages_once_and_does_not_promote_contact(db_session, test_settings, monkeypatch):
    from app.application.travellers import draft_contact
    service, _, _, person, token, _ = await completion_context(db_session, test_settings)
    pending, provider = await pending_change(service, token)
    secret, before = await contact_draft(service, token)
    original_verify = draft_contact.verify_code
    interleaved = False

    async def verify_then_retry(*args):
        nonlocal interleaved
        await original_verify(*args)
        if not interleaved:
            interleaved = True
            await verify_draft_contact(service, token, secret, pending, provider.code)

    monkeypatch.setattr(draft_contact, "verify_code", verify_then_retry)
    await verify_draft_contact(service, token, secret, pending, provider.code)
    after = await draft_view(service, await require_draft(service, token, secret))
    assert interleaved and after.revision == before.revision + 1
    assert person.profile.contact_revision == 1
    await require_grant(service, token, "history:read")


@pytest.mark.asyncio
async def test_new_contact_requires_otp_and_final_submit_revokes_only_selected_person(db_session, test_settings):
    service, _, group, first, old_token, _ = await completion_context(db_session, test_settings)
    family = await seed_person(service, group, 2)
    _, family_claim, family_token = await successful_claim(service, group, family, "code")
    claim_token, provider = await pending_change(service, old_token)
    with pytest.raises(ReuseError):
        await verify_change(service, old_token, claim_token, "000000" if provider.code != "000000" else "000001")
    assert first.profile.contact_revision == 1
    secret, body = await verify_change(service, old_token, claim_token, provider.code)
    assert first.profile.contact_revision == 1
    await require_grant(service, old_token, "history:read")
    result = await complete_draft(service, old_token, secret, body)
    assert first.profile.contact_revision == 2
    with pytest.raises(ReuseError):
        await require_grant(service, old_token, "history:read")
    await require_grant(service, family_token, "history:read")
    await db_session.refresh(family_claim)
    assert family_claim.status == "authorized" and family_claim.revoked_at is None
    rows = (await db_session.scalars(select(TravellerContactBindingModel).where(
        TravellerContactBindingModel.traveller_id == first.profile.id))).all()
    current = [row for row in rows if row.status == "current"]
    assert len(current) == 1 and service.crypto.decrypt(current[0].value_ciphertext) == NEW_PHONE
    assert current[0].verified_at is not None and current[0].verification_evidence["method"] == "whatsapp_otp"
    historical = [row for row in rows if row.status == "historical"]
    assert len(historical) == 1 and service.crypto.decrypt(historical[0].value_ciphertext) == first.phone
    assert await complete_draft(service, old_token, secret, body) == result
    assert first.profile.contact_revision == 2


@pytest.mark.asyncio
async def test_retry_same_contact_preserves_claim_attempts_and_delivery(db_session, test_settings):
    service, _, group, person, token, _ = await completion_context(db_session, test_settings)
    claim_token, provider = await pending_change(service, token)
    claim, _ = await service.locked(claim_token)
    original_expiry = claim.expires_at
    claim.otp_attempt_count = 2
    await db_session.commit()
    same_token = await begin_contact_change(service, token, phone_number=NEW_PHONE)
    assert same_token == claim_token
    await send_contact_change_code(service, same_token, provider=provider, ip_address="other-network", limiter=FakeLimiter())
    assert provider.calls == 1
    same_claim, _ = await service.locked(same_token)
    assert same_claim.otp_attempt_count == 2 and same_claim.expires_at == original_expiry
    assert await db_session.scalar(select(func.count()).select_from(TravellerClaimModel)) == 2


@pytest.mark.asyncio
async def test_contact_claim_cannot_be_attached_to_another_person_grant(db_session, test_settings):
    service, _, group, first, token, _ = await completion_context(db_session, test_settings)
    other = await seed_person(service, group, 2)
    claim_token, provider = await pending_change(service, token)
    _, _, other_token = await successful_claim(service, group, other, "code")
    with pytest.raises(ReuseError):
        await verify_change(service, other_token, claim_token, provider.code)
    assert first.profile.contact_revision == 1 and other.profile.contact_revision == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["contact_revision", "profile_revision", "source_revoked", "claim_expired"])
async def test_contact_change_rechecks_authority_after_code_delivery(db_session, test_settings, mutation):
    service, _, group, person, token, _ = await completion_context(db_session, test_settings)
    source = await db_session.scalar(select(TravellerClaimModel).where(TravellerClaimModel.traveller_id == person.profile.id))
    claim_token, provider = await pending_change(service, token)
    if mutation == "contact_revision":
        person.profile.contact_revision += 1
    elif mutation == "profile_revision":
        person.profile.revision += 1
    elif mutation == "source_revoked":
        source.revoked_at, source.status = datetime.now(UTC), "revoked"
    else:
        pending, _ = await service.locked(claim_token)
        pending.created_at = datetime.now(UTC) - timedelta(minutes=11)
        pending.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    with pytest.raises(ReuseError):
        await verify_change(service, token, claim_token, provider.code)
    current = await db_session.scalar(select(TravellerContactBindingModel).where(
        TravellerContactBindingModel.traveller_id == person.profile.id,
        TravellerContactBindingModel.status == "current",
    ))
    assert service.crypto.decrypt(current.value_ciphertext) == person.phone


@pytest.mark.asyncio
async def test_locked_contact_cannot_reset_otp_counter_by_requesting_again(db_session, test_settings):
    service, _, group, person, token, _ = await completion_context(db_session, test_settings)
    claim_token, provider = await pending_change(service, token)
    claim, _ = await service.locked(claim_token)
    claim.status = "locked"
    claim.otp_attempt_count = claim.max_attempts
    await db_session.commit()
    with pytest.raises(ReuseError):
        await begin_contact_change(service, token, phone_number=NEW_PHONE)
    assert provider.calls == 1
