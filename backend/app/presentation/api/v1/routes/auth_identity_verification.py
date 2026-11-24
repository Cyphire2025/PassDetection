"""Cohesive verification operations behind the stable identity route facade."""

from __future__ import annotations

from datetime import UTC

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.identity_security import (
    generate_recovery_codes,
    reencrypt_mfa_secret_if_needed,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.identity_security_repository import (
    IdentitySecurityRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes.auth_identity_dependencies import (
    DateTimeClass,
    DenyVerification,
    FactorVerifier,
    RequestHash,
    SessionIssuer,
)
from app.presentation.api.v1.schemas.auth_schemas import (
    AuthResponse,
    MFAChallengeVerifyRequest,
    MFAEnrollmentResult,
)
from app.presentation.security.client_ip import trusted_client_ip


async def verify_dashboard_mfa(
    body: MFAChallengeVerifyRequest,
    request: Request,
    response: Response,
    session: AsyncSession,
    *,
    datetime: DateTimeClass,
    _request_hash: RequestHash,
    _validate_mfa_code: FactorVerifier,
    _issue_authenticated_session: SessionIssuer,
    _deny_mfa_verification: DenyVerification,
) -> MFAEnrollmentResult | AuthResponse:
    repository = IdentitySecurityRepository(session)
    challenge = await repository.get_pending_auth_challenge(
        raw_token=body.challenge_token,
    )
    now = datetime.now(tz=UTC)
    if challenge is None:
        await _deny_mfa_verification(session)
    if challenge.request_ip_hash != _request_hash(
        request, "ip"
    ) or challenge.user_agent_hash != _request_hash(request, "user-agent"):
        challenge.status = "cancelled"
        challenge.updated_at = now
        await _deny_mfa_verification(session)

    state = await repository.get_state(challenge.user_id, lock=True)
    if state is None or state.credential_state != "active":
        challenge.status = "cancelled"
        challenge.updated_at = now
        await _deny_mfa_verification(session)
    user = await UserRepository(session).get_by_id(challenge.user_id)
    if user is None or not user.is_active:
        challenge.status = "cancelled"
        challenge.updated_at = now
        await _deny_mfa_verification(session)

    secret_ciphertext = (
        challenge.pending_secret_ciphertext
        if challenge.purpose == "mfa_enrollment"
        else state.mfa_secret_ciphertext
    )
    if secret_ciphertext is None:
        challenge.status = "cancelled"
        challenge.updated_at = now
        await _deny_mfa_verification(session)
    valid, method, counter = await _validate_mfa_code(
        repository=repository,
        state=state,
        code=body.code,
        secret_ciphertext=secret_ciphertext,
        now=now,
        allow_recovery=challenge.purpose == "mfa_login",
    )
    if not valid:
        challenge.attempt_count += 1
        challenge.updated_at = now
        if challenge.attempt_count >= challenge.max_attempts:
            challenge.status = "locked"
        await _deny_mfa_verification(session)

    recovery_codes: list[str] = []
    if challenge.purpose == "mfa_enrollment":
        state.mfa_secret_ciphertext = secret_ciphertext
        state.mfa_enabled_at = now
        state.session_version += 1
        recovery_codes = generate_recovery_codes()
        await repository.replace_recovery_codes(user_id=user.id, raw_codes=recovery_codes, now=now)
    elif state.mfa_secret_ciphertext is not None:
        # Successful verification is the safest lazy-rotation point: the state
        # row is locked and the old key has just authenticated one real factor.
        state.mfa_secret_ciphertext = reencrypt_mfa_secret_if_needed(state.mfa_secret_ciphertext)
    state.mfa_last_counter = counter if counter is not None else state.mfa_last_counter
    state.updated_at = now
    challenge.status = "consumed"
    challenge.consumed_at = now
    challenge.updated_at = now
    auth_response = await _issue_authenticated_session(
        user=user,
        state=state,
        request=request,
        response=response,
        session=session,
        method=method,
        mfa_at=now,
    )
    await AuditLogRepository(session).record(
        action="auth.mfa_enrolled" if recovery_codes else "auth.mfa_verified",
        entity_type="user_account",
        agency_id=user.agency_id,
        user_id=user.id,
        actor_email=user.email,
        entity_id=str(user.id),
        ip_address=trusted_client_ip(request),
        metadata={"method": method},
    )
    # Publish cookies only after factor consumption, session, and audit are
    # durable together; request-scoped dependency teardown follows the response.
    await session.commit()
    if recovery_codes:
        return MFAEnrollmentResult(**auth_response.model_dump(), recovery_codes=recovery_codes)
    return auth_response
