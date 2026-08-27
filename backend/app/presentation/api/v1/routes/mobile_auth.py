"""Bearer-only authentication for passenger, Client Manager, and coordinator apps."""

from __future__ import annotations

import asyncio
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.otp_provider import OTPDeliveryError
from app.application.use_cases.whatsapp.contact_normalization import normalize_whatsapp_phone
from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.core.security.mobile_jwt import (
    MobileAccessClaims,
    MobilePrincipalType,
    create_mobile_access_token,
    create_mobile_refresh_token,
    hash_mobile_lookup,
    hash_mobile_otp_code,
    hash_mobile_refresh_token,
)
from app.core.security.mobile_offline_lease import (
    create_mobile_offline_authorization_lease,
)
from app.core.security.password import hash_password, verify_password
from app.domain.entities.entities import GroupStatus, UserRole
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerProfileModel,
    GCGroupAccessModel,
    MobileDeviceSessionModel,
    MobileOTPChallengeModel,
    MobilePassengerIdentityModel,
    MobilePassengerSessionIdentityModel,
    MobileRefreshTokenModel,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.security.login_attempt_limiter import LoginAttemptLimiter
from app.infrastructure.security.mobile_otp_rate_limiter import (
    MobileOTPRateLimiter,
    OTPRateLimitExceeded,
    OTPRateLimitUnavailable,
)
from app.infrastructure.whatsapp.otp_provider import get_otp_provider
from app.presentation.api.v1.routes.mobile_auth_otp_support import (
    _claim_summary,
    _direct_passenger_otp_rows,
    _eligible_passenger_identities,
    _locked_challenge,
    _matching_passenger_claims,
    _reconcile_phone_candidate_groups,
    _validate_passenger_session_identities,
    _verify_challenge_code,
)
from app.presentation.api.v1.routes.mobile_auth_session_support import (
    MobileSessionIssueDependencies,
    _normalize_direct_password_client_manager,
    _principal_profile,
    _refresh_principal,
    _revoke_session_family,
    issue_mobile_session,
    mobile_offline_lease_generations,
)
from app.presentation.api.v1.routes.mobile_auth_session_support import (
    _principal_display_name as _principal_display_name,
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
    MobilePassengerTripSwitchRequest,
    MobilePasswordChangeRequest,
    MobilePrincipalResponse,
    MobileRefreshRequest,
    MobileTokenResponse,
)
from app.presentation.dependencies.mobile_auth import (
    client_manager_profile_allows_password_session,
    get_current_mobile_claims,
)
from app.presentation.security.client_ip import trusted_client_ip


def _set_mobile_auth_no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"


router = APIRouter(dependencies=[Depends(_set_mobile_auth_no_store)])
logger = get_logger(__name__)
_OTP_NEUTRAL_RESPONSE_MIN_SECONDS = 0.65
_OTP_NEUTRAL_RESPONSE_JITTER_MS = 150


