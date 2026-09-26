"""Shared consent-start protocol: owner scope, PKCE, browser binding and audit."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.interfaces.email_provider import EmailProviderError
from app.core.config.settings import get_settings
from app.domain.entities.entities import User
from app.infrastructure.database.email_models import EmailOAuthStateModel
from app.infrastructure.email.oauth import (
    generate_oauth_state,
    generate_pkce_pair,
    hash_oauth_state,
)
from app.infrastructure.email.token_encryption import EmailTokenCipher, TokenEncryptionError
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.schemas.email_integration_schemas import (
    EmailAuthorizationUrlResponse,
    EmailAuthorizeRequest,
)
from app.presentation.security.email_oauth_binding import start_oauth_browser_binding

from .email_integration_access import (
    _agency_scope,
    _default_organization_agency_id,
    _owned_connection,
    _provider_instance,
)
from .email_integration_policy_support import (
    _provider_configured,
    _provider_scopes,
    _require_feature,
)


async def begin_provider_authorization(
    provider_name: str,
    payload: EmailAuthorizeRequest,
    response: Response,
    current_user: User,
    session: AsyncSession,
) -> EmailAuthorizationUrlResponse:
    provider_label = "Gmail" if provider_name == "gmail" else "Microsoft Outlook"
    settings = get_settings()
    _require_feature(settings)
    if not _provider_configured(settings, provider_name):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{provider_label} OAuth is not configured.",
        )
    agency_scope = _agency_scope(current_user)
    if payload.connection_id is not None:
        connection = await _owned_connection(
            session,
            connection_id=payload.connection_id,
            owner_user_id=current_user.id,
            agency_id=agency_scope,
        )
        agency_id = connection.agency_id
        if connection.provider != provider_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"This connection cannot be authorized with {provider_label}.",
            )
    else:
        agency_id = await _default_organization_agency_id(session, current_user)

    state_value = generate_oauth_state()
    pkce = generate_pkce_pair()
    provider = _provider_instance(provider_name, settings)
    try:
        authorization_url = provider.build_authorization_url(
            state=state_value,
            code_challenge=pkce.challenge,
        )
        cipher = EmailTokenCipher.from_settings(settings)
    except (EmailProviderError, TokenEncryptionError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from None
    encrypted_verifier = cipher.encrypt(pkce.verifier)
    now = datetime.now(tz=UTC)
    session.add(
        EmailOAuthStateModel(
            id=uuid.uuid4(),
            agency_id=agency_id,
            user_id=current_user.id,
            connection_id=payload.connection_id,
            provider=provider_name,
            state_hash=hash_oauth_state(state_value),
            nonce_hash=start_oauth_browser_binding(
                response,
                provider=provider_name,
                user_id=current_user.id,
                session_version=current_user.session_version,
                settings=settings,
            ),
            code_verifier_ciphertext=encrypted_verifier.ciphertext.encode("ascii"),
            key_version=encrypted_verifier.key_version,
            requested_scopes=_provider_scopes(provider_name),
            return_path="/email-integrations",
            expires_at=now + timedelta(seconds=settings.email_oauth_state_ttl_seconds),
            consumed_at=None,
            created_at=now,
        )
    )
    await AuditLogRepository(session).record(
        action="email_oauth_started",
        entity_type="email_connection",
        entity_id=str(payload.connection_id) if payload.connection_id else None,
        agency_id=agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={"provider": provider_name, "reconnect": payload.connection_id is not None},
    )
    return EmailAuthorizationUrlResponse(authorization_url=authorization_url)
