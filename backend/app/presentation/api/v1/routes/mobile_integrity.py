"""Server-owned challenge and Apple key-registration endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.app_integrity import (
    MobileIntegrityRejected,
    MobileIntegrityUnavailable,
)
from app.application.mobile.integrity_service import MobileIntegrityService
from app.core.config.settings import get_settings
from app.core.security.mobile_jwt import MobileAccessClaims
from app.infrastructure.database.session import get_db_session
from app.infrastructure.security.mobile_integrity_challenges import (
    MobileIntegrityChallengeStore,
    get_mobile_integrity_challenge_store,
)
from app.infrastructure.security.mobile_integrity_providers import (
    MobileIntegrityProviderRegistry,
    get_mobile_integrity_provider_registry,
)
from app.presentation.api.v1.schemas.mobile_schemas import (
    MobileAppAttestRegistrationRequest,
    MobileAppAttestRegistrationResponse,
    MobileIntegrityChallengeRequest,
    MobileIntegrityChallengeResponse,
)
from app.presentation.dependencies.mobile_auth import require_unrestricted_mobile_claims

router = APIRouter()


def get_mobile_integrity_service(
    session: AsyncSession = Depends(get_db_session),
    challenge_store: MobileIntegrityChallengeStore = Depends(
        get_mobile_integrity_challenge_store
    ),
    providers: MobileIntegrityProviderRegistry = Depends(
        get_mobile_integrity_provider_registry
    ),
) -> MobileIntegrityService:
    return MobileIntegrityService(
        session=session,
        challenge_store=challenge_store,
        providers=providers,
    )


@router.post(
    "/integrity/challenges",
    response_model=MobileIntegrityChallengeResponse,
)
async def issue_mobile_integrity_challenge(
    body: MobileIntegrityChallengeRequest,
    response: Response,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    service: MobileIntegrityService = Depends(get_mobile_integrity_service),
) -> MobileIntegrityChallengeResponse:
    _no_store(response)
    mode = get_settings().mobile.app_integrity_mode
    try:
        challenge = await service.issue_challenge(claims=claims, request=body)
    except MobileIntegrityRejected as exc:
        raise _rejected() from exc
    except MobileIntegrityUnavailable as exc:
        raise _unavailable() from exc
    if challenge is None:
        return MobileIntegrityChallengeResponse(
            status="disabled",
            mode="disabled",
            required=False,
            provider=body.provider,
        )
    return MobileIntegrityChallengeResponse(
        status="issued",
        mode=mode,
        required=mode == "enforce",
        provider=challenge.provider,
        challenge_id=challenge.challenge_id,
        provider_request_hash=challenge.provider_request_hash,
        expires_at=datetime.fromtimestamp(challenge.expires_at_epoch, tz=UTC),
    )


@router.post(
    "/integrity/app-attest/keys/register",
    response_model=MobileAppAttestRegistrationResponse,
)
async def register_mobile_app_attest_key(
    body: MobileAppAttestRegistrationRequest,
    response: Response,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    service: MobileIntegrityService = Depends(get_mobile_integrity_service),
) -> MobileAppAttestRegistrationResponse:
    _no_store(response)
    try:
        await service.register_apple_key(claims=claims, request=body)
    except MobileIntegrityRejected as exc:
        raise _rejected() from exc
    except MobileIntegrityUnavailable as exc:
        raise _unavailable() from exc
    return MobileAppAttestRegistrationResponse()


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"


def _rejected() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="The mobile app integrity proof was rejected",
    )


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Mobile app integrity verification is temporarily unavailable",
        headers={"Retry-After": "30"},
    )


__all__ = ["get_mobile_integrity_service", "router"]
