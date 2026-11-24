"""Issue public contact OTPs and persist delivery outcomes outside row locks."""

from __future__ import annotations

import hmac
import math
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.otp_provider import OTPDeliveryError
from app.application.security.public_contact_proof import code_digest as _code_digest
from app.application.security.public_contact_proof import digest as _digest
from app.application.security.public_contact_proof import remaining as _remaining
from app.application.security.public_contact_proof import utc as _utc
from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.infrastructure.database.public_upload_contact_model import (
    PublicUploadContactChallengeModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.security.mobile_otp_rate_limiter import (
    OTPRateLimitExceeded,
    OTPRateLimitUnavailable,
)
from app.infrastructure.security.public_upload_otp_rate_limiter import PublicUploadOTPRateLimiter
from app.infrastructure.whatsapp.otp_provider import get_otp_provider
from app.presentation.api.v1.schemas.public_upload_contact_schemas import (
    PublicContactOTPRequest,
    PublicContactOTPRequestResponse,
)
from app.presentation.security.client_ip import trusted_client_ip

from .contact_challenges import _locked_challenge, _locked_upload, _no_store

router = APIRouter()
logger = get_logger("app.presentation.api.v1.routes.passport_routes.contact_verification")


@router.post("/{submission_id}/contact-otp/request", response_model=PublicContactOTPRequestResponse)
async def request_public_contact_otp(
    submission_id: uuid.UUID,
    body: PublicContactOTPRequest,
    request: Request,
    response: Response,
    upload_session_id: str = Header(..., alias="X-Upload-Session-ID", min_length=32, max_length=128),
    session: AsyncSession = Depends(get_db_session),
) -> PublicContactOTPRequestResponse:
    _no_store(response)
    submission = await _locked_upload(session, submission_id, body.group_token, upload_session_id)
    settings = get_settings().mobile
    # Public uploads support families of up to twenty members, including shared
    # household numbers, without altering the stricter mobile login quotas.
    try:
        await PublicUploadOTPRateLimiter().consume(
            normalized_phone=body.phone_number, ip_address=trusted_client_ip(request),
        )
    except OTPRateLimitExceeded as exc:
        raise HTTPException(429, "Please wait before requesting another code.") from exc
    except OTPRateLimitUnavailable as exc:
        raise HTTPException(503, "WhatsApp verification is temporarily unavailable.") from exc

    now = datetime.now(UTC)
    challenge = await _locked_challenge(session, submission_id)
    email_hash = _digest("email", str(body.email).lower().strip())
    session_hash = _digest("upload-session", upload_session_id)
    if challenge is not None and _utc(challenge.resend_available_at) > now:
        retry_after = _remaining(challenge.resend_available_at, now)
        if (
            challenge.status == "pending" and _utc(challenge.expires_at) > now
            and challenge.phone_number == body.phone_number
            and hmac.compare_digest(challenge.email_hash, email_hash)
            and hmac.compare_digest(challenge.upload_session_hash, session_hash)
        ):
            return PublicContactOTPRequestResponse(
                challenge_id=challenge.id,
                expires_in_seconds=_remaining(challenge.expires_at, now),
                resend_after_seconds=retry_after,
            )
        raise HTTPException(
            429, "Please wait before requesting another code.",
            headers={"Retry-After": str(retry_after), "Cache-Control": "no-store"},
        )

    challenge_id = uuid.uuid4()
    development_code = settings.otp_development_code
    code = (
        development_code.get_secret_value()
        if settings.otp_provider == "development" and development_code is not None
        else f"{secrets.randbelow(1_000_000):06d}"
    )
    # The durable submission row lock serializes creation and rotation, including
    # when no challenge exists yet. There can be only one row per submission.
    if challenge is None:
        challenge = PublicUploadContactChallengeModel(submission_id=submission_id)
        session.add(challenge)
    cooldown = max(settings.otp_resend_cooldown_seconds, math.ceil(settings.otp_delivery_timeout_seconds) + 5)
    challenge.id = challenge_id
    challenge.group_id = submission.group_id
    challenge.upload_session_hash = session_hash
    challenge.email_hash = email_hash
    challenge.phone_number = body.phone_number
    challenge.code_hash = _code_digest(challenge_id, code)
    challenge.status = "sending"
    challenge.attempt_count = 0
    challenge.max_attempts = settings.otp_max_attempts
    challenge.expires_at = now + timedelta(seconds=settings.otp_ttl_seconds)
    challenge.resend_available_at = now + timedelta(seconds=cooldown)
    challenge.verified_at = None
    challenge.proof_expires_at = None
    challenge.consumed_at = None
    challenge.created_at = now
    challenge.updated_at = now
    await session.commit()

    # No database locks are held while Meta is contacted. Sending is fail-closed:
    # the code is unusable until the successful result is durably recorded.
    delivered = False
    try:
        await get_otp_provider().send_code(
            normalized_phone=body.phone_number,
            code=code,
            expires_in_seconds=settings.otp_ttl_seconds,
        )
        delivered = True
    except OTPDeliveryError as exc:
        logger.warning("public_contact_otp_delivery_failed", error_code=exc.code)
    except Exception as exc:
        logger.error("public_contact_otp_delivery_failed", error_type=type(exc).__name__)

    await _locked_upload(session, submission_id, body.group_token, upload_session_id)
    challenge = await _locked_challenge(session, submission_id)
    if challenge is None or challenge.id != challenge_id or challenge.status != "sending":
        raise HTTPException(409, "The verification request changed. Request a new code.")
    challenge.status = "pending" if delivered else "failed"
    if not delivered:
        challenge.code_hash = None
    challenge.updated_at = datetime.now(UTC)
    await session.commit()
    if not delivered:
        raise HTTPException(
            503, "We could not send your WhatsApp code. Please try again shortly.",
            headers={"Retry-After": str(cooldown), "Cache-Control": "no-store"},
        )
    return PublicContactOTPRequestResponse(
        challenge_id=challenge_id,
        expires_in_seconds=_remaining(challenge.expires_at, datetime.now(UTC)),
        resend_after_seconds=_remaining(challenge.resend_available_at, datetime.now(UTC)),
    )
