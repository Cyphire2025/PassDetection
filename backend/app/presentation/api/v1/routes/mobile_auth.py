"""Bearer-only authentication for passenger, Client Manager, and coordinator apps."""

from __future__ import annotations

import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.otp_provider import OTPDeliveryError, get_otp_provider
from app.application.use_cases.whatsapp.contact_normalization import normalize_whatsapp_phone
from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.core.security.mobile_jwt import (
    MobileAccessClaims,
    create_mobile_access_token,
    create_mobile_refresh_token,
    hash_mobile_lookup,
    hash_mobile_otp_code,
    hash_mobile_refresh_token,
    hash_mobile_secondary_factor,
)
from app.core.security.password import hash_password, verify_password
from app.domain.entities.entities import GroupStatus, UserRole
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerProfileModel,
    GCGroupAccessModel,
    MobileDeviceSessionModel,
    MobileOTPChallengeModel,
    MobilePassengerIdentityModel,
    MobileRefreshTokenModel,
)
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel, UserModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.security.login_attempt_limiter import LoginAttemptLimiter
from app.infrastructure.security.mobile_otp_rate_limiter import (
    MobileOTPRateLimiter,
    OTPRateLimitExceeded,
    OTPRateLimitUnavailable,
)
from app.presentation.api.v1.schemas.mobile_schemas import (
    MobileActivationRequest,
    MobileClaimVerifyRequest,
    MobileCredentialLoginRequest,
    MobileDeviceInput,
    MobileLogoutRequest,
    MobileOTPRequest,
    MobileOTPRequestResponse,
    MobileOTPVerifyRequest,
    MobileOTPVerifyResponse,
    MobilePasswordChangeRequest,
    MobilePrincipalResponse,
    MobileRefreshRequest,
    MobileTokenResponse,
    MobileTripClaimSummary,
)
from app.presentation.dependencies.mobile_auth import get_current_mobile_claims


def _set_mobile_auth_no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"


router = APIRouter(dependencies=[Depends(_set_mobile_auth_no_store)])
logger = get_logger(__name__)


