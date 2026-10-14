"""Fresh-draft contact possession verification, never a history lookup."""
from fastapi import APIRouter, Depends, Request

from app.application.travellers.draft_store import FreshDraftStore
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.fresh_contact import request_fresh_code, verify_fresh_code
from app.infrastructure.security.mobile_otp_rate_limiter import (
    OTPRateLimitExceeded,
    OTPRateLimitUnavailable,
)
from app.infrastructure.security.public_upload_otp_rate_limiter import PublicUploadOTPRateLimiter
from app.infrastructure.whatsapp.otp_provider import get_otp_provider
from app.presentation.api.v1.routes.fresh_draft_dependencies import fresh_store, fresh_token
from app.presentation.api.v1.routes.returning_dependencies import private_boundary
from app.presentation.api.v1.schemas.public_upload_contact_schemas import (
    PublicContactOTPRequest,
    PublicContactOTPRequestResponse,
    PublicContactOTPVerifyRequest,
    PublicContactOTPVerifyResponse,
)
from app.presentation.security.client_ip import trusted_client_ip

router = APIRouter(dependencies=[Depends(private_boundary)])


@router.post("/{group_token}/contact/request", response_model=PublicContactOTPRequestResponse)
async def request_code(group_token: str, body: PublicContactOTPRequest, request: Request,
    secret: str = Depends(fresh_token), service: FreshDraftStore = Depends(fresh_store),
) -> PublicContactOTPRequestResponse:
    if body.group_token != group_token:
        raise ReuseError(ReuseReason.UNAVAILABLE)
    try:
        result = await request_fresh_code(service, group_token, secret, email=str(body.email), phone=body.phone_number,
            ip_address=trusted_client_ip(request), provider=get_otp_provider(service.settings), limiter=PublicUploadOTPRateLimiter())
    except OTPRateLimitExceeded as exc:
        raise ReuseError(ReuseReason.RATE_LIMITED) from exc
    except OTPRateLimitUnavailable as exc:
        raise ReuseError(ReuseReason.INFRASTRUCTURE) from exc
    return PublicContactOTPRequestResponse(challenge_id=result[0], expires_in_seconds=result[1], resend_after_seconds=result[2])


@router.post("/{group_token}/contact/verify", response_model=PublicContactOTPVerifyResponse)
async def verify_code(group_token: str, body: PublicContactOTPVerifyRequest,
    secret: str = Depends(fresh_token), service: FreshDraftStore = Depends(fresh_store),
) -> PublicContactOTPVerifyResponse:
    if body.group_token != group_token:
        raise ReuseError(ReuseReason.UNAVAILABLE)
    result = await verify_fresh_code(service, group_token, secret, challenge_id=body.challenge_id, code=body.code)
    return PublicContactOTPVerifyResponse(phone_verification_id=result[0], phone_number=result[1], expires_in_seconds=result[2])
