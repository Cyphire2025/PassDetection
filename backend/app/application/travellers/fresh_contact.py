"""Draft-bound public contact proof; uses the shared OTP verifier and quotas."""
import asyncio
import hmac
import math
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import select

from app.application.mobile.otp_provider import OTPProvider
from app.application.security.public_contact_proof import (
    CONTACT_PROOF_TTL_SECONDS,
    code_digest,
    digest,
    remaining,
    utc,
    verify_contact_code,
)
from app.application.travellers.draft_store import DraftStore
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.fresh_drafts import require_fresh_draft
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftContactProofModel as Proof,
)
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerReturningDraftModel as Draft,
)
from app.infrastructure.security.public_upload_otp_rate_limiter import PublicUploadOTPRateLimiter


async def locked_proof(service: DraftStore, draft: Draft) -> Proof | None:
    return cast(Proof | None, await service.session.scalar(select(Proof).where(Proof.draft_id == draft.id, Proof.agency_id == draft.agency_id)
        .with_for_update().execution_options(populate_existing=True)))


async def request_fresh_code(service: DraftStore, group_token: str, secret: str, *, email: str, phone: str,
    ip_address: str | None, provider: OTPProvider, limiter: PublicUploadOTPRateLimiter,
) -> tuple[uuid.UUID, int, int]:
    await limiter.consume(normalized_phone=phone, ip_address=ip_address)
    draft = await require_fresh_draft(service, group_token, secret)
    settings, now = service.settings.mobile, datetime.now(UTC)
    proof = await locked_proof(service, draft)
    email_hash, fingerprint = digest("email", email.lower().strip()), service.crypto.digest("draft-phone", phone)
    if proof and utc(proof.resend_available_at) > now:
        if proof.status == "pending" and utc(proof.expires_at) > now and proof.phone_fingerprint == fingerprint and hmac.compare_digest(proof.email_hash, email_hash):
            await service.session.commit()
            return proof.id, remaining(proof.expires_at, now), remaining(proof.resend_available_at, now)
        raise ReuseError(ReuseReason.RATE_LIMITED, retry_after=remaining(proof.resend_available_at, now))
    code = settings.otp_development_code.get_secret_value() if settings.otp_provider == "development" and settings.otp_development_code else f"{secrets.randbelow(1_000_000):06d}"
    cooldown = max(settings.otp_resend_cooldown_seconds, math.ceil(settings.otp_delivery_timeout_seconds) + 5)
    if proof is None:
        proof = Proof(draft_id=draft.id, agency_id=draft.agency_id, company_id=draft.company_id, created_at=now)
        service.session.add(proof)
    proof.id = challenge_id = uuid.uuid4()
    proof.email_hash, proof.phone_fingerprint, proof.phone_ciphertext = email_hash, fingerprint, service.crypto.encrypt(phone)
    proof.status, proof.code_hash, proof.attempt_count, proof.max_attempts = "sending", code_digest(challenge_id, code), 0, settings.otp_max_attempts
    proof.expires_at, proof.resend_available_at = now + timedelta(seconds=settings.otp_ttl_seconds), now + timedelta(seconds=cooldown)
    proof.updated_at, proof.verified_at, proof.proof_expires_at = now, None, None
    draft.verified_phone_ciphertext = draft.verified_phone_fingerprint = None
    draft.phone_verified_at = None
    draft.revision += 1
    await service.session.commit()
    delivered = False
    try:
        async with asyncio.timeout(settings.otp_delivery_timeout_seconds):
            await provider.send_code(normalized_phone=phone, code=code, expires_in_seconds=settings.otp_ttl_seconds)
        delivered = True
    except Exception:
        pass  # Provider data and destination never enter logs or responses.
    draft = await require_fresh_draft(service, group_token, secret)
    proof = await locked_proof(service, draft)
    if proof is None or proof.id != challenge_id or proof.status != "sending":
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    proof.status, proof.updated_at = ("pending" if delivered else "failed"), datetime.now(UTC)
    if not delivered:
        proof.code_hash = None
    await service.session.commit()
    if not delivered:
        raise ReuseError(ReuseReason.INFRASTRUCTURE, retry_after=cooldown)
    return proof.id, remaining(proof.expires_at, datetime.now(UTC)), remaining(proof.resend_available_at, datetime.now(UTC))


async def verify_fresh_code(service: DraftStore, group_token: str, secret: str, *, challenge_id: uuid.UUID, code: str) -> tuple[uuid.UUID, str, int]:
    draft = await require_fresh_draft(service, group_token, secret)
    proof, now = await locked_proof(service, draft), datetime.now(UTC)
    if proof is None or proof.id != challenge_id:
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    if proof.status == "verified" and proof.proof_expires_at and utc(proof.proof_expires_at) > now:
        await service.session.commit()
        return proof.id, service.crypto.decrypt(proof.phone_ciphertext), remaining(proof.proof_expires_at, now)
    if not verify_contact_code(proof, code, now):
        await service.session.commit()
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    draft.verified_phone_ciphertext, draft.verified_phone_fingerprint = proof.phone_ciphertext, proof.phone_fingerprint
    draft.phone_verified_at = proof.verified_at
    draft.revision += 1
    await service.session.commit()
    return proof.id, service.crypto.decrypt(proof.phone_ciphertext), CONTACT_PROOF_TTL_SECONDS


async def require_fresh_contact(service: DraftStore, draft: Draft, *, proof_id: uuid.UUID, email: str, phone: str) -> Proof:
    proof = await locked_proof(service, draft)
    if (proof is None or proof.id != proof_id or proof.status != "verified" or proof.proof_expires_at is None
            or utc(proof.proof_expires_at) <= datetime.now(UTC) or proof.verified_at is None
            or not hmac.compare_digest(proof.email_hash, digest("email", email.lower().strip()))
            or not hmac.compare_digest(proof.phone_fingerprint, service.crypto.digest("draft-phone", phone))):
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    return proof
