"""Contact possession changes exactly one authorized person's future binding."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.application.travellers.contact_change import (
    begin_contact_change,
    finish_contact_change,
    send_contact_change_code,
)
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.grants import require_grant
from app.infrastructure.database.traveller_reuse_models import (
    TravellerClaimModel,
    TravellerContactBindingModel,
)
from tests.integration.test_returning_claims import successful_claim
from tests.integration.traveller_reuse_fixtures import (
    FakeLimiter,
    FakeOTP,
    reuse_context,
    seed_person,
)

NEW_PHONE = "+919876540001"


async def pending_change(service, token):
    claim_token = await begin_contact_change(service, token, phone_number=NEW_PHONE)
    provider = FakeOTP()
    await send_contact_change_code(service, claim_token, provider=provider, ip_address="127.0.0.1", limiter=FakeLimiter())
    return claim_token, provider


@pytest.mark.asyncio
async def test_retry_completed_during_otp_commit_gap_recovers_current_grant(
    db_session, test_settings, monkeypatch,
):
    from app.application.travellers import contact_change

    service, _, group = await reuse_context(db_session, test_settings)
    person = await seed_person(service, group)
    _, _, old_token = await successful_claim(service, group, person, "code")
    claim_token, provider = await pending_change(service, old_token)
    original_verify = contact_change.verify_code
    interleaved = False
    competing_result = None

    async def verify_then_complete_retry(*args):
        nonlocal interleaved, competing_result
        await original_verify(*args)
        if not interleaved:
            interleaved = True
            competing_result = await finish_contact_change(service, old_token, claim_token, provider.code)

    monkeypatch.setattr(contact_change, "verify_code", verify_then_complete_retry)
    result = await finish_contact_change(service, old_token, claim_token, provider.code)
    assert interleaved and result == competing_result and result != old_token
    assert person.profile.contact_revision == 2
    await require_grant(service, result, "history:read")
    with pytest.raises(ReuseError):
        await require_grant(service, old_token, "history:read")
    assert await db_session.scalar(select(func.count()).select_from(TravellerContactBindingModel).where(
        TravellerContactBindingModel.traveller_id == person.profile.id,
        TravellerContactBindingModel.status == "current",
    )) == 1


@pytest.mark.asyncio
async def test_new_contact_requires_otp_and_revokes_only_selected_person(db_session, test_settings):
    service, _, group = await reuse_context(db_session, test_settings)
    first, family = await seed_person(service, group), await seed_person(service, group, 2)
    _, source_claim, old_token = await successful_claim(service, group, first, "code")
    _, family_claim, family_token = await successful_claim(service, group, family, "code")
    previous_revision = first.profile.contact_revision
    claim_token, provider = await pending_change(service, old_token)
    assert first.profile.contact_revision == previous_revision
    with pytest.raises(ReuseError):
        await finish_contact_change(service, old_token, claim_token, "000000" if provider.code != "000000" else "000001")
    assert first.profile.contact_revision == previous_revision
    new_token = await finish_contact_change(service, old_token, claim_token, provider.code)
    assert new_token != old_token and first.profile.contact_revision == previous_revision + 1
    await db_session.refresh(source_claim)
    assert source_claim.status == "revoked" and source_claim.revoked_at is not None
    with pytest.raises(ReuseError):
        await require_grant(service, old_token, "history:read")
    await require_grant(service, new_token, "history:read")
    await require_grant(service, family_token, "history:read")
    await db_session.refresh(family_claim)
    assert family_claim.status == "authorized" and family_claim.revoked_at is None
    rows = (await db_session.scalars(select(TravellerContactBindingModel).where(
        TravellerContactBindingModel.traveller_id == first.profile.id,
    ))).all()
    current = [row for row in rows if row.status == "current"]
    assert len(current) == 1 and service.crypto.decrypt(current[0].value_ciphertext) == NEW_PHONE
    assert current[0].verified_at is not None and current[0].verification_evidence["method"] == "whatsapp_otp"
    historical = [row for row in rows if row.status == "historical"]
    assert len(historical) == 1 and service.crypto.decrypt(historical[0].value_ciphertext) == first.phone
    # A lost successful response recovers the same grant and never increments.
    assert await finish_contact_change(service, old_token, claim_token, provider.code) == new_token
    assert first.profile.contact_revision == previous_revision + 1


@pytest.mark.asyncio
async def test_retry_same_contact_preserves_claim_attempts_and_delivery(db_session, test_settings):
    service, _, group = await reuse_context(db_session, test_settings)
    person = await seed_person(service, group)
    _, _, token = await successful_claim(service, group, person, "passport")
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
    service, _, group = await reuse_context(db_session, test_settings)
    first, other = await seed_person(service, group), await seed_person(service, group, 2)
    _, _, token = await successful_claim(service, group, first, "code")
    claim_token, provider = await pending_change(service, token)
    _, _, other_token = await successful_claim(service, group, other, "code")
    with pytest.raises(ReuseError) as rejected:
        await finish_contact_change(service, other_token, claim_token, provider.code)
    assert rejected.value.reason == ReuseReason.VERIFICATION_FAILED
    assert first.profile.contact_revision == 1 and other.profile.contact_revision == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["contact_revision", "profile_revision", "source_revoked", "claim_expired"])
async def test_contact_change_rechecks_authority_after_code_delivery(db_session, test_settings, mutation):
    service, _, group = await reuse_context(db_session, test_settings)
    person = await seed_person(service, group)
    _, source, token = await successful_claim(service, group, person, "code")
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
        await finish_contact_change(service, token, claim_token, provider.code)
    current = await db_session.scalar(select(TravellerContactBindingModel).where(
        TravellerContactBindingModel.traveller_id == person.profile.id,
        TravellerContactBindingModel.status == "current",
    ))
    assert service.crypto.decrypt(current.value_ciphertext) == person.phone


@pytest.mark.asyncio
async def test_locked_contact_cannot_reset_otp_counter_by_requesting_again(db_session, test_settings):
    service, _, group = await reuse_context(db_session, test_settings)
    person = await seed_person(service, group)
    _, _, token = await successful_claim(service, group, person, "code")
    claim_token, provider = await pending_change(service, token)
    claim, _ = await service.locked(claim_token)
    claim.status = "locked"
    claim.otp_attempt_count = claim.max_attempts
    await db_session.commit()
    with pytest.raises(ReuseError):
        await begin_contact_change(service, token, phone_number=NEW_PHONE)
    assert provider.calls == 1