async def _complete_neutral_otp_timing(
    started_at: float,
    *,
    jitter_ms: int,
) -> None:
    """Apply the same bounded response floor to eligible and neutral requests."""

    target_seconds = _OTP_NEUTRAL_RESPONSE_MIN_SECONDS + (jitter_ms / 1000)
    remaining = target_seconds - (time.monotonic() - started_at)
    if remaining > 0:
        await asyncio.sleep(remaining)


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
    started_at = time.monotonic()
    timing_jitter_ms = secrets.randbelow(_OTP_NEUTRAL_RESPONSE_JITTER_MS + 1)
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
            )
            .order_by(MobileOTPChallengeModel.created_at.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing is not None and existing.expires_at > now and existing.resend_available_at > now:
        await session.commit()
        await _complete_neutral_otp_timing(
            started_at,
            jitter_ms=timing_jitter_ms,
        )
        return MobileOTPRequestResponse(
            challenge_id=existing.id,
            expires_in_seconds=max(1, int((existing.expires_at - now).total_seconds())),
            resend_after_seconds=max(1, int((existing.resend_available_at - now).total_seconds())),
        )
    if existing is not None:
        existing.status = "expired" if existing.expires_at <= now else "cancelled"
        existing.updated_at = now

    challenge_id = uuid.uuid4()
    configured_code = settings.otp_development_code
    code = (
        configured_code.get_secret_value()
        if configured_code is not None and settings.otp_provider == "development"
        else f"{secrets.randbelow(1_000_000):06d}"
    )
    if normalized_phone is not None:
        await _reconcile_phone_candidate_groups(
            session,
            normalized_phone=normalized_phone,
            phone_lookup_hash=phone_lookup_hash,
        )
        eligible = await _eligible_passenger_identities(session, phone_lookup_hash)
    else:
        eligible = []
    agencies = {identity.agency_id for identity, _access, _group in eligible}
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
        provider_reference=None,
        status="pending",
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
    try:
        await session.flush()
        # The challenge and any just-in-time identity reconciliation are
        # durable before an external provider can observe the send request.
        await session.commit()
    except IntegrityError:
        # The partial unique index serializes concurrent requests even when
        # both transactions initially observed no pending row.
        await session.rollback()
        winner = (
            await session.execute(
                select(MobileOTPChallengeModel)
                .where(
                    MobileOTPChallengeModel.phone_lookup_hash == phone_lookup_hash,
                )
                .order_by(MobileOTPChallengeModel.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if winner is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OTP verification is temporarily unavailable",
            )
        await session.commit()
        await _complete_neutral_otp_timing(
            started_at,
            jitter_ms=timing_jitter_ms,
        )
        return MobileOTPRequestResponse(
            challenge_id=winner.id,
            expires_in_seconds=max(
                1, int((winner.expires_at - datetime.now(tz=UTC)).total_seconds())
            ),
            resend_after_seconds=max(
                1,
                int((winner.resend_available_at - datetime.now(tz=UTC)).total_seconds()),
            ),
        )

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
            delivery_status = "unknown" if exc.delivery_unknown else "failed"
            provider_error_code = exc.code
            logger.warning(
                "mobile_otp_delivery_failed",
                provider=settings.otp_provider,
                error_code=provider_error_code,
                delivery_unknown=exc.delivery_unknown,
            )
        except Exception as exc:
            delivery_status = "unknown"
            provider_error_code = "OTP_PROVIDER_UNEXPECTED"
            logger.error(
                "mobile_otp_delivery_failed",
                provider=settings.otp_provider,
                error_code=provider_error_code,
                delivery_unknown=True,
                error_type=type(exc).__name__,
            )

    challenge.provider_reference = provider_reference
    if delivery_status == "failed":
        challenge.status = "cancelled"
    elif delivery_status == "unknown":
        # An uncertain provider result may still arrive. Suppress resends for
        # the full code lifetime so two usable codes are never in flight.
        challenge.resend_available_at = challenge.expires_at
    challenge.updated_at = datetime.now(tz=UTC)
    try:
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
        await session.commit()
    except Exception:
        # The committed challenge remains authoritative even if recording the
        # provider outcome fails. Never turn that persistence issue into an
        # account-enumeration signal or log phone/code material.
        await session.rollback()
        logger.error(
            "mobile_otp_delivery_state_persistence_failed",
            provider=settings.otp_provider,
            challenge_id=str(challenge.id),
        )

    await _complete_neutral_otp_timing(
        started_at,
        jitter_ms=timing_jitter_ms,
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
    eligible = await _eligible_passenger_identities(session, challenge.phone_lookup_hash)
    if not eligible:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired verification code",
        )
    directly_authorized = _direct_passenger_otp_rows(eligible)
    if directly_authorized:
        identity, access, _group = directly_authorized[0]
        challenge.status = "consumed"
        challenge.consumed_at = now
        challenge.passenger_identity_id = identity.id
        tokens = await _issue_passenger_session(
            session,
            identity=identity,
            access=access,
            authorized_identities=[row[0] for row in directly_authorized],
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
    eligible = await _eligible_passenger_identities(session, challenge.phone_lookup_hash)
    proven_matches = _matching_passenger_claims(
        eligible,
        claim_id=None,
        verification_value=body.verification_value,
    )

    if len(proven_matches) > 1 and body.claim_id is None:
        # Secondary proof succeeded. It is now safe to show only the matching
        # trip claims; selecting one repeats the same proof with claim_id.
        return MobileOTPVerifyResponse(
            status="claim_selection_required",
            claims=[_claim_summary(identity, group) for identity, _access, group in proven_matches],
        )
    selected_matches = (
        [row for row in proven_matches if row[0].id == body.claim_id]
        if body.claim_id is not None
        else proven_matches
    )
    if len(selected_matches) != 1:
        challenge.attempt_count = min(challenge.max_attempts, challenge.attempt_count + 1)
        if challenge.attempt_count >= challenge.max_attempts:
            challenge.status = "locked"
            challenge.verified_at = None
        challenge.updated_at = now
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Passenger verification could not be completed",
        )

    identity, access, _group = selected_matches[0]
    challenge.status = "consumed"
    challenge.consumed_at = now
    challenge.passenger_identity_id = identity.id
    challenge.updated_at = now
    tokens = await _issue_passenger_session(
        session,
        identity=identity,
        access=access,
        authorized_identities=[
            row[0] for row in proven_matches if row[0].agency_id == identity.agency_id
        ],
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

    now = datetime.now(tz=UTC)
    password_change_required = False
    principal_type: MobilePrincipalType = "coordinator"
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
        if profile is None or not client_manager_profile_allows_password_session(profile):
            await limiter.record_failure(email=email, ip_address=client_ip)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )
        _normalize_direct_password_client_manager(profile, now=now)
        principal_type = "client_manager"

    await limiter.record_success(email=email, ip_address=client_ip)
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
    token_hash = hash_mobile_lookup(body.activation_token, purpose="manager-invitation")
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
            # Lock both invitation/profile and account rows until the
            # one-time activation transition commits.
            .with_for_update()
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
    stored = (
        await session.execute(
            select(MobileRefreshTokenModel)
            .where(MobileRefreshTokenModel.token_hash == token_hash)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if stored is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )
    device_session = (
        await session.execute(
            select(MobileDeviceSessionModel)
            .where(
                MobileDeviceSessionModel.id == stored.session_id,
                MobileDeviceSessionModel.agency_id == stored.agency_id,
                MobileDeviceSessionModel.refresh_family_id == stored.family_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if device_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )
    presented_device_hash = hash_mobile_lookup(
        body.installation_id,
        purpose="device-installation",
    )
    if not secrets.compare_digest(
        device_session.device_identifier_hash,
        presented_device_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )
    if stored.consumed_at is not None:
        stored.reuse_detected_at = now
        await _revoke_session_family(session, device_session, reason="refresh_token_reuse", now=now)
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )
    if (
        stored.revoked_at is not None
        or stored.expires_at <= now
        or device_session.status != "active"
        or device_session.revoked_at is not None
        or device_session.expires_at <= now
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    principal, display_name, password_change_required, selected_access = await _refresh_principal(
        session, device_session
    )
    if device_session.subject_role not in {"passenger", "client_manager", "coordinator"}:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )
    principal_type = cast(MobilePrincipalType, device_session.subject_role)
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
        account_id=device_session.account_id,
        principal_type=principal_type,
        agency_id=device_session.agency_id,
        session_id=device_session.id,
        session_generation=device_session.session_generation,
        password_change_required=password_change_required,
    )
    principal_generation, access_generation = await mobile_offline_lease_generations(
        session,
        principal_type=principal_type,
        principal=principal,
        access=selected_access,
    )
    passenger_id = (
        principal.passenger_submission_id
        if principal_type == "passenger" and isinstance(principal, MobilePassengerIdentityModel)
        else None
    )
    offline_authorization_lease = create_mobile_offline_authorization_lease(
        principal_id=principal.id,
        account_id=device_session.account_id,
        principal_type=principal_type,
        agency_id=device_session.agency_id,
        passenger_id=passenger_id,
        session_id=device_session.id,
        session_generation=device_session.session_generation,
        installation_id=body.installation_id,
        principal_generation=principal_generation,
        access_generation=access_generation,
        now=now,
    )
    return MobileTokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        access_token_expires_at=access_expires,
        refresh_token_expires_at=refresh_expires,
        session_id=device_session.id,
        offline_authorization_lease=offline_authorization_lease,
        principal=MobilePrincipalResponse(
            id=principal.id,
            account_id=device_session.account_id,
            principal_type=principal_type,
            agency_id=device_session.agency_id,
            passenger_id=(passenger_id),
            display_name=display_name,
            force_password_change=password_change_required,
        ),
    )


@router.get("/me", response_model=MobilePrincipalResponse)
async def mobile_me(
    claims: MobileAccessClaims = Depends(get_current_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobilePrincipalResponse:
    display_name, email, phone_number, passenger_id = await _principal_profile(session, claims)
    return MobilePrincipalResponse(
        id=claims.principal_id,
        account_id=claims.account_id,
        principal_type=claims.principal_type,
        agency_id=claims.agency_id,
        passenger_id=passenger_id,
        display_name=display_name,
        email=email,
        phone_number=phone_number,
        force_password_change=False,
    )


@router.post("/passenger/trip/switch", response_model=MobileTokenResponse)
async def switch_passenger_trip(
    body: MobilePassengerTripSwitchRequest,
    request: Request,
    claims: MobileAccessClaims = Depends(get_current_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileTokenResponse:
    """Rotate the live session to one previously proven passenger identity.

    The caller supplies only a group identifier. The identity itself is
    resolved exclusively from the server-side authorization set established
    by OTP and any required secondary factor. Old access and refresh tokens
    are invalidated before the replacement pair is returned.
    """

    if claims.principal_type != "passenger":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Passenger trip switching is not available",
        )
    now = datetime.now(tz=UTC)
    # Refresh rotation locks the current refresh row before its device session.
    # Use the same order here so a simultaneous refresh/switch cannot deadlock.
    active_refresh_token_ids = (
        (
            await session.execute(
                select(MobileRefreshTokenModel.id)
                .where(
                    MobileRefreshTokenModel.session_id == claims.session_id,
                    MobileRefreshTokenModel.agency_id == claims.agency_id,
                    MobileRefreshTokenModel.consumed_at.is_(None),
                    MobileRefreshTokenModel.revoked_at.is_(None),
                    MobileRefreshTokenModel.expires_at > now,
                )
                .order_by(MobileRefreshTokenModel.token_generation)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    # A bearer token must never resurrect a session whose refresh family has
    # already been exhausted or explicitly revoked.
    if not active_refresh_token_ids:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Mobile session is no longer active",
        )
    device_session = (
        await session.execute(
            select(MobileDeviceSessionModel)
            .where(
                MobileDeviceSessionModel.id == claims.session_id,
                MobileDeviceSessionModel.agency_id == claims.agency_id,
                MobileDeviceSessionModel.subject_role == "passenger",
                MobileDeviceSessionModel.passenger_identity_id == claims.principal_id,
                MobileDeviceSessionModel.status == "active",
                MobileDeviceSessionModel.session_generation == claims.session_generation,
                MobileDeviceSessionModel.revoked_at.is_(None),
                MobileDeviceSessionModel.expires_at > now,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if device_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Mobile session is no longer active",
        )
    presented_device_hash = hash_mobile_lookup(
        body.installation_id,
        purpose="device-installation",
    )
    if not secrets.compare_digest(
        device_session.device_identifier_hash,
        presented_device_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Mobile session is no longer active",
        )

    target_rows = (
        await session.execute(
            select(
                MobilePassengerSessionIdentityModel,
                MobilePassengerIdentityModel,
                GCGroupAccessModel,
                ClientGroupModel,
            )
            .join(
                MobilePassengerIdentityModel,
                and_(
                    MobilePassengerIdentityModel.id
                    == MobilePassengerSessionIdentityModel.passenger_identity_id,
                    MobilePassengerIdentityModel.gc_group_access_id
                    == MobilePassengerSessionIdentityModel.gc_group_access_id,
                    MobilePassengerIdentityModel.agency_id
                    == MobilePassengerSessionIdentityModel.agency_id,
                    MobilePassengerIdentityModel.group_id
                    == MobilePassengerSessionIdentityModel.group_id,
                ),
            )
            .join(
                GCGroupAccessModel,
                and_(
                    GCGroupAccessModel.id == MobilePassengerSessionIdentityModel.gc_group_access_id,
                    GCGroupAccessModel.agency_id == MobilePassengerSessionIdentityModel.agency_id,
                    GCGroupAccessModel.group_id == MobilePassengerSessionIdentityModel.group_id,
                ),
            )
            .join(
                ClientGroupModel,
                and_(
                    ClientGroupModel.id == MobilePassengerSessionIdentityModel.group_id,
                    ClientGroupModel.agency_id == MobilePassengerSessionIdentityModel.agency_id,
                ),
            )
            .where(
                MobilePassengerSessionIdentityModel.session_id == claims.session_id,
                MobilePassengerSessionIdentityModel.agency_id == claims.agency_id,
                MobilePassengerSessionIdentityModel.group_id == body.group_id,
                MobilePassengerIdentityModel.claim_generation
                == MobilePassengerSessionIdentityModel.identity_claim_generation,
                MobilePassengerIdentityModel.status.in_(("eligible", "claimed")),
                MobilePassengerIdentityModel.revoked_at.is_(None),
                GCGroupAccessModel.is_enabled.is_(True),
                GCGroupAccessModel.passenger_access_enabled.is_(True),
                GCGroupAccessModel.revoked_at.is_(None),
                or_(
                    GCGroupAccessModel.access_starts_at.is_(None),
                    GCGroupAccessModel.access_starts_at <= now,
                ),
                or_(
                    GCGroupAccessModel.access_expires_at.is_(None),
                    GCGroupAccessModel.access_expires_at > now,
                ),
                ClientGroupModel.status.in_((GroupStatus.ACTIVE.value, GroupStatus.CLOSED.value)),
                ClientGroupModel.deleted_at.is_(None),
            )
            .limit(2)
            .with_for_update()
        )
    ).all()
    # Ambiguity is denied: a group identifier must resolve to exactly one
    # identity in this exact session-scoped proof set.
    if len(target_rows) != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Passenger trip is not authorized",
        )
    _authorization, identity, access, _group = target_rows[0]

    token_generation = (
        int(
            (
                await session.execute(
                    select(
                        func.coalesce(func.max(MobileRefreshTokenModel.token_generation), 0)
                    ).where(
                        MobileRefreshTokenModel.session_id == device_session.id,
                        MobileRefreshTokenModel.agency_id == device_session.agency_id,
                        MobileRefreshTokenModel.family_id == device_session.refresh_family_id,
                    )
                )
            ).scalar_one()
        )
        + 1
    )
    await session.execute(
        update(MobileRefreshTokenModel)
        .where(
            MobileRefreshTokenModel.session_id == device_session.id,
            MobileRefreshTokenModel.agency_id == device_session.agency_id,
            MobileRefreshTokenModel.family_id == device_session.refresh_family_id,
            MobileRefreshTokenModel.revoked_at.is_(None),
        )
        .values(revoked_at=now, revoke_reason="passenger_trip_switched")
    )

    raw_refresh, refresh_expires = create_mobile_refresh_token()
    session.add(
        MobileRefreshTokenModel(
            id=uuid.uuid4(),
            agency_id=device_session.agency_id,
            session_id=device_session.id,
            family_id=device_session.refresh_family_id,
            token_hash=hash_mobile_refresh_token(raw_refresh),
            token_generation=token_generation,
            issued_at=now,
            expires_at=refresh_expires,
        )
    )
    identity.status = "claimed"
    identity.claimed_at = identity.claimed_at or now
    identity.last_verified_at = now
    identity.updated_at = now
    device_session.passenger_identity_id = identity.id
    device_session.selected_gc_group_access_id = access.id
    device_session.selected_group_id = access.group_id
    # Acknowledgement belongs to the previously selected trip.  The new trip
    # is counted as synchronized only after its own complete manifest commit.
    device_session.last_sync_acknowledged_at = None
    device_session.session_generation += 1
    device_session.last_seen_at = now
    device_session.last_ip_hash = _request_digest(request, "ip")
    device_session.expires_at = refresh_expires
    device_session.updated_at = now
    await session.flush()

    display_name = (
        await session.execute(
            select(PassportSubmissionModel.client_name).where(
                PassportSubmissionModel.id == identity.passenger_submission_id,
                PassportSubmissionModel.agency_id == identity.agency_id,
                PassportSubmissionModel.group_id == identity.group_id,
            )
        )
    ).scalar_one()
    access_token, access_expires = create_mobile_access_token(
        principal_id=identity.id,
        account_id=device_session.account_id,
        principal_type="passenger",
        agency_id=identity.agency_id,
        session_id=device_session.id,
        session_generation=device_session.session_generation,
        password_change_required=False,
    )
    principal_generation, access_generation = await mobile_offline_lease_generations(
        session,
        principal_type="passenger",
        principal=identity,
        access=access,
    )
    offline_authorization_lease = create_mobile_offline_authorization_lease(
        principal_id=identity.id,
        account_id=device_session.account_id,
        principal_type="passenger",
        agency_id=identity.agency_id,
        passenger_id=identity.passenger_submission_id,
        session_id=device_session.id,
        session_generation=device_session.session_generation,
        installation_id=body.installation_id,
        principal_generation=principal_generation,
        access_generation=access_generation,
        now=now,
    )
    await _audit_mobile_auth(
        session,
        request,
        agency_id=identity.agency_id,
        action="mobile.passenger_trip_switched",
        entity_id=access.group_id,
    )
    return MobileTokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        access_token_expires_at=access_expires,
        refresh_token_expires_at=refresh_expires,
        session_id=device_session.id,
        offline_authorization_lease=offline_authorization_lease,
        principal=MobilePrincipalResponse(
            id=identity.id,
            account_id=device_session.account_id,
            principal_type="passenger",
            agency_id=identity.agency_id,
            passenger_id=identity.passenger_submission_id,
            display_name=display_name,
        ),
    )


@router.post("/password/change", response_model=MobileTokenResponse)
async def change_mobile_password(
    body: MobilePasswordChangeRequest,
    request: Request,
    claims: MobileAccessClaims = Depends(get_current_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileTokenResponse:
    if claims.principal_type not in {"client_manager", "coordinator"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Password login is not used by passengers"
        )
    row = (
        await session.execute(
            select(UserModel, MobileDeviceSessionModel)
            .join(MobileDeviceSessionModel, MobileDeviceSessionModel.user_id == UserModel.id)
            .where(
                UserModel.id == claims.principal_id,
                UserModel.agency_id == claims.agency_id,
                MobileDeviceSessionModel.id == claims.session_id,
            )
            # Lock both the account and its current device session so password
            # replacement and session-family revocation remain atomic.
            .with_for_update()
        )
    ).first()
    if row is None or not verify_password(body.current_password, row[0].hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect"
        )
    user, old_session = row
    try:
        user.hashed_password = hash_password(body.new_password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
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
        authorized_session_ids = select(MobilePassengerSessionIdentityModel.session_id).where(
            MobilePassengerSessionIdentityModel.agency_id == claims.agency_id,
            MobilePassengerSessionIdentityModel.passenger_identity_id == claims.principal_id,
        )
        predicate = or_(
            MobileDeviceSessionModel.passenger_identity_id == claims.principal_id,
            MobileDeviceSessionModel.id.in_(authorized_session_ids),
        )
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


async def _issue_passenger_session(
    session: AsyncSession,
    *,
    identity: MobilePassengerIdentityModel,
    access: GCGroupAccessModel,
    authorized_identities: list[MobilePassengerIdentityModel] | None = None,
    device: MobileDeviceInput,
    request: Request,
) -> MobileTokenResponse:
    if (
        identity.gc_group_access_id != access.id
        or identity.group_id != access.group_id
        or identity.agency_id != access.agency_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Passenger verification could not be completed",
        )
    passenger_name = (
        await session.execute(
            select(PassportSubmissionModel.client_name).where(
                PassportSubmissionModel.id == identity.passenger_submission_id,
                PassportSubmissionModel.agency_id == identity.agency_id,
                PassportSubmissionModel.group_id == identity.group_id,
            )
        )
    ).scalar_one()
    now = datetime.now(tz=UTC)
    proven_identities = authorized_identities or [identity]
    _validate_passenger_session_identities(
        selected_identity=identity,
        authorized_identities=proven_identities,
    )
    for proven_identity in proven_identities:
        proven_identity.status = "claimed"
        proven_identity.claimed_at = proven_identity.claimed_at or now
        proven_identity.last_verified_at = now
    return await _issue_session(
        session,
        principal_id=identity.id,
        principal_type="passenger",
        agency_id=identity.agency_id,
        display_name=passenger_name,
        device=device,
        request=request,
        passenger_identity=identity,
        passenger_authorized_identities=proven_identities,
        access=access,
        password_change_required=False,
    )


async def _issue_user_session(
    session: AsyncSession,
    *,
    user: UserModel,
    principal_type: MobilePrincipalType,
    device: MobileDeviceInput,
    request: Request,
    password_change_required: bool,
) -> MobileTokenResponse:
    if user.agency_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Mobile account has no agency"
        )
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
    principal_type: MobilePrincipalType,
    agency_id: uuid.UUID,
    display_name: str,
    device: MobileDeviceInput,
    request: Request,
    password_change_required: bool,
    user: UserModel | None = None,
    passenger_identity: MobilePassengerIdentityModel | None = None,
    passenger_authorized_identities: list[MobilePassengerIdentityModel] | None = None,
    access: GCGroupAccessModel | None = None,
) -> MobileTokenResponse:
    return await issue_mobile_session(
        session,
        principal_id=principal_id,
        principal_type=principal_type,
        agency_id=agency_id,
        display_name=display_name,
        device=device,
        request=request,
        password_change_required=password_change_required,
        user=user,
        passenger_identity=passenger_identity,
        passenger_authorized_identities=passenger_authorized_identities,
        access=access,
        dependencies=MobileSessionIssueDependencies(
            validate_passenger_session_identities=_validate_passenger_session_identities,
            revoke_same_device_session=_revoke_same_device_session,
            create_refresh_token=create_mobile_refresh_token,
            create_access_token=create_mobile_access_token,
            create_offline_authorization_lease=(create_mobile_offline_authorization_lease),
            hash_lookup=hash_mobile_lookup,
            hash_refresh_token=hash_mobile_refresh_token,
            request_digest=_request_digest,
        ),
    )


async def _revoke_same_device_session(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    user_id: uuid.UUID | None,
    passenger_identity_id: uuid.UUID | None,
    passenger_authorized_identity_ids: list[uuid.UUID] | None,
    device_hash: str,
    now: datetime,
) -> None:
    if user_id is not None:
        predicate = MobileDeviceSessionModel.user_id == user_id
    else:
        authorized_ids = list(dict.fromkeys(passenger_authorized_identity_ids or []))
        if passenger_identity_id is not None and passenger_identity_id not in authorized_ids:
            authorized_ids.append(passenger_identity_id)
        authorized_session_ids = select(MobilePassengerSessionIdentityModel.session_id).where(
            MobilePassengerSessionIdentityModel.agency_id == agency_id,
            MobilePassengerSessionIdentityModel.passenger_identity_id.in_(authorized_ids),
        )
        predicate = or_(
            MobileDeviceSessionModel.passenger_identity_id.in_(authorized_ids),
            MobileDeviceSessionModel.id.in_(authorized_session_ids),
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


def _require_mobile_enabled() -> None:
    if not get_settings().mobile.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The mobile API is not enabled",
        )


def _client_ip(request: Request) -> str | None:
    return trusted_client_ip(request)


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
