"""One-time contact possession, independent from disclosure and mobile login."""

from __future__ import annotations

import asyncio
import hmac
import math
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from app.application.mobile.otp_provider import OTPProvider
from app.application.travellers.audit import record_claim_action
from app.application.travellers.claims import ReturningClaims
from app.application.travellers.errors import ReuseError, ReuseReason
from app.domain.services.traveller_verification import utc
from app.infrastructure.security.traveller_reuse_rate_limiter import TravellerReuseRateLimiter


async def request_code(
    service: ReturningClaims, secret: str, *, provider: OTPProvider,
    ip_address: str | None, limiter: TravellerReuseRateLimiter,
) -> tuple[int, int]:
    claim, _ = await service.locked(secret)
    now, settings = datetime.now(UTC), service.settings.mobile
    if claim.otp_verified_at is not None or claim.status not in {"created", "otp_pending", "otp_sending"}:
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    if claim.otp_resend_at and utc(claim.otp_resend_at) > now:
        raise ReuseError(ReuseReason.RATE_LIMITED, retry_after=math.ceil((utc(claim.otp_resend_at) - now).total_seconds()))
    if claim.otp_attempt_count >= claim.max_attempts or not claim.phone_ciphertext:
        raise ReuseError(ReuseReason.RATE_LIMITED)
    phone = service.crypto.decrypt(claim.phone_ciphertext)
    await limiter.consume(normalized_phone=phone, ip_address=ip_address)
    code = f"{secrets.randbelow(1_000_000):06d}"
    if settings.otp_provider == "development" and not service.settings.is_production and settings.otp_development_code:
        code = settings.otp_development_code.get_secret_value()
    otp_id = uuid.uuid4()
    cooldown = max(settings.otp_resend_cooldown_seconds, math.ceil(settings.otp_delivery_timeout_seconds) + 5)
    claim.otp_id, claim.otp_hash = otp_id, service.crypto.digest("otp", str(otp_id), code)
    claim.status = "otp_sending"
    claim.otp_expires_at = min(now + timedelta(seconds=settings.otp_ttl_seconds), utc(claim.expires_at))
    claim.otp_resend_at = now + timedelta(seconds=cooldown)
    # Resend deliberately does not reset attempts or extend the claim lifetime.
    await service.session.commit()
    delivered = False
    try:
        await asyncio.wait_for(provider.send_code(normalized_phone=phone, code=code,
            expires_in_seconds=settings.otp_ttl_seconds), timeout=settings.otp_delivery_timeout_seconds)
        delivered = True
    except Exception:
        # Provider payloads may contain phone/OTP; no exception text is logged.
        delivered = False
    claim, _ = await service.locked(secret)
    if claim.otp_id != otp_id or claim.status != "otp_sending":
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    claim.status = "otp_pending" if delivered else "created"
    if not delivered:
        claim.otp_hash = None
        await record_claim_action(service.session, claim, "otp_delivery_failed")
    await service.session.commit()
    if not delivered:
        raise ReuseError(ReuseReason.INFRASTRUCTURE, retry_after=cooldown)
    return settings.otp_ttl_seconds, cooldown


async def verify_code(service: ReturningClaims, secret: str, code: str) -> None:
    claim, _ = await service.locked(secret)
    now = datetime.now(UTC)
    if claim.otp_verified_at is not None:
        return  # Same claim can recover a lost success response; no extension.
    if (
        claim.status != "otp_pending" or claim.otp_id is None or not claim.otp_hash
        or claim.otp_expires_at is None or utc(claim.otp_expires_at) <= now
        or claim.otp_attempt_count >= claim.max_attempts
    ):
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    claim.otp_attempt_count += 1
    if not hmac.compare_digest(claim.otp_hash, service.crypto.digest("otp", str(claim.otp_id), code)):
        if claim.otp_attempt_count >= claim.max_attempts:
            claim.status, claim.otp_hash = "locked", None
        await record_claim_action(service.session, claim, "otp_failed")
        await service.session.commit()
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    claim.otp_hash, claim.otp_verified_at, claim.status = None, now, "otp_verified"
    await record_claim_action(service.session, claim, "otp_verified")
    await service.session.commit()
