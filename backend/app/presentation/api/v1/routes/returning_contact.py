"""New-number OTP verifies only the selected person's future contact binding."""

from fastapi import APIRouter, Depends, Request, Response

from app.application.travellers.claims import ReturningClaims
from app.application.travellers.contact_change import begin_contact_change, finish_contact_change, send_contact_change_code
from app.application.travellers.errors import ReuseError, ReuseReason
from app.infrastructure.security.traveller_reuse_rate_limiter import TravellerReuseRateLimiter
from app.infrastructure.whatsapp.otp_provider import get_otp_provider
from app.presentation.api.v1.routes.returning_dependencies import (
    CONTACT_COOKIE, GRANT_COOKIE, grant_secret, private_boundary, returning_service, set_secret_cookie,
)
from app.presentation.api.v1.schemas.returning_schemas import ClaimStageResponse, CodeVerifyRequest, ContactChangeRequest, OTPRequestResponse
from app.presentation.security.client_ip import trusted_client_ip

router = APIRouter(dependencies=[Depends(private_boundary)])


@router.post("/contact/request", response_model=OTPRequestResponse)
async def request_new_contact(
    body: ContactChangeRequest, request: Request, response: Response,
    token: str = Depends(grant_secret), service: ReturningClaims = Depends(returning_service),
) -> OTPRequestResponse:
    claim_token = await begin_contact_change(service, token, phone_number=body.phone_number)
    # Cookie is set before delivery so an uncertain provider result can recover
    # without reusing an OTP or changing the person's accepted current number.
    set_secret_cookie(response, CONTACT_COOKIE, claim_token, 600)
    expires, resend = await send_contact_change_code(service, claim_token, provider=get_otp_provider(service.settings),
        ip_address=trusted_client_ip(request), limiter=TravellerReuseRateLimiter())
    return OTPRequestResponse(expires_in_seconds=expires, resend_after_seconds=resend)


@router.post("/contact/verify", response_model=ClaimStageResponse)
async def verify_new_contact(
    body: CodeVerifyRequest, request: Request, response: Response,
    token: str = Depends(grant_secret), service: ReturningClaims = Depends(returning_service),
) -> ClaimStageResponse:
    claim_token = request.cookies.get(CONTACT_COOKIE)
    if not claim_token:
        raise ReuseError(ReuseReason.EXPIRED)
    updated = await finish_contact_change(service, token, claim_token, body.code)
    set_secret_cookie(response, GRANT_COOKIE, updated, 3600)
    return ClaimStageResponse(stage="review")
