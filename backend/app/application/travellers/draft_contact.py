"""OTP verification stages possession evidence; only final Submit promotes it."""
from datetime import UTC, datetime

from sqlalchemy import select

from app.application.travellers.claims import ReturningClaims
from app.application.travellers.contact_change import begin_contact_change
from app.application.travellers.drafts import require_draft
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.otp import verify_code
from app.domain.services.traveller_verification import utc
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerReturningDraftModel as Draft,
)
from app.infrastructure.database.traveller_reuse_models import TravellerClaimModel as Claim


async def begin_draft_contact(service: ReturningClaims, token: str, secret: str, *, phone_number: str) -> str:
    draft = await require_draft(service, token, secret)
    draft_id = draft.id
    claim_token = await begin_contact_change(service, token, phone_number=phone_number)
    claim, _ = await service.locked(claim_token)
    previous = claim.actor_evidence.get("draft_id")
    if previous and previous != str(draft_id):
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    claim.actor_evidence = {**claim.actor_evidence, "draft_id": str(draft_id)}
    await service.session.commit()
    return claim_token


async def verify_draft_contact(service: ReturningClaims, token: str, secret: str, claim_token: str, code: str) -> None:
    draft = await require_draft(service, token, secret)
    claim, _ = await service.locked(claim_token)
    if (claim.actor_evidence.get("purpose") != "contact_change" or claim.actor_evidence.get("draft_id") != str(draft.id)
            or claim.traveller_id != draft.traveller_id):
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    await verify_code(service, claim_token, code)  # Attempt evidence commits independently.
    draft = await require_draft(service, token, secret)
    claim, _ = await service.locked(claim_token)
    if claim.otp_verified_at is None or not claim.phone_ciphertext or not claim.phone_fingerprint:
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    if draft.verified_contact_claim_id != claim.id:
        draft.verified_contact_claim_id = claim.id
        draft.verified_phone_ciphertext, draft.verified_phone_fingerprint = claim.phone_ciphertext, claim.phone_fingerprint
        draft.phone_verified_at = claim.otp_verified_at
        draft.revision += 1
    await service.session.commit()


async def staged_contact_claim(service: ReturningClaims, draft: Draft) -> Claim | None:
    if draft.verified_contact_claim_id is None:
        return None
    # Fixed draft expiry bounds this already verified evidence. Claim challenge
    # expiry limits submitting OTP answers; it never authorizes another person.
    claim = await service.session.scalar(select(Claim).where(Claim.id == draft.verified_contact_claim_id,
        Claim.agency_id == draft.agency_id, Claim.company_id == draft.company_id,
        Claim.group_id == draft.group_id, Claim.traveller_id == draft.traveller_id).with_for_update().execution_options(populate_existing=True))
    if (claim is None or claim.revoked_at is not None or claim.otp_verified_at is None
            or claim.phone_ciphertext != draft.verified_phone_ciphertext or claim.phone_fingerprint != draft.verified_phone_fingerprint
            or claim.otp_verified_at != draft.phone_verified_at or claim.expected_contact_revision != draft.contact_revision
            or draft.phone_verified_at is None or utc(claim.otp_verified_at) > datetime.now(UTC)):
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    contact_change = claim.actor_evidence.get("purpose") == "contact_change" and claim.actor_evidence.get("draft_id") == str(draft.id)
    recovery = claim.actor_evidence.get("pending_contact_change")
    recovery_change = isinstance(recovery, dict) and recovery.get("purpose") == "pending_contact_change" and recovery.get("fingerprint") == claim.phone_fingerprint
    if not contact_change and not recovery_change:
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    return claim
