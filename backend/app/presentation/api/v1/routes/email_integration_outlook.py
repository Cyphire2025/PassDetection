"""Outlook consent callback and atomic rotating-token persistence."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.application.interfaces.email_provider import EmailProviderError
from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.email_models import EmailConnectionModel, EmailOAuthStateModel
from app.infrastructure.database.models import AgencyModel, UserModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.email.oauth import (
    hash_oauth_state,
)
from app.infrastructure.email.outlook_provider import OutlookEmailProvider
from app.infrastructure.email.token_encryption import (
    EmailTokenCipher,
    EncryptedToken,
    TokenEncryptionError,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.routes import email_integration_policy_support as _policy_support
from app.presentation.api.v1.schemas.email_integration_schemas import (
    EmailAuthorizationUrlResponse,
    EmailAuthorizeRequest,
)
from app.presentation.dependencies.csrf import require_cookie_csrf
from app.presentation.security.email_oauth_binding import (
    OAuthBindingSnapshot,
    revalidate_oauth_actor_for_persistence,
    verify_oauth_browser_binding,
)

from .email_integration_access import (
    _current_email_user,
    _enqueue_connection_sync,
    _owned_connection,
    _require_provider_account_owner,
)
from .email_integration_oauth_start import begin_provider_authorization

router = APIRouter()
logger = get_logger(__name__)

_provider_configured = _policy_support._provider_configured
_provider_scopes = _policy_support._provider_scopes
_require_feature = _policy_support._require_feature
_oauth_return_url = _policy_support._oauth_return_url


@router.post(
    "/oauth/outlook/authorize",
    response_model=EmailAuthorizationUrlResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def authorize_outlook(
    payload: EmailAuthorizeRequest,
    response: Response,
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> EmailAuthorizationUrlResponse:
    return await begin_provider_authorization("outlook", payload, response, current_user, session)


@router.get("/oauth/outlook/callback", include_in_schema=False)
async def outlook_oauth_callback(
    request: Request,
    state_value: str | None = Query(default=None, alias="state"),
    code: str | None = Query(default=None, max_length=8_192),
    error: str | None = Query(default=None, max_length=128),
    session: AsyncSession = Depends(get_db_session),
) -> RedirectResponse:
    settings = get_settings()
    if not state_value:
        return RedirectResponse(
            _oauth_return_url(settings, "failed", "outlook"),
            status_code=303,
        )
    try:
        state_hash = hash_oauth_state(state_value)
    except ValueError:
        return RedirectResponse(
            _oauth_return_url(settings, "failed", "outlook"),
            status_code=303,
        )

    state_row = await session.scalar(
        select(EmailOAuthStateModel)
        .options(undefer(EmailOAuthStateModel.code_verifier_ciphertext))
        .where(EmailOAuthStateModel.state_hash == state_hash)
        .with_for_update()
    )
    now = datetime.now(tz=UTC)
    if (
        state_row is None
        or state_row.consumed_at is not None
        or state_row.expires_at <= now
        or state_row.provider != "outlook"
    ):
        return RedirectResponse(
            _oauth_return_url(settings, "failed", "outlook"),
            status_code=303,
        )

    agency_id = state_row.agency_id
    user_id = state_row.user_id
    connection_id = state_row.connection_id
    verifier_ciphertext = bytes(state_row.code_verifier_ciphertext)
    verifier_key_version = state_row.key_version
    if not await verify_oauth_browser_binding(request, state_row, session):
        return RedirectResponse(
            _oauth_return_url(settings, "failed", "outlook"),
            status_code=303,
        )
    binding = OAuthBindingSnapshot(
        provider="outlook",
        user_id=user_id,
        nonce_hash=state_row.nonce_hash,
    )
    state_row.consumed_at = now
    await session.commit()

    if error:
        outcome = "denied" if error == "access_denied" else "cancelled"
        return RedirectResponse(
            _oauth_return_url(settings, outcome, "outlook"),
            status_code=303,
        )
    if (
        not code
        or not settings.email_integrations_enabled
        or not _provider_configured(settings, "outlook")
    ):
        return RedirectResponse(
            _oauth_return_url(settings, "failed", "outlook"),
            status_code=303,
        )
    actor_is_still_authorized = await session.scalar(
        select(UserModel.id)
        .outerjoin(AgencyModel, AgencyModel.id == UserModel.agency_id)
        .where(
            UserModel.id == user_id,
            UserModel.is_active.is_(True),
            or_(
                UserModel.role == UserRole.SUPER_ADMIN.value,
                (
                    (UserModel.agency_id == agency_id)
                    & UserModel.role.in_(
                        {
                            UserRole.AGENCY_ADMIN.value,
                            UserRole.AGENCY_MANAGER.value,
                            UserRole.AGENCY_STAFF.value,
                        }
                    )
                    & AgencyModel.is_active.is_(True)
                ),
            ),
        )
    )
    if actor_is_still_authorized is None:
        return RedirectResponse(
            _oauth_return_url(settings, "failed", "outlook"),
            status_code=303,
        )

    provider = OutlookEmailProvider(settings=settings)
    try:
        cipher = EmailTokenCipher.from_settings(settings)
        verifier = cipher.decrypt(
            EncryptedToken(
                ciphertext=verifier_ciphertext.decode("ascii"),
                key_version=verifier_key_version,
            )
        )
        token_set = await provider.exchange_authorization_code(
            code=code,
            code_verifier=verifier,
        )
        profile = await provider.get_account_profile(access_token=token_set.access_token)
        encrypted_access = cipher.encrypt(token_set.access_token)
        encrypted_refresh = (
            cipher.encrypt(token_set.refresh_token) if token_set.refresh_token else None
        )
    except (EmailProviderError, TokenEncryptionError, UnicodeDecodeError):
        logger.warning(
            "email_oauth_exchange_failed",
            agency_id=str(agency_id),
            provider="outlook",
            reconnect=connection_id is not None,
        )
        return RedirectResponse(
            _oauth_return_url(settings, "failed", "outlook"),
            status_code=303,
        )

    reconnected = connection_id is not None
    connection: EmailConnectionModel | None = None
    try:
        if not await revalidate_oauth_actor_for_persistence(
            request,
            binding,
            agency_id=agency_id,
            session=session,
        ):
            raise ValueError("Mailbox authorization changed during provider consent")
        if connection_id is not None:
            connection = await _owned_connection(
                session,
                connection_id=connection_id,
                owner_user_id=user_id,
                agency_id=agency_id,
                for_update=True,
                with_tokens=True,
            )
            if connection.provider != "outlook":
                raise ValueError("Provider mismatch")
            if connection.provider_account_id != profile.provider_account_id:
                raise ValueError("The authorized Microsoft identity does not match this connection")
            if encrypted_refresh is None and connection.refresh_token_ciphertext is None:
                raise ValueError("Microsoft did not return offline access")
        else:
            connection = await session.scalar(
                select(EmailConnectionModel)
                .options(undefer(EmailConnectionModel.refresh_token_ciphertext))
                .where(
                    EmailConnectionModel.provider == "outlook",
                    EmailConnectionModel.provider_account_id == profile.provider_account_id,
                )
                .with_for_update()
            )
            _require_provider_account_owner(
                connection,
                agency_id=agency_id,
                owner_user_id=user_id,
            )
            if connection is not None:
                reconnected = True
            else:
                if encrypted_refresh is None:
                    raise ValueError("Microsoft did not return offline access")
                connection = EmailConnectionModel(
                    id=uuid.uuid4(),
                    agency_id=agency_id,
                    owner_user_id=user_id,
                    provider="outlook",
                    provider_account_id=profile.provider_account_id,
                    email_address=profile.email_address,
                    normalized_email_address=profile.email_address.casefold(),
                    display_name=profile.display_name,
                    status="active",
                    sync_state="queued",
                    scopes=list(token_set.scopes),
                    token_key_version=cipher.key_version,
                    sync_generation=0,
                    consecutive_failures=0,
                    created_by_user_id=user_id,
                    created_at=now,
                    updated_at=now,
                )
                session.add(connection)

        if connection is None:
            raise ValueError("Email connection could not be created")
        if encrypted_refresh is None and connection.refresh_token_ciphertext is None:
            raise ValueError("Microsoft did not return offline access")
        connection.provider_account_id = profile.provider_account_id
        connection.email_address = profile.email_address
        connection.normalized_email_address = profile.email_address.casefold()
        connection.display_name = profile.display_name[:255] if profile.display_name else None
        connection.status = "active"
        connection.sync_state = "queued"
        connection.access_token_ciphertext = encrypted_access.ciphertext.encode("ascii")
        if encrypted_refresh is not None:
            # Microsoft rotates refresh tokens; every replacement is encrypted
            # and committed atomically with the access token.
            connection.refresh_token_ciphertext = encrypted_refresh.ciphertext.encode("ascii")
        connection.token_key_version = cipher.key_version
        connection.token_expires_at = token_set.expires_at
        connection.scopes = list(token_set.scopes)
        # Keep the first synchronization on the common bounded-lookback path;
        # that path snapshots a fresh Graph delta cursor before listing recent
        # inbox messages and therefore cannot miss mail during authorization.
        connection.sync_cursor = None
        connection.sync_generation += 1
        connection.next_sync_at = now
        connection.paused_at = None
        connection.disconnected_at = None
        connection.last_error_code = None
        connection.last_error_message = None
        connection.last_error_at = None
        connection.updated_at = now
        await session.flush()
        await AuditLogRepository(session).record(
            action=("email_connection_reauthorized" if reconnected else "email_connection_created"),
            entity_type="email_connection",
            entity_id=str(connection.id),
            agency_id=agency_id,
            user_id=user_id,
            actor_email=None,
            metadata={"provider": "outlook"},
        )
        await session.commit()
    except (IntegrityError, ValueError, HTTPException):
        await session.rollback()
        return RedirectResponse(
            _oauth_return_url(settings, "failed", "outlook"),
            status_code=303,
        )

    _enqueue_connection_sync(connection)
    return RedirectResponse(
        _oauth_return_url(
            settings,
            "reconnected" if reconnected else "connected",
            "outlook",
        ),
        status_code=303,
    )
