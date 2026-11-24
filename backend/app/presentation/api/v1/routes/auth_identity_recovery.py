"""Cohesive recovery operations behind the stable identity route facade."""

from __future__ import annotations

from datetime import timedelta

from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.interfaces.identity_notification_provider import (
    IdentityNotificationDeliveryDisabled,
)
from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import UserModel
from app.infrastructure.observability.metrics import metrics
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.identity_security_repository import (
    IdentitySecurityRepository,
)
from app.infrastructure.security.identity_notifications import (
    identity_notification_provider,
    stage_password_recovery_notification,
)
from app.infrastructure.security.identity_recovery_rate_limiter import (
    IdentityRecoveryRateLimited,
    IdentityRecoveryRateLimiterUnavailable,
)
from app.presentation.api.v1.routes.auth_identity_dependencies import (
    RecoveryLimiterFactory,
    RequestHash,
    SettingsProvider,
)
from app.presentation.api.v1.schemas.auth_schemas import (
    PasswordRecoveryRequest,
    PasswordRecoveryRequestResponse,
)
from app.presentation.security.client_ip import trusted_client_ip


async def request_password_recovery(
    body: PasswordRecoveryRequest,
    request: Request,
    response: Response,
    session: AsyncSession,
    *,
    get_settings: SettingsProvider,
    IdentityRecoveryRateLimiter: RecoveryLimiterFactory,
    _request_hash: RequestHash,
) -> PasswordRecoveryRequestResponse:
    settings = get_settings()
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    neutral_response = PasswordRecoveryRequestResponse(development_recovery_token=None)
    limiter = IdentityRecoveryRateLimiter()
    try:
        await limiter.consume_network(
            ip_address=trusted_client_ip(request),
            risk_context=_request_hash(request, "user-agent"),
        )
        # Provider construction performs configuration validation without
        # delivering anything. A disabled/misconfigured production integration
        # must never mint a raw token that nobody can receive.
        identity_notification_provider(settings)
    except (
        IdentityNotificationDeliveryDisabled,
        IdentityRecoveryRateLimited,
        IdentityRecoveryRateLimiterUnavailable,
    ):
        metrics.increment("identity.password_recovery.request_suppressed")
        await limiter.close()
        return neutral_response

    email = str(body.email).lower().strip()
    user = (
        await session.execute(
            select(UserModel).where(
                UserModel.email == email,
                UserModel.is_active.is_(True),
                UserModel.deleted_at.is_(None),
                UserModel.role != UserRole.CLIENT_MANAGER.value,
            )
        )
    ).scalar_one_or_none()
    development_token: str | None = None
    if user is not None:
        account_limiter = IdentityRecoveryRateLimiter()
        try:
            await account_limiter.consume_account(user_id=user.id, agency_id=user.agency_id)
        except (IdentityRecoveryRateLimited, IdentityRecoveryRateLimiterUnavailable):
            # Preserve any previously issued link. This suppression is audited
            # internally but remains indistinguishable to the requester.
            await AuditLogRepository(session).record(
                action="auth.password_recovery_suppressed",
                entity_type="user_account",
                agency_id=user.agency_id,
                user_id=user.id,
                entity_id=str(user.id),
                ip_address=trusted_client_ip(request),
                result="blocked",
                metadata={"reason": "bounded_rate_limit"},
            )
            metrics.increment("identity.password_recovery.account_suppressed")
            await limiter.close()
            return neutral_response
        repository = IdentitySecurityRepository(session)
        state = await repository.ensure_state(user)
        if state.credential_state == "active":
            action_token, raw_token = await repository.issue_action_token(
                user_id=user.id,
                purpose="password_recovery",
                expires_in=timedelta(minutes=settings.password_recovery_token_ttl_minutes),
                request_ip_hash=_request_hash(request, "ip"),
            )
            stage_password_recovery_notification(
                session,
                user=user,
                action_token=action_token,
                raw_token=raw_token,
                settings=settings,
            )
            if settings.is_development and settings.password_recovery_development_expose_token:
                development_token = raw_token
            await AuditLogRepository(session).record(
                action="auth.password_recovery_requested",
                entity_type="user_account",
                agency_id=user.agency_id,
                user_id=user.id,
                actor_email=user.email,
                entity_id=str(user.id),
                ip_address=trusted_client_ip(request),
                metadata={
                    "delivery_staged": True,
                    "expires_in_minutes": settings.password_recovery_token_ttl_minutes,
                },
            )
    await limiter.close()
    return PasswordRecoveryRequestResponse(development_recovery_token=development_token)