@router.post(
    "/otp/request",
    response_model=MobileOTPRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_passenger_otp(
    body: MobileOTPRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> MobileOTPRequestResponse:
    _require_mobile_enabled()
    settings = get_settings().mobile
    normalized_phone = normalize_whatsapp_phone(body.phone_number)
    limiter_value = normalized_phone or f"invalid:{body.phone_number.strip().casefold()}"
    try:
        await MobileOTPRateLimiter().consume(
            normalized_phone=limiter_value,
            ip_address=_client_ip(request),
        )
    except OTPRateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Please wait before requesting another code",
        ) from exc
    except OTPRateLimitUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OTP verification is temporarily unavailable",
        ) from exc

    phone_lookup_hash = hash_mobile_lookup(limiter_value, purpose="passenger-phone")
    now = datetime.now(tz=UTC)
    existing = (
        await session.execute(
            select(MobileOTPChallengeModel)
            .where(
                MobileOTPChallengeModel.phone_lookup_hash == phone_lookup_hash,
                MobileOTPChallengeModel.status == "pending",
                MobileOTPChallengeModel.expires_at > now,
                MobileOTPChallengeModel.resend_available_at > now,
            )
            .order_by(MobileOTPChallengeModel.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return MobileOTPRequestResponse(
            challenge_id=existing.id,
            expires_in_seconds=max(1, int((existing.expires_at - now).total_seconds())),
            resend_after_seconds=max(
                1, int((existing.resend_available_at - now).total_seconds())
            ),
        )

    challenge_id = uuid.uuid4()
    configured_code = settings.otp_development_code
    code = (
        configured_code.get_secret_value()
        if configured_code is not None and settings.otp_provider == "development"
        else f"{secrets.randbelow(1_000_000):06d}"
    )
    eligible = (
        await _eligible_passenger_identities(session, phone_lookup_hash)
        if normalized_phone is not None
        else []
    )
    agencies = {identity.agency_id for identity, _access, _group in eligible}
    provider_reference: str | None = None
    delivery_status = "not_attempted"
    provider_error_code: str | None = None
    if eligible:
        try:
            provider_reference = await get_otp_provider().send_code(
                normalized_phone=normalized_phone or "",
                code=code,
                expires_in_seconds=settings.otp_ttl_seconds,
            )
            delivery_status = "delivered"
        except OTPDeliveryError as exc:
            # The response remains neutral; logs/audit contain no phone or OTP.
            provider_reference = None
            delivery_status = "failed"
            provider_error_code = type(exc).__name__
            logger.warning(
                "mobile_otp_delivery_failed",
                provider=settings.otp_provider,
                error_code=provider_error_code,
            )
    challenge = MobileOTPChallengeModel(
        id=challenge_id,
        agency_id=next(iter(agencies)) if len(agencies) == 1 else None,
        passenger_identity_id=eligible[0][0].id if len(eligible) == 1 else None,
        subject_type="passenger",
        purpose="login",
        phone_lookup_hash=phone_lookup_hash,
        challenge_token_hash=hash_mobile_lookup(
            secrets.token_urlsafe(32), purpose="otp-challenge-token"
        ),
        code_hash=hash_mobile_otp_code(challenge_id, code),
        provider=settings.otp_provider,
        provider_reference=provider_reference,
        status="cancelled" if delivery_status == "failed" else "pending",
        attempt_count=0,
        max_attempts=settings.otp_max_attempts,
        resend_count=0,
        max_resends=3,
        resend_available_at=now + timedelta(seconds=settings.otp_resend_cooldown_seconds),
        expires_at=now + timedelta(seconds=settings.otp_ttl_seconds),
        request_ip_hash=_request_digest(request, "ip"),
        user_agent_hash=_request_digest(request, "user-agent"),
        created_at=now,
        updated_at=now,
    )
    session.add(challenge)
    await session.flush()
    await AuditLogRepository(session).record(
        action="mobile.otp_requested",
        entity_type="mobile_otp_challenge",
        agency_id=challenge.agency_id,
        entity_id=str(challenge.id),
        ip_address=_client_ip(request),
        metadata={
            "provider": settings.otp_provider,
            "delivery_status": delivery_status,
            "provider_error_code": provider_error_code,
            "eligible_identity_count": len(eligible),
        },
    )
    return MobileOTPRequestResponse(
        challenge_id=challenge.id,
        expires_in_seconds=settings.otp_ttl_seconds,
        resend_after_seconds=settings.otp_resend_cooldown_seconds,
    )


@router.post("/otp/verify", response_model=MobileOTPVerifyResponse)
async def verify_passenger_otp(
    body: MobileOTPVerifyRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> MobileOTPVerifyResponse:
    _require_mobile_enabled()
    challenge = await _locked_challenge(session, body.challenge_id)
    await _verify_challenge_code(session, challenge, body.code)
    now = datetime.now(tz=UTC)
    challenge.status = "verified"
    challenge.verified_at = now
    challenge.updated_at = now
    eligible = await _eligible_passenger_identities(
        session, challenge.phone_lookup_hash
    )
    if not eligible:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired verification code",
        )
    if len(eligible) == 1 and not eligible[0][0].requires_secondary_verification:
        identity, access, _group = eligible[0]
        challenge.status = "consumed"
        challenge.consumed_at = now
        challenge.passenger_identity_id = identity.id
        tokens = await _issue_passenger_session(
            session,
            identity=identity,
            access=access,
            device=body.device,
            request=request,
        )
        await _audit_mobile_auth(
            session,
            request,
            agency_id=identity.agency_id,
            action="mobile.passenger_otp_verified",
            entity_id=identity.id,
        )
        return MobileOTPVerifyResponse(status="authenticated", tokens=tokens)

    # Multiple/shared records are deliberately not enumerated before a safe
    # secondary factor succeeds.
    return MobileOTPVerifyResponse(
        status="secondary_verification_required",
        claims=[],
    )


@router.post("/claim/verify", response_model=MobileOTPVerifyResponse)
async def verify_passenger_claim(
    body: MobileClaimVerifyRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> MobileOTPVerifyResponse:
    _require_mobile_enabled()
    challenge = await _locked_challenge(session, body.challenge_id)
    now = datetime.now(tz=UTC)
    if (
        challenge.status != "verified"
        or challenge.verified_at is None
        or challenge.expires_at <= now
        or challenge.consumed_at is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired verification challenge",
        )
    eligible = await _eligible_passenger_identities(
        session, challenge.phone_lookup_hash
    )
    matches = _matching_passenger_claims(
        eligible,
        claim_id=body.claim_id,
        verification_value=body.verification_value,
    )

    if len(matches) > 1 and body.claim_id is None:
        # Secondary proof succeeded. It is now safe to show only the matching
        # trip claims; selecting one repeats the same proof with claim_id.
        return MobileOTPVerifyResponse(
            status="claim_selection_required",
            claims=[_claim_summary(identity, group) for identity, _access, group in matches],
        )
    if len(matches) != 1:
        challenge.attempt_count = min(
            challenge.max_attempts, challenge.attempt_count + 1
        )
        if challenge.attempt_count >= challenge.max_attempts:
            challenge.status = "locked"
            challenge.verified_at = None
        challenge.updated_at = now
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Passenger verification could not be completed",
        )

    identity, access, _group = matches[0]
    challenge.status = "consumed"
    challenge.consumed_at = now
    challenge.passenger_identity_id = identity.id
    challenge.updated_at = now
    tokens = await _issue_passenger_session(
        session,
        identity=identity,
        access=access,
        device=body.device,
        request=request,
    )
    await _audit_mobile_auth(
        session,
        request,
        agency_id=identity.agency_id,
        action="mobile.passenger_claim_verified",
        entity_id=identity.id,
    )
    return MobileOTPVerifyResponse(status="authenticated", tokens=tokens)


@router.post("/login", response_model=MobileTokenResponse)
async def mobile_credential_login(
    body: MobileCredentialLoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> MobileTokenResponse:
    _require_mobile_enabled()
    limiter = LoginAttemptLimiter()
    email = str(body.email).lower().strip()
    client_ip = _client_ip(request)
    await limiter.check_allowed(email=email, ip_address=client_ip)
    user = (
        await session.execute(
            select(UserModel).where(
                UserModel.email == email,
                UserModel.role.in_(
                    (UserRole.CLIENT_MANAGER.value, UserRole.AGENCY_COORDINATOR.value)
                ),
                UserModel.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if (
        user is None
        or not user.is_active
        or user.agency_id is None
        or not verify_password(body.password, user.hashed_password)
    ):
        await limiter.record_failure(email=email, ip_address=client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    password_change_required = False
    principal_type = "coordinator"
    if user.role == UserRole.CLIENT_MANAGER.value:
        profile = (
            await session.execute(
                select(ClientManagerProfileModel).where(
                    ClientManagerProfileModel.user_id == user.id,
                    ClientManagerProfileModel.agency_id == user.agency_id,
                    ClientManagerProfileModel.status.in_(("invited", "active")),
                    ClientManagerProfileModel.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if profile is None:
            await limiter.record_failure(email=email, ip_address=client_ip)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )
        password_change_required = profile.force_password_change
        principal_type = "client_manager"

    await limiter.record_success(email=email, ip_address=client_ip)
    now = datetime.now(tz=UTC)
    user.last_login_at = now
    user.updated_at = now
    tokens = await _issue_user_session(
        session,
        user=user,
        principal_type=principal_type,
        device=body.device,
        request=request,
        password_change_required=password_change_required,
    )
    await _audit_mobile_auth(
        session,
        request,
        agency_id=user.agency_id,
        action="mobile.credential_login",
        entity_id=user.id,
        user_id=user.id,
    )
    return tokens


@router.post("/activate", response_model=MobileTokenResponse)
async def activate_client_manager(
    body: MobileActivationRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> MobileTokenResponse:
    """Redeem one invitation exactly once and issue an unrestricted session."""

    _require_mobile_enabled()
    token_hash = hash_mobile_lookup(
        body.activation_token, purpose="manager-invitation"
    )
    limiter_key = f"activation:{token_hash}"
    limiter = LoginAttemptLimiter()
    client_ip = _client_ip(request)
    await limiter.check_allowed(email=limiter_key, ip_address=client_ip)
    try:
        new_password_hash = hash_password(body.new_password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    now = datetime.now(tz=UTC)
    row = (
        await session.execute(
            select(ClientManagerProfileModel, UserModel)
            .join(UserModel, UserModel.id == ClientManagerProfileModel.user_id)
            .where(
                ClientManagerProfileModel.invitation_token_hash == token_hash,
                ClientManagerProfileModel.invitation_expires_at > now,
                ClientManagerProfileModel.status == "invited",
                ClientManagerProfileModel.deleted_at.is_(None),
                UserModel.role == UserRole.CLIENT_MANAGER.value,
                UserModel.is_active.is_(True),
                UserModel.deleted_at.is_(None),
            )
            .with_for_update(of=(ClientManagerProfileModel, UserModel))
        )
    ).first()
    if row is None:
        await limiter.record_failure(email=limiter_key, ip_address=client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Activation link is invalid or expired",
        )

    profile, user = row
    if user.agency_id is None or user.agency_id != profile.agency_id:
        await limiter.record_failure(email=limiter_key, ip_address=client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Activation link is invalid or expired",
        )
    sessions = list(
        (
            await session.execute(
                select(MobileDeviceSessionModel)
                .where(
                    MobileDeviceSessionModel.agency_id == profile.agency_id,
                    MobileDeviceSessionModel.user_id == user.id,
                    MobileDeviceSessionModel.status == "active",
                )
                .with_for_update()
            )
        ).scalars()
    )
    for device_session in sessions:
        await _revoke_session_family(
            session,
            device_session,
            reason="account_activated",
            now=now,
        )
    user.hashed_password = new_password_hash
    user.updated_at = now
    profile.status = "active"
    profile.force_password_change = False
    profile.invitation_token_hash = None
    profile.invitation_expires_at = None
    profile.activated_at = now
    profile.suspended_at = None
    profile.access_generation += 1
    profile.revision += 1
    profile.updated_at = now
    await session.flush()
    tokens = await _issue_user_session(
        session,
        user=user,
        principal_type="client_manager",
        device=body.device,
        request=request,
        password_change_required=False,
    )
    await limiter.record_success(email=limiter_key, ip_address=client_ip)
    await _audit_mobile_auth(
        session,
        request,
        agency_id=profile.agency_id,
        action="mobile.client_manager_activated",
        entity_id=profile.id,
        user_id=user.id,
    )
    return tokens


@router.post("/refresh", response_model=MobileTokenResponse)
async def refresh_mobile_session(
    body: MobileRefreshRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> MobileTokenResponse:
    _require_mobile_enabled()
    now = datetime.now(tz=UTC)
    token_hash = hash_mobile_refresh_token(body.refresh_token)
    row = (
        await session.execute(
            select(MobileRefreshTokenModel, MobileDeviceSessionModel)
            .join(
                MobileDeviceSessionModel,
                MobileDeviceSessionModel.id == MobileRefreshTokenModel.session_id,
            )
            .where(MobileRefreshTokenModel.token_hash == token_hash)
            .with_for_update(of=(MobileRefreshTokenModel, MobileDeviceSessionModel))
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    stored, device_session = row
    if stored.consumed_at is not None:
        stored.reuse_detected_at = now
        await _revoke_session_family(
            session, device_session, reason="refresh_token_reuse", now=now
        )
        await session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    if (
        stored.revoked_at is not None
        or stored.expires_at <= now
        or device_session.status != "active"
        or device_session.revoked_at is not None
        or device_session.expires_at <= now
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    principal, display_name, password_change_required = await _refresh_principal(
        session, device_session
    )
    stored.consumed_at = now
    raw_refresh, refresh_expires = create_mobile_refresh_token()
    replacement = MobileRefreshTokenModel(
        id=uuid.uuid4(),
        agency_id=device_session.agency_id,
        session_id=device_session.id,
        family_id=device_session.refresh_family_id,
        parent_token_id=stored.id,
        token_hash=hash_mobile_refresh_token(raw_refresh),
        token_generation=stored.token_generation + 1,
        issued_at=now,
        expires_at=refresh_expires,
    )
    session.add(replacement)
    device_session.last_refresh_at = now
    device_session.last_seen_at = now
    device_session.last_ip_hash = _request_digest(request, "ip")
    device_session.expires_at = refresh_expires
    device_session.updated_at = now
    access_token, access_expires = create_mobile_access_token(
        principal_id=principal.id,
        principal_type=device_session.subject_role,
        agency_id=device_session.agency_id,
        session_id=device_session.id,
        session_generation=device_session.session_generation,
        password_change_required=password_change_required,
    )
    return MobileTokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        access_token_expires_at=access_expires,
        refresh_token_expires_at=refresh_expires,
        session_id=device_session.id,
        principal=MobilePrincipalResponse(
            id=principal.id,
            principal_type=device_session.subject_role,
            agency_id=device_session.agency_id,
            display_name=display_name,
            force_password_change=password_change_required,
        ),
    )


@router.get("/me", response_model=MobilePrincipalResponse)
async def mobile_me(
    claims: MobileAccessClaims = Depends(get_current_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobilePrincipalResponse:
    display_name = await _principal_display_name(session, claims)
    return MobilePrincipalResponse(
        id=claims.principal_id,
        principal_type=claims.principal_type,
        agency_id=claims.agency_id,
        display_name=display_name,
        force_password_change=claims.password_change_required,
    )


@router.post("/password/change", response_model=MobileTokenResponse)
async def change_mobile_password(
    body: MobilePasswordChangeRequest,
    request: Request,
    claims: MobileAccessClaims = Depends(get_current_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileTokenResponse:
    if claims.principal_type not in {"client_manager", "coordinator"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Password login is not used by passengers")
    row = (
        await session.execute(
            select(UserModel, MobileDeviceSessionModel)
            .join(MobileDeviceSessionModel, MobileDeviceSessionModel.user_id == UserModel.id)
            .where(
                UserModel.id == claims.principal_id,
                UserModel.agency_id == claims.agency_id,
                MobileDeviceSessionModel.id == claims.session_id,
            )
            .with_for_update(of=(UserModel, MobileDeviceSessionModel))
        )
    ).first()
    if row is None or not verify_password(body.current_password, row[0].hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")
    user, old_session = row
    try:
        user.hashed_password = hash_password(body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    now = datetime.now(tz=UTC)
    if claims.principal_type == "client_manager":
        profile = (
            await session.execute(
                select(ClientManagerProfileModel)
                .where(
                    ClientManagerProfileModel.user_id == user.id,
                    ClientManagerProfileModel.agency_id == claims.agency_id,
                    ClientManagerProfileModel.deleted_at.is_(None),
                )
                .with_for_update()
            )
        ).scalar_one()
        profile.force_password_change = False
        profile.status = "active"
        profile.activated_at = profile.activated_at or now
        profile.suspended_at = None
        profile.invitation_token_hash = None
        profile.invitation_expires_at = None
        profile.access_generation += 1
        profile.revision += 1
        profile.updated_at = now
    user.updated_at = now
    await _revoke_session_family(session, old_session, reason="password_changed", now=now)
    await session.flush()
    tokens = await _issue_user_session(
        session,
        user=user,
        principal_type=claims.principal_type,
        device=body.device,
        request=request,
        password_change_required=False,
    )
    await _audit_mobile_auth(
        session,
        request,
        agency_id=claims.agency_id,
        action="mobile.password_changed",
        entity_id=user.id,
        user_id=user.id,
    )
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def logout_mobile_session(
    request: Request,
    body: MobileLogoutRequest | None = None,
    claims: MobileAccessClaims = Depends(get_current_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    del body
    device_session = (
        await session.execute(
            select(MobileDeviceSessionModel)
            .where(
                MobileDeviceSessionModel.id == claims.session_id,
                MobileDeviceSessionModel.agency_id == claims.agency_id,
            )
            .with_for_update()
        )
    ).scalar_one()
    await _revoke_session_family(
        session,
        device_session,
        reason="logout",
        now=datetime.now(tz=UTC),
    )
    await _audit_mobile_auth(
        session,
        request,
        agency_id=claims.agency_id,
        action="mobile.logout",
        entity_id=claims.session_id,
        user_id=(claims.principal_id if claims.principal_type != "passenger" else None),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def logout_all_mobile_sessions(
    request: Request,
    claims: MobileAccessClaims = Depends(get_current_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    now = datetime.now(tz=UTC)
    if claims.principal_type == "passenger":
        predicate = MobileDeviceSessionModel.passenger_identity_id == claims.principal_id
    else:
        predicate = MobileDeviceSessionModel.user_id == claims.principal_id
    sessions = list(
        (
            await session.execute(
                select(MobileDeviceSessionModel)
                .where(
                    MobileDeviceSessionModel.agency_id == claims.agency_id,
                    predicate,
                    MobileDeviceSessionModel.status == "active",
                )
                .with_for_update()
            )
        ).scalars()
    )
    for item in sessions:
        await _revoke_session_family(session, item, reason="logout_all", now=now)
    await _audit_mobile_auth(
        session,
        request,
        agency_id=claims.agency_id,
        action="mobile.logout_all",
        entity_id=claims.principal_id,
        user_id=(claims.principal_id if claims.principal_type != "passenger" else None),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _eligible_passenger_identities(
    session: AsyncSession,
    phone_lookup_hash: str,
) -> list[tuple[MobilePassengerIdentityModel, GCGroupAccessModel, ClientGroupModel]]:
    now = datetime.now(tz=UTC)
    rows = (
        await session.execute(
            select(MobilePassengerIdentityModel, GCGroupAccessModel, ClientGroupModel)
            .join(
                GCGroupAccessModel,
                GCGroupAccessModel.id == MobilePassengerIdentityModel.gc_group_access_id,
            )
            .join(ClientGroupModel, ClientGroupModel.id == MobilePassengerIdentityModel.group_id)
            .where(
                MobilePassengerIdentityModel.phone_lookup_hash == phone_lookup_hash,
                MobilePassengerIdentityModel.status.in_(("eligible", "claimed")),
                MobilePassengerIdentityModel.revoked_at.is_(None),
                GCGroupAccessModel.is_enabled.is_(True),
                GCGroupAccessModel.passenger_access_enabled.is_(True),
                GCGroupAccessModel.revoked_at.is_(None),
                ClientGroupModel.status.in_((GroupStatus.ACTIVE.value, GroupStatus.CLOSED.value)),
                (GCGroupAccessModel.access_starts_at.is_(None) | (GCGroupAccessModel.access_starts_at <= now)),
                (GCGroupAccessModel.access_expires_at.is_(None) | (GCGroupAccessModel.access_expires_at > now)),
                MobilePassengerIdentityModel.agency_id == GCGroupAccessModel.agency_id,
                MobilePassengerIdentityModel.group_id == GCGroupAccessModel.group_id,
                ClientGroupModel.agency_id == GCGroupAccessModel.agency_id,
            )
            .order_by(ClientGroupModel.travel_date.asc(), ClientGroupModel.id.asc())
            .limit(50)
        )
    ).all()
    return list(rows)


def _matching_passenger_claims(
    eligible: list[
        tuple[MobilePassengerIdentityModel, GCGroupAccessModel, ClientGroupModel]
    ],
    *,
    claim_id: uuid.UUID | None,
    verification_value: str | None,
) -> list[
    tuple[MobilePassengerIdentityModel, GCGroupAccessModel, ClientGroupModel]
]:
    """Resolve OTP claims without revealing cross-group shared phone records.

    Reconciliation can prove uniqueness only inside one group, while OTP lookup
    spans all eligible groups.  Therefore any multi-row phone lookup requires a
    retained secondary factor, even when each individual row was unambiguous in
    its own group.  A row without such a factor is deliberately unreachable in
    that multi-match state.
    """

    multiple_phone_matches = len(eligible) > 1
    candidates = (
        [row for row in eligible if row[0].id == claim_id]
        if claim_id is not None
        else eligible
    )
    matches: list[
        tuple[MobilePassengerIdentityModel, GCGroupAccessModel, ClientGroupModel]
    ] = []
    for row in candidates:
        identity = row[0]
        if not multiple_phone_matches and not identity.requires_secondary_verification:
            matches.append(row)
            continue
        if verification_value is None or identity.secondary_factor_hash is None:
            continue
        candidate = hash_mobile_secondary_factor(identity.id, verification_value)
        if hmac.compare_digest(candidate, identity.secondary_factor_hash):
            matches.append(row)
    return matches


async def _locked_challenge(
    session: AsyncSession, challenge_id: uuid.UUID
) -> MobileOTPChallengeModel:
    challenge = (
        await session.execute(
            select(MobileOTPChallengeModel)
            .where(MobileOTPChallengeModel.id == challenge_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if challenge is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired verification challenge",
        )
    return challenge


async def _verify_challenge_code(
    session: AsyncSession,
    challenge: MobileOTPChallengeModel,
    code: str,
) -> None:
    now = datetime.now(tz=UTC)
    if challenge.status != "pending" or challenge.expires_at <= now:
        if challenge.status == "pending" and challenge.expires_at <= now:
            challenge.status = "expired"
            challenge.updated_at = now
            await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired verification code",
        )
    expected = hash_mobile_otp_code(challenge.id, code)
    if not hmac.compare_digest(expected, challenge.code_hash):
        challenge.attempt_count = min(
            challenge.max_attempts, challenge.attempt_count + 1
        )
        if challenge.attempt_count >= challenge.max_attempts:
            challenge.status = "locked"
        challenge.updated_at = now
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired verification code",
        )


async def _issue_passenger_session(
    session: AsyncSession,
    *,
    identity: MobilePassengerIdentityModel,
    access: GCGroupAccessModel,
    device: MobileDeviceInput,
    request: Request,
) -> MobileTokenResponse:
    passenger_name = (
        await session.execute(
            select(PassportSubmissionModel.client_name).where(
                PassportSubmissionModel.id == identity.passenger_submission_id,
                PassportSubmissionModel.agency_id == identity.agency_id,
                PassportSubmissionModel.group_id == identity.group_id,
            )
        )
    ).scalar_one()
    identity.status = "claimed"
    identity.claimed_at = identity.claimed_at or datetime.now(tz=UTC)
    identity.last_verified_at = datetime.now(tz=UTC)
    return await _issue_session(
        session,
        principal_id=identity.id,
        principal_type="passenger",
        agency_id=identity.agency_id,
        display_name=passenger_name,
        device=device,
        request=request,
        passenger_identity=identity,
        access=access,
        password_change_required=False,
    )


async def _issue_user_session(
    session: AsyncSession,
    *,
    user: UserModel,
    principal_type: str,
    device: MobileDeviceInput,
    request: Request,
    password_change_required: bool,
) -> MobileTokenResponse:
    if user.agency_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Mobile account has no agency")
    return await _issue_session(
        session,
        principal_id=user.id,
        principal_type=principal_type,
        agency_id=user.agency_id,
        display_name=user.full_name,
        device=device,
        request=request,
        user=user,
        password_change_required=password_change_required,
    )


async def _issue_session(
    session: AsyncSession,
    *,
    principal_id: uuid.UUID,
    principal_type: str,
    agency_id: uuid.UUID,
    display_name: str,
    device: MobileDeviceInput,
    request: Request,
    password_change_required: bool,
    user: UserModel | None = None,
    passenger_identity: MobilePassengerIdentityModel | None = None,
    access: GCGroupAccessModel | None = None,
) -> MobileTokenResponse:
    now = datetime.now(tz=UTC)
    device_hash = hash_mobile_lookup(device.installation_id, purpose="device-installation")
    await _revoke_same_device_session(
        session,
        agency_id=agency_id,
        user_id=user.id if user else None,
        passenger_identity_id=passenger_identity.id if passenger_identity else None,
        device_hash=device_hash,
        now=now,
    )
    raw_refresh, refresh_expires = create_mobile_refresh_token()
    family_id = uuid.uuid4()
    device_session = MobileDeviceSessionModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        subject_role=principal_type,
        user_id=user.id if user else None,
        passenger_identity_id=passenger_identity.id if passenger_identity else None,
        passenger_subject_hash=(
            hash_mobile_lookup(str(passenger_identity.id), purpose="passenger-subject")
            if passenger_identity
            else None
        ),
        selected_gc_group_access_id=access.id if access else None,
        selected_group_id=access.group_id if access else None,
        device_identifier_hash=device_hash,
        platform=device.platform,
        app_version=device.app_version,
        device_label=device.device_name,
        status="active",
        session_generation=1,
        refresh_family_id=family_id,
        created_ip_hash=_request_digest(request, "ip"),
        last_ip_hash=_request_digest(request, "ip"),
        last_seen_at=now,
        expires_at=refresh_expires,
        created_at=now,
        updated_at=now,
    )
    refresh_model = MobileRefreshTokenModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        session_id=device_session.id,
        family_id=family_id,
        token_hash=hash_mobile_refresh_token(raw_refresh),
        token_generation=1,
        issued_at=now,
        expires_at=refresh_expires,
    )
    session.add_all([device_session, refresh_model])
    await session.flush()
    access_token, access_expires = create_mobile_access_token(
        principal_id=principal_id,
        principal_type=principal_type,
        agency_id=agency_id,
        session_id=device_session.id,
        session_generation=device_session.session_generation,
        password_change_required=password_change_required,
    )
    return MobileTokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        access_token_expires_at=access_expires,
        refresh_token_expires_at=refresh_expires,
        session_id=device_session.id,
        principal=MobilePrincipalResponse(
            id=principal_id,
            principal_type=principal_type,
            agency_id=agency_id,
            display_name=display_name,
            force_password_change=password_change_required,
        ),
    )


async def _revoke_same_device_session(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    user_id: uuid.UUID | None,
    passenger_identity_id: uuid.UUID | None,
    device_hash: str,
    now: datetime,
) -> None:
    predicate = (
        MobileDeviceSessionModel.user_id == user_id
        if user_id is not None
        else MobileDeviceSessionModel.passenger_identity_id == passenger_identity_id
    )
    existing = list(
        (
            await session.execute(
                select(MobileDeviceSessionModel)
                .where(
                    MobileDeviceSessionModel.agency_id == agency_id,
                    predicate,
                    MobileDeviceSessionModel.device_identifier_hash == device_hash,
                    MobileDeviceSessionModel.status == "active",
                )
                .with_for_update()
            )
        ).scalars()
    )
    for item in existing:
        await _revoke_session_family(session, item, reason="session_replaced", now=now)


async def _revoke_session_family(
    session: AsyncSession,
    device_session: MobileDeviceSessionModel,
    *,
    reason: str,
    now: datetime,
) -> None:
    device_session.status = "revoked"
    device_session.session_generation += 1
    device_session.revoked_at = now
    device_session.revoke_reason = reason
    device_session.updated_at = now
    await session.execute(
        update(MobileRefreshTokenModel)
        .where(
            MobileRefreshTokenModel.session_id == device_session.id,
            MobileRefreshTokenModel.family_id == device_session.refresh_family_id,
            MobileRefreshTokenModel.revoked_at.is_(None),
        )
        .values(revoked_at=now, revoke_reason=reason)
    )


async def _refresh_principal(
    session: AsyncSession,
    device_session: MobileDeviceSessionModel,
) -> tuple[UserModel | MobilePassengerIdentityModel, str, bool]:
    if device_session.subject_role == "passenger":
        identity = (
            await session.execute(
                select(MobilePassengerIdentityModel).where(
                    MobilePassengerIdentityModel.id == device_session.passenger_identity_id,
                    MobilePassengerIdentityModel.agency_id == device_session.agency_id,
                    MobilePassengerIdentityModel.status == "claimed",
                    MobilePassengerIdentityModel.revoked_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if identity is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Mobile identity is inactive")
        name = (
            await session.execute(
                select(PassportSubmissionModel.client_name).where(
                    PassportSubmissionModel.id == identity.passenger_submission_id,
                    PassportSubmissionModel.agency_id == identity.agency_id,
                )
            )
        ).scalar_one()
        return identity, name, False

    expected_role = (
        UserRole.CLIENT_MANAGER.value
        if device_session.subject_role == "client_manager"
        else UserRole.AGENCY_COORDINATOR.value
    )
    user = (
        await session.execute(
            select(UserModel).where(
                UserModel.id == device_session.user_id,
                UserModel.agency_id == device_session.agency_id,
                UserModel.role == expected_role,
                UserModel.is_active.is_(True),
                UserModel.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Mobile account is inactive")
    force_change = False
    if device_session.subject_role == "client_manager":
        profile = (
            await session.execute(
                select(ClientManagerProfileModel).where(
                    ClientManagerProfileModel.user_id == user.id,
                    ClientManagerProfileModel.agency_id == user.agency_id,
                    ClientManagerProfileModel.status.in_(("invited", "active")),
                    ClientManagerProfileModel.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if profile is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Mobile account is inactive")
        force_change = profile.force_password_change
    return user, user.full_name, force_change


async def _principal_display_name(
    session: AsyncSession, claims: MobileAccessClaims
) -> str:
    if claims.principal_type == "passenger":
        name = (
            await session.execute(
                select(PassportSubmissionModel.client_name)
                .join(
                    MobilePassengerIdentityModel,
                    MobilePassengerIdentityModel.passenger_submission_id
                    == PassportSubmissionModel.id,
                )
                .where(
                    MobilePassengerIdentityModel.id == claims.principal_id,
                    MobilePassengerIdentityModel.agency_id == claims.agency_id,
                )
            )
        ).scalar_one_or_none()
    else:
        name = (
            await session.execute(
                select(UserModel.full_name).where(
                    UserModel.id == claims.principal_id,
                    UserModel.agency_id == claims.agency_id,
                )
            )
        ).scalar_one_or_none()
    if not name:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Mobile principal is inactive")
    return str(name)


def _claim_summary(
    identity: MobilePassengerIdentityModel,
    group: ClientGroupModel,
) -> MobileTripClaimSummary:
    return MobileTripClaimSummary(
        claim_id=identity.id,
        group_id=group.id,
        group_name=group.name,
        destination=group.destination,
        travel_date=group.travel_date,
        return_date=group.return_date,
        requires_secondary_verification=identity.requires_secondary_verification,
    )


def _require_mobile_enabled() -> None:
    if not get_settings().mobile.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The mobile API is not enabled",
        )


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _request_digest(request: Request, field: str) -> str | None:
    if field == "ip":
        value = _client_ip(request)
    else:
        value = request.headers.get(field)
    return hash_mobile_lookup(value, purpose=f"request-{field}") if value else None


async def _audit_mobile_auth(
    session: AsyncSession,
    request: Request,
    *,
    agency_id: uuid.UUID,
    action: str,
    entity_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> None:
    await AuditLogRepository(session).record(
        action=action,
        entity_type="mobile_auth",
        agency_id=agency_id,
        user_id=user_id,
        entity_id=str(entity_id),
        ip_address=_client_ip(request),
        metadata={},
    )
