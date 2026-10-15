"""OTP-proved contact change from an already authorized person-specific grant."""

import math
from datetime import UTC, datetime

from sqlalchemy import select

from app.application.mobile.otp_provider import OTPProvider
from app.application.travellers.claims import ReturningClaims
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.grants import require_grant
from app.application.travellers.otp import request_code
from app.domain.services.traveller_verification import utc
from app.domain.value_objects.phone_number import normalize_phone_number
from app.infrastructure.database.traveller_reuse_models import TravellerClaimModel
from app.infrastructure.security.traveller_reuse_rate_limiter import TravellerReuseRateLimiter


async def begin_contact_change(
    service: ReturningClaims, grant_token: str, *, phone_number: str,
) -> str:
    grant, scope, person = await require_grant(service, grant_token, "contact:change")
    phone = normalize_phone_number(phone_number)
    if phone is None:
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    # Recover a lost response using a deterministic, server-secret token bound
    # to the existing grant and new phone. Neither OTP attempts nor TTL reset.
    fingerprint = service.crypto.scoped_digest("phone", grant.agency_id, grant.company_id, phone)
    token = service.crypto.digest("contact-change-secret", grant.secret_hash, fingerprint)
    secret_hash = service.crypto.digest("claim", token)
    previous = await service.session.scalar(select(TravellerClaimModel).where(
        TravellerClaimModel.secret_hash == secret_hash,
        TravellerClaimModel.agency_id == grant.agency_id,
        TravellerClaimModel.company_id == grant.company_id,
        TravellerClaimModel.group_id == grant.group_id,
    ).with_for_update())
    if previous is not None:
        await service.locked(token)
        await service.session.commit()
        return token
    claim = service.new_claim(scope, method="phone", normalized_phone=phone,
        secret_hash=secret_hash, idempotency_key=f"contact:{secret_hash}")
    # Values are copied only from server-held, currently valid authorization.
    claim.traveller_id = person.id
    claim.passport_id = grant.passport_id
    claim.document_revision_id = grant.document_revision_id
    claim.expected_profile_revision = person.revision
    claim.expected_contact_revision = person.contact_revision
    claim.expected_authorization_version = person.authorization_version
    claim.required_question_count = 0
    claim.actor_kind = grant.actor_kind
    claim.actor_evidence = {"purpose": "contact_change", "source_grant_id": str(grant.id)}
    service.session.add(claim)
    await service.session.commit()
    return token


async def send_contact_change_code(
    service: ReturningClaims, token: str, *, provider: OTPProvider,
    ip_address: str | None, limiter: TravellerReuseRateLimiter,
) -> tuple[int, int]:
    claim, _ = await service.locked(token)
    now = datetime.now(UTC)
    if (claim.status == "otp_pending" and claim.otp_expires_at and utc(claim.otp_expires_at) > now
            and claim.otp_resend_at and utc(claim.otp_resend_at) > now):
        result = (math.ceil((utc(claim.otp_expires_at) - now).total_seconds()),
                  math.ceil((utc(claim.otp_resend_at) - now).total_seconds()))
        await service.session.commit()
        return result
    return await request_code(service, token, provider=provider, ip_address=ip_address, limiter=limiter)
