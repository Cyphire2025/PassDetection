"""Tenant-scoped API for server-side email integrations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import and_, func, or_, select, true, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, undefer
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement

from app.application.interfaces.email_provider import EmailProvider, EmailProviderError
from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.email_integrations.rollout_policy import (
    email_ai_disabled_policy_exists,
    email_ai_policy_allows,
)
from app.core.config.settings import Settings, get_settings
from app.core.logging.logger import get_logger
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.email_ai_models import (
    EmailActionProposalModel,
    EmailAiAnalysisModel,
    EmailDetectedDeadlineModel,
    EmailReplyDraftModel,
)
from app.infrastructure.database.email_models import (
    EmailActivityEventModel,
    EmailArtifactDocumentModel,
    EmailArtifactModel,
    EmailConnectionModel,
    EmailMessageModel,
    EmailOAuthStateModel,
    EmailReviewItemModel,
)
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.email.account_removal import purge_email_connection_records
from app.infrastructure.email.gmail_provider import GmailEmailProvider
from app.infrastructure.email.oauth import (
    generate_oauth_state,
    generate_pkce_pair,
    hash_oauth_state,
)
from app.infrastructure.email.outlook_provider import OutlookEmailProvider
from app.infrastructure.email.sync_service import (
    ingest_reviewed_artifact,
    refresh_message_processing_state,
)
from app.infrastructure.email.token_encryption import (
    EmailTokenCipher,
    EncryptedToken,
    TokenEncryptionError,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes import (
    email_integration_policy_support as _policy_support,
)
from app.presentation.api.v1.routes import (
    email_integration_review_support as _review_support,
)
from app.presentation.api.v1.schemas.email_integration_schemas import (
    EmailActivityEventResponse,
    EmailActivityItemResponse,
    EmailAiConnectionSettingsRequest,
    EmailAiConnectionSettingsResponse,
    EmailArtifactDetailResponse,
    EmailAuthorizationUrlResponse,
    EmailAuthorizeRequest,
    EmailConnectionActionResponse,
    EmailConnectionResponse,
    EmailIntegrationStatusResponse,
    EmailIntegrationSummaryResponse,
    EmailMessageDetailResponse,
    EmailProviderAvailabilityResponse,
    EmailReviewActionResponse,
    EmailReviewGroupOption,
    EmailReviewItemResponse,
    EmailReviewOptionsResponse,
    EmailReviewPassengerOption,
    RemoveEmailConnectionRequest,
    RemoveEmailConnectionResponse,
    ResolveEmailReviewRequest,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf
from app.presentation.security.email_oauth_binding import (
    OAuthBindingSnapshot,
    revalidate_oauth_actor_for_persistence,
    start_oauth_browser_binding,
    verify_oauth_browser_binding,
)

router = APIRouter()
logger = get_logger(__name__)

_provider_configured = _policy_support._provider_configured
_provider_scopes = _policy_support._provider_scopes
_secret_is_set = _policy_support._secret_is_set
_require_feature = _policy_support._require_feature
_oauth_return_url = _policy_support._oauth_return_url
_allowed_connection_actions = _policy_support._allowed_connection_actions
_email_removal_confirmation_matches = _policy_support._email_removal_confirmation_matches

_original_email_url = _review_support._original_email_url
_string_list = _review_support._string_list
_allowed_review_actions = _review_support._allowed_review_actions
_display_conflicts = _review_support._display_conflicts
_passport_number_hint = _review_support._passport_number_hint
_artifact_source_host = _review_support._artifact_source_host
_event_title = _review_support._event_title
_event_detail = _review_support._event_detail
_bounded_event_value = _review_support._bounded_event_value

EMAIL_INTEGRATION_ROLES = [
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
    UserRole.AGENCY_STAFF,
]
_current_email_user = require_role(EMAIL_INTEGRATION_ROLES)
_ACTIVE_CONNECTION_STATUSES = {"active", "failing", "paused"}
_ACTIVE_REVIEW_STATUSES = {"open", "deferred"}


def _provider_instance(provider: str, settings: Settings) -> EmailProvider:
    if provider == "gmail":
        return GmailEmailProvider(settings=settings)
    if provider == "outlook":
        return OutlookEmailProvider(settings=settings)
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="This email provider is not supported.",
    )
def _agency_scope(user: User) -> uuid.UUID | None:
    if user.role == UserRole.SUPER_ADMIN:
        return None
    if user.agency_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is not assigned to the organization.",
        )
    return user.agency_id


def _email_owner_filters(
    owner_column: InstrumentedAttribute[uuid.UUID],
    agency_column: InstrumentedAttribute[uuid.UUID],
    user: User,
) -> tuple[ColumnElement[bool], ...]:
    """Return the immutable personal mailbox boundary for an authenticated user."""

    filters = [owner_column == user.id]
    if user.role != UserRole.SUPER_ADMIN:
        filters.append(agency_column == _agency_scope(user))
    return tuple(filters)


def _group_role_visibility_filter(user: User) -> ColumnElement[bool]:
    if user.role == UserRole.AGENCY_STAFF:
        return AuthorizationPolicy.staff_group_visibility_filter(user)
    return true()


def _passport_role_visibility_filter(user: User) -> ColumnElement[bool]:
    if user.role == UserRole.AGENCY_STAFF:
        return AuthorizationPolicy.staff_passport_visibility_filter(user)
    return true()


def _require_provider_account_owner(
    connection: EmailConnectionModel | None,
    *,
    agency_id: uuid.UUID,
    owner_user_id: uuid.UUID,
) -> None:
    """Reject reconnecting a provider identity owned by another dashboard user."""

    if connection is not None and (
        connection.agency_id != agency_id or connection.owner_user_id != owner_user_id
    ):
        raise ValueError("Provider account already belongs to another owner")


async def _default_organization_agency_id(session: AsyncSession, user: User) -> uuid.UUID:
    if user.agency_id is not None:
        return user.agency_id
    agency_id = await session.scalar(
        select(AgencyModel.id)
        .where(AgencyModel.is_active.is_(True))
        .order_by(AgencyModel.created_at.asc(), AgencyModel.id.asc())
        .limit(1)
    )
    if agency_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Create the organization before connecting an email account.",
        )
    return agency_id


async def _owned_connection(
    session: AsyncSession,
    *,
    connection_id: uuid.UUID,
    owner_user_id: uuid.UUID,
    agency_id: uuid.UUID | None,
    for_update: bool = False,
    with_tokens: bool = False,
) -> EmailConnectionModel:
    stmt = select(EmailConnectionModel).where(
        EmailConnectionModel.id == connection_id,
        EmailConnectionModel.owner_user_id == owner_user_id,
    )
    if agency_id is not None:
        stmt = stmt.where(EmailConnectionModel.agency_id == agency_id)
    if with_tokens:
        stmt = stmt.options(
            undefer(EmailConnectionModel.access_token_ciphertext),
            undefer(EmailConnectionModel.refresh_token_ciphertext),
        )
    if for_update:
        stmt = stmt.with_for_update()
    connection = await session.scalar(stmt)
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email connection was not found.",
        )
    return connection


def _enqueue_connection_sync(
    connection: EmailConnectionModel,
    *,
    provider_message_id: str | None = None,
) -> bool:
    try:
        from app.infrastructure.email.tasks import sync_email_connection

        task_kwargs = {
            "connection_id": str(connection.id),
            "agency_id": str(connection.agency_id),
            "owner_user_id": str(connection.owner_user_id),
            "provider_account_id": connection.provider_account_id,
            "sync_generation": connection.sync_generation,
        }
        if provider_message_id:
            task_kwargs["provider_message_id"] = provider_message_id
        sync_email_connection.apply_async(
            kwargs=task_kwargs,
            queue="email_integrations",
        )
        return True
    except Exception as exc:
        logger.warning(
            "email_sync_enqueue_failed",
            connection_id=str(connection.id),
            error_type=type(exc).__name__,
        )
        return False


@router.get("/status", response_model=EmailIntegrationStatusResponse)
async def email_integration_status(
    current_user: User = Depends(_current_email_user),
) -> EmailIntegrationStatusResponse:
    del current_user
    settings = get_settings()
    ai_ready = settings.email_ai_runtime_ready
    return EmailIntegrationStatusResponse(
        enabled=settings.email_integrations_enabled,
        sync_enabled=settings.email_sync_enabled,
        attachment_processing_enabled=settings.email_attachment_processing_enabled,
        auto_actions_enabled=settings.email_auto_actions_enabled,
        ai_enabled=ai_ready,
        ai_notifications_enabled=settings.email_ai_notifications_ready,
        providers=[
            EmailProviderAvailabilityResponse(
                provider="gmail",
                label="Gmail",
                configured=_provider_configured(settings, "gmail"),
            ),
            EmailProviderAvailabilityResponse(
                provider="outlook",
                label="Microsoft Outlook",
                configured=_provider_configured(settings, "outlook"),
            ),
        ],
    )


@router.get("/connections", response_model=list[EmailConnectionResponse])
async def list_email_connections(
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[EmailConnectionResponse]:
    settings = get_settings()
    result = await session.execute(
        select(
            EmailConnectionModel,
            AgencyModel.name,
            (
                ~email_ai_disabled_policy_exists(
                    agency_id=EmailConnectionModel.agency_id,
                    owner_user_id=EmailConnectionModel.owner_user_id,
                    connection_id=EmailConnectionModel.id,
                )
            ).label("ai_policy_allows"),
        )
        .join(AgencyModel, AgencyModel.id == EmailConnectionModel.agency_id)
        .where(
            *_email_owner_filters(
                EmailConnectionModel.owner_user_id,
                EmailConnectionModel.agency_id,
                current_user,
            )
        )
        .order_by(EmailConnectionModel.created_at.desc())
    )
    return [
        EmailConnectionResponse(
            id=connection.id,
            agency_id=connection.agency_id,
            agency_name=agency_name,
            provider=connection.provider,
            email_address=connection.email_address,
            status=connection.status,
            last_successful_sync_at=connection.last_successful_sync_at,
            last_sync_attempt_at=connection.last_sync_attempt_at,
            last_error_message=connection.last_error_message,
            ai_processing_enabled=connection.ai_processing_enabled,
            ai_effective_enabled=bool(
                connection.ai_processing_enabled
                and settings.email_ai_runtime_ready
                and connection.status in {"active", "failing"}
                and ai_policy_allows
            ),
            allowed_actions=_allowed_connection_actions(connection, settings),
        )
        for connection, agency_name, ai_policy_allows in result.all()
    ]


@router.post(
    "/oauth/gmail/authorize",
    response_model=EmailAuthorizationUrlResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def authorize_gmail(
    payload: EmailAuthorizeRequest,
    response: Response,
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> EmailAuthorizationUrlResponse:
    settings = get_settings()
    _require_feature(settings)
    if not _provider_configured(settings):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gmail OAuth is not configured.",
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
        if connection.provider != "gmail":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This connection cannot be authorized with Gmail.",
            )
    else:
        agency_id = await _default_organization_agency_id(session, current_user)

    state_value = generate_oauth_state()
    pkce = generate_pkce_pair()
    provider = GmailEmailProvider(settings=settings)
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
            provider="gmail",
            state_hash=hash_oauth_state(state_value),
            nonce_hash=start_oauth_browser_binding(
                response, provider="gmail", user_id=current_user.id,
                session_version=current_user.session_version, settings=settings,
            ),
            code_verifier_ciphertext=encrypted_verifier.ciphertext.encode("ascii"),
            key_version=encrypted_verifier.key_version,
            requested_scopes=["https://www.googleapis.com/auth/gmail.readonly"],
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
        metadata={"provider": "gmail", "reconnect": payload.connection_id is not None},
    )
    return EmailAuthorizationUrlResponse(authorization_url=authorization_url)


@router.get("/oauth/gmail/callback", include_in_schema=False)
async def gmail_oauth_callback(
    request: Request,
    state_value: str | None = Query(default=None, alias="state"),
    code: str | None = Query(default=None, max_length=8_192),
    error: str | None = Query(default=None, max_length=128),
    session: AsyncSession = Depends(get_db_session),
) -> RedirectResponse:
    settings = get_settings()
    if not state_value:
        return RedirectResponse(_oauth_return_url(settings, "failed"), status_code=303)
    try:
        state_hash = hash_oauth_state(state_value)
    except ValueError:
        return RedirectResponse(_oauth_return_url(settings, "failed"), status_code=303)

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
        or state_row.provider != "gmail"
    ):
        return RedirectResponse(_oauth_return_url(settings, "failed"), status_code=303)

    agency_id = state_row.agency_id
    user_id = state_row.user_id
    connection_id = state_row.connection_id
    verifier_ciphertext = bytes(state_row.code_verifier_ciphertext)
    verifier_key_version = state_row.key_version
    if not await verify_oauth_browser_binding(request, state_row, session):
        return RedirectResponse(_oauth_return_url(settings, "failed"), status_code=303)
    binding = OAuthBindingSnapshot(
        provider="gmail", user_id=user_id, nonce_hash=state_row.nonce_hash,
    )
    state_row.consumed_at = now
    await session.commit()

    if error:
        outcome = "denied" if error == "access_denied" else "cancelled"
        return RedirectResponse(_oauth_return_url(settings, outcome), status_code=303)
    if not code:
        return RedirectResponse(_oauth_return_url(settings, "failed"), status_code=303)
    if not settings.email_integrations_enabled:
        return RedirectResponse(_oauth_return_url(settings, "failed"), status_code=303)
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
        return RedirectResponse(_oauth_return_url(settings, "failed"), status_code=303)

    provider = GmailEmailProvider(settings=settings)
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
            reconnect=connection_id is not None,
        )
        return RedirectResponse(_oauth_return_url(settings, "failed"), status_code=303)

    reconnected = connection_id is not None
    connection: EmailConnectionModel | None = None
    try:
        if not await revalidate_oauth_actor_for_persistence(
            request, binding, agency_id=agency_id, session=session,
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
            if connection.provider != "gmail":
                raise ValueError("Provider mismatch")
            if connection.provider_account_id != profile.provider_account_id:
                raise ValueError("The authorized Gmail identity does not match this connection")
            if encrypted_refresh is None and connection.refresh_token_ciphertext is None:
                raise ValueError("Gmail did not return offline access")
        else:
            connection = await session.scalar(
                select(EmailConnectionModel)
                .options(undefer(EmailConnectionModel.refresh_token_ciphertext))
                .where(
                    EmailConnectionModel.provider == "gmail",
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
                    raise ValueError("Gmail did not return offline access")
                connection = EmailConnectionModel(
                    id=uuid.uuid4(),
                    agency_id=agency_id,
                    owner_user_id=user_id,
                    provider="gmail",
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
            raise ValueError("Gmail did not return offline access")
        connection.provider_account_id = profile.provider_account_id
        connection.email_address = profile.email_address
        connection.normalized_email_address = profile.email_address.casefold()
        connection.display_name = profile.display_name[:255] if profile.display_name else None
        connection.status = "active"
        connection.sync_state = "queued"
        connection.access_token_ciphertext = encrypted_access.ciphertext.encode("ascii")
        if encrypted_refresh is not None:
            connection.refresh_token_ciphertext = encrypted_refresh.ciphertext.encode("ascii")
        connection.token_key_version = cipher.key_version
        connection.token_expires_at = token_set.expires_at
        connection.scopes = list(token_set.scopes)
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
            metadata={"provider": "gmail"},
        )
        await session.commit()
    except (IntegrityError, ValueError, HTTPException):
        await session.rollback()
        try:
            await provider.revoke_token(token=token_set.refresh_token or token_set.access_token)
        except EmailProviderError as revoke_error:
            logger.warning(
                "email_oauth_cleanup_revoke_failed",
                error_code=revoke_error.code,
                error_type=type(revoke_error).__name__,
            )
        return RedirectResponse(_oauth_return_url(settings, "failed"), status_code=303)

    _enqueue_connection_sync(connection)
    return RedirectResponse(
        _oauth_return_url(
            settings,
            "reconnected" if reconnected else "connected",
        ),
        status_code=303,
    )


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
    settings = get_settings()
    _require_feature(settings)
    if not _provider_configured(settings, "outlook"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Microsoft Outlook OAuth is not configured.",
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
        if connection.provider != "outlook":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This connection cannot be authorized with Microsoft Outlook.",
            )
    else:
        agency_id = await _default_organization_agency_id(session, current_user)

    state_value = generate_oauth_state()
    pkce = generate_pkce_pair()
    provider = OutlookEmailProvider(settings=settings)
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
            provider="outlook",
            state_hash=hash_oauth_state(state_value),
            nonce_hash=start_oauth_browser_binding(
                response, provider="outlook", user_id=current_user.id,
                session_version=current_user.session_version, settings=settings,
            ),
            code_verifier_ciphertext=encrypted_verifier.ciphertext.encode("ascii"),
            key_version=encrypted_verifier.key_version,
            requested_scopes=_provider_scopes("outlook"),
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
        metadata={"provider": "outlook", "reconnect": payload.connection_id is not None},
    )
    return EmailAuthorizationUrlResponse(authorization_url=authorization_url)


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
            _oauth_return_url(settings, "failed", "outlook"), status_code=303,
        )
    binding = OAuthBindingSnapshot(
        provider="outlook", user_id=user_id, nonce_hash=state_row.nonce_hash,
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
            request, binding, agency_id=agency_id, session=session,
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


@router.post(
    "/connections/{connection_id}/sync",
    response_model=EmailConnectionActionResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def sync_connection(
    connection_id: uuid.UUID,
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> EmailConnectionActionResponse:
    settings = get_settings()
    _require_feature(settings)
    if not settings.email_sync_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email synchronization is disabled.",
        )
    connection = await _owned_connection(
        session,
        connection_id=connection_id,
        owner_user_id=current_user.id,
        agency_id=_agency_scope(current_user),
        for_update=True,
    )
    if connection.status not in {"active", "failing"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Resume or reconnect this email account before syncing.",
        )
    connection.sync_state = "queued"
    connection.next_sync_at = datetime.now(tz=UTC)
    await session.commit()
    queued = _enqueue_connection_sync(connection)
    return EmailConnectionActionResponse(
        connection_id=connection.id,
        status=connection.status,
        message=(
            "Email synchronization was queued."
            if queued
            else "Email synchronization is scheduled for the next worker cycle."
        ),
    )


@router.post(
    "/connections/{connection_id}/pause",
    response_model=EmailConnectionActionResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def pause_connection(
    connection_id: uuid.UUID,
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> EmailConnectionActionResponse:
    agency_id = _agency_scope(current_user)
    connection = await _owned_connection(
        session,
        connection_id=connection_id,
        owner_user_id=current_user.id,
        agency_id=agency_id,
        for_update=True,
    )
    agency_id = connection.agency_id
    if connection.status == "disconnected":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reconnect this email account before pausing it.",
        )
    now = datetime.now(tz=UTC)
    connection.status = "paused"
    connection.sync_state = "idle"
    connection.sync_generation += 1
    connection.sync_lease_token = None
    connection.sync_lease_expires_at = None
    connection.next_sync_at = None
    connection.paused_at = now
    await AuditLogRepository(session).record(
        action="email_connection_paused",
        entity_type="email_connection",
        entity_id=str(connection.id),
        agency_id=agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={"provider": connection.provider},
    )
    return EmailConnectionActionResponse(
        connection_id=connection.id,
        status=connection.status,
        message="Email monitoring is paused for this account.",
    )


@router.post(
    "/connections/{connection_id}/resume",
    response_model=EmailConnectionActionResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def resume_connection(
    connection_id: uuid.UUID,
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> EmailConnectionActionResponse:
    settings = get_settings()
    _require_feature(settings)
    if not settings.email_sync_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email synchronization is disabled.",
        )
    connection = await _owned_connection(
        session,
        connection_id=connection_id,
        owner_user_id=current_user.id,
        agency_id=_agency_scope(current_user),
        for_update=True,
    )
    if connection.status != "paused":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a paused email connection can be resumed.",
        )
    connection.status = "active"
    connection.sync_state = "queued"
    connection.sync_generation += 1
    connection.next_sync_at = datetime.now(tz=UTC)
    connection.paused_at = None
    await session.commit()
    queued = _enqueue_connection_sync(connection)
    return EmailConnectionActionResponse(
        connection_id=connection.id,
        status=connection.status,
        message=(
            "Email monitoring resumed and synchronization was queued."
            if queued
            else "Email monitoring resumed; synchronization will start next cycle."
        ),
    )


@router.delete(
    "/connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_cookie_csrf)],
)
async def disconnect_email_connection(
    connection_id: uuid.UUID,
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    agency_id = _agency_scope(current_user)
    connection = await _owned_connection(
        session,
        connection_id=connection_id,
        owner_user_id=current_user.id,
        agency_id=agency_id,
        for_update=True,
        with_tokens=True,
    )
    agency_id = connection.agency_id
    provider = _provider_instance(connection.provider, get_settings())
    if (
        connection.status == "disconnected"
        and not connection.access_token_ciphertext
        and not connection.refresh_token_ciphertext
    ):
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    token_to_revoke: str | None = None
    decryption_failed = False
    if provider.supports_remote_token_revocation:
        try:
            cipher = EmailTokenCipher.from_settings()
            if connection.refresh_token_ciphertext:
                token_to_revoke = cipher.decrypt(
                    EncryptedToken(
                        ciphertext=connection.refresh_token_ciphertext.decode("ascii"),
                        key_version=connection.token_key_version,
                    )
                )
            elif connection.access_token_ciphertext:
                token_to_revoke = cipher.decrypt(
                    EncryptedToken(
                        ciphertext=connection.access_token_ciphertext.decode("ascii"),
                        key_version=connection.token_key_version,
                    )
                )
        except (TokenEncryptionError, UnicodeDecodeError):
            decryption_failed = True

    now = datetime.now(tz=UTC)
    connection.status = "disconnecting"
    connection.sync_state = "blocked"
    connection.sync_generation += 1
    connection.sync_lease_token = None
    connection.sync_lease_expires_at = None
    connection.next_sync_at = None
    connection.updated_at = now
    await session.commit()

    revoke_error: EmailProviderError | None = None
    if decryption_failed:
        revoke_error = EmailProviderError(
            "Stored email credentials could not be opened",
            code="EMAIL_TOKEN_DECRYPTION_FAILED",
        )
    elif token_to_revoke:
        try:
            await provider.revoke_token(token=token_to_revoke)
        except EmailProviderError as exc:
            # Revocation endpoints commonly report an already-invalid token as
            # a client error. In that case access is already gone and local
            # credential removal is safe.
            if exc.status_code not in {400, 401, 404}:
                revoke_error = exc

    connection = await _owned_connection(
        session,
        connection_id=connection_id,
        owner_user_id=current_user.id,
        agency_id=agency_id,
        for_update=True,
        with_tokens=True,
    )
    now = datetime.now(tz=UTC)
    if revoke_error is not None:
        connection.status = "disconnecting"
        connection.sync_state = "blocked"
        connection.next_sync_at = None
        connection.last_error_code = revoke_error.code[:80]
        connection.last_error_message = (
            "Provider access could not be revoked. Retry disconnecting this account."
        )
        connection.last_error_at = now
        connection.updated_at = now
        await AuditLogRepository(session).record(
            action="email_connection_disconnect_failed",
            entity_type="email_connection",
            entity_id=str(connection.id),
            agency_id=agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "provider": connection.provider,
                "error_code": revoke_error.code,
            },
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Provider access could not be revoked. The connection remains "
                "blocked; retry disconnecting it."
            ),
        )

    connection.status = "disconnected"
    connection.sync_state = "blocked"
    connection.access_token_ciphertext = None
    connection.refresh_token_ciphertext = None
    connection.token_expires_at = None
    connection.disconnected_at = now
    connection.last_error_code = None
    connection.last_error_message = None
    connection.last_error_at = None
    connection.updated_at = now
    await AuditLogRepository(session).record(
        action="email_connection_disconnected",
        entity_type="email_connection",
        entity_id=str(connection.id),
        agency_id=agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "provider": connection.provider,
            "provider_revoke_required": (
                provider.supports_remote_token_revocation and token_to_revoke is not None
            ),
            "provider_revoke_succeeded": (
                True
                if provider.supports_remote_token_revocation and token_to_revoke is not None
                else None
            ),
            "credential_disposition": "local_credentials_deleted",
        },
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/connections/{connection_id}/data",
    response_model=RemoveEmailConnectionResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def remove_email_connection_and_data(
    connection_id: uuid.UUID,
    payload: RemoveEmailConnectionRequest,
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> RemoveEmailConnectionResponse:
    """Permanently remove one owned mailbox and its attributable data."""

    agency_scope = _agency_scope(current_user)
    connection = await _owned_connection(
        session,
        connection_id=connection_id,
        owner_user_id=current_user.id,
        agency_id=agency_scope,
        for_update=True,
        with_tokens=True,
    )
    if not _email_removal_confirmation_matches(
        confirmation_email=payload.confirmation_email,
        connection_email=connection.email_address,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Type the connected email address exactly to confirm removal.",
        )

    agency_id = connection.agency_id
    provider = _provider_instance(connection.provider, get_settings())
    provider_name = connection.provider
    token_to_revoke: str | None = None
    decryption_failed = False
    credentials_already_removed = (
        connection.status == "disconnected"
        and not connection.access_token_ciphertext
        and not connection.refresh_token_ciphertext
    )
    if provider.supports_remote_token_revocation and not credentials_already_removed:
        try:
            cipher = EmailTokenCipher.from_settings()
            if connection.refresh_token_ciphertext:
                token_to_revoke = cipher.decrypt(
                    EncryptedToken(
                        ciphertext=connection.refresh_token_ciphertext.decode("ascii"),
                        key_version=connection.token_key_version,
                    )
                )
            elif connection.access_token_ciphertext:
                token_to_revoke = cipher.decrypt(
                    EncryptedToken(
                        ciphertext=connection.access_token_ciphertext.decode("ascii"),
                        key_version=connection.token_key_version,
                    )
                )
        except (TokenEncryptionError, UnicodeDecodeError):
            decryption_failed = True

    # Commit the generation fence before contacting the provider. Any worker
    # already holding a stale claim will fail its ownership/generation checks.
    now = datetime.now(tz=UTC)
    connection.status = "disconnecting"
    connection.sync_state = "blocked"
    connection.sync_generation += 1
    connection.sync_lease_token = None
    connection.sync_lease_expires_at = None
    connection.next_sync_at = None
    connection.updated_at = now
    await session.commit()

    revoke_error: EmailProviderError | None = None
    if decryption_failed:
        revoke_error = EmailProviderError(
            "Stored email credentials could not be opened",
            code="EMAIL_TOKEN_DECRYPTION_FAILED",
        )
    elif token_to_revoke:
        try:
            await provider.revoke_token(token=token_to_revoke)
        except EmailProviderError as exc:
            if exc.status_code not in {400, 401, 404}:
                revoke_error = exc

    connection = await _owned_connection(
        session,
        connection_id=connection_id,
        owner_user_id=current_user.id,
        agency_id=agency_id,
        for_update=True,
        with_tokens=True,
    )
    if revoke_error is not None:
        now = datetime.now(tz=UTC)
        connection.status = "disconnecting"
        connection.sync_state = "blocked"
        connection.next_sync_at = None
        connection.last_error_code = revoke_error.code[:80]
        connection.last_error_message = (
            "Provider access could not be revoked. Retry removing this account."
        )
        connection.last_error_at = now
        connection.updated_at = now
        await AuditLogRepository(session).record(
            action="email_connection_removal_failed",
            entity_type="email_connection",
            entity_id=str(connection.id),
            agency_id=agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "provider": provider_name,
                "error_code": revoke_error.code,
            },
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Provider access could not be revoked. The connection remains "
                "blocked; retry removing it."
            ),
        )

    try:
        removal = await purge_email_connection_records(
            session,
            connection=connection,
        )
        await AuditLogRepository(session).record(
            action="email_connection_data_removed",
            entity_type="email_connection",
            entity_id=str(removal.connection_id),
            agency_id=agency_id,
            user_id=current_user.id,
            actor_email=None,
            metadata={
                "provider": provider_name,
                "messages_removed": removal.message_count,
                "artifacts_removed": removal.artifact_count,
                "reviews_removed": removal.review_count,
                "activity_events_removed": removal.activity_count,
                "documents_removed": removal.document_count,
                "notifications_removed": removal.notification_count,
                "credential_disposition": "local_credentials_deleted",
            },
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    storage_cleanup_pending = False
    if removal.storage_keys:
        try:
            await MinioStorageRepository().delete_files(list(removal.storage_keys))
        except Exception as exc:
            # Relational cleanup is already committed. The retention sweeper
            # safely removes these now-unreferenced objects on a later pass.
            storage_cleanup_pending = True
            logger.error(
                "email_connection_storage_cleanup_deferred",
                connection_id=str(removal.connection_id),
                object_count=len(removal.storage_keys),
                error_type=type(exc).__name__,
            )

    return RemoveEmailConnectionResponse(
        connection_id=removal.connection_id,
        messages_removed=removal.message_count,
        artifacts_removed=removal.artifact_count,
        reviews_removed=removal.review_count,
        activity_events_removed=removal.activity_count,
        documents_removed=removal.document_count,
        notifications_removed=removal.notification_count,
        storage_cleanup_pending=storage_cleanup_pending,
        message="The email account and its stored integration data were removed.",
    )


@router.put(
    "/connections/{connection_id}/ai-settings",
    response_model=EmailAiConnectionSettingsResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def update_connection_ai_settings(
    connection_id: uuid.UUID,
    payload: EmailAiConnectionSettingsRequest,
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> EmailAiConnectionSettingsResponse:
    """Opt the authenticated owner's mailbox into or out of AI analysis."""

    connection = await _owned_connection(
        session,
        connection_id=connection_id,
        owner_user_id=current_user.id,
        agency_id=current_user.agency_id,
        for_update=True,
    )
    now = datetime.now(tz=UTC)
    was_enabled = connection.ai_processing_enabled
    connection.ai_processing_enabled = payload.enabled
    connection.updated_at = now
    if payload.enabled and (not was_enabled or connection.ai_enabled_at is None):
        # New analysis starts at an explicit opt-in watermark. Historical
        # backfill is intentionally a separate future operation.
        connection.ai_enabled_at = now
    if not payload.enabled:
        await session.execute(
            update(EmailAiAnalysisModel)
            .where(
                EmailAiAnalysisModel.connection_id == connection.id,
                EmailAiAnalysisModel.agency_id == connection.agency_id,
                EmailAiAnalysisModel.owner_user_id == current_user.id,
                EmailAiAnalysisModel.status.in_({"pending", "processing"}),
            )
            .values(
                status="ignored",
                needs_attention=False,
                lease_token=None,
                lease_expires_at=None,
                next_attempt_at=None,
                started_at=None,
                completed_at=now,
                last_error_code="account_ai_opted_out",
            )
            .execution_options(synchronize_session=False)
        )
    await AuditLogRepository(session).record(
        agency_id=connection.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        action=(
            "email_ai.account_enabled"
            if payload.enabled
            else "email_ai.account_disabled"
        ),
        entity_type="email_connection",
        entity_id=str(connection.id),
        metadata={"provider": connection.provider},
    )
    settings = get_settings()
    effective_enabled = bool(
        payload.enabled
        and settings.email_ai_runtime_ready
        and connection.status in {"active", "failing"}
        and await email_ai_policy_allows(
            session,
            agency_id=connection.agency_id,
            owner_user_id=current_user.id,
            connection_id=connection.id,
        )
    )
    if effective_enabled:
        message = "Travel email analysis is active for this account."
    elif payload.enabled:
        message = (
            "This account is opted in, but an organization, user, account, "
            "deployment, or mailbox safety control is keeping analysis inactive."
        )
    else:
        message = "Travel email analysis is off for this account."
    return EmailAiConnectionSettingsResponse(
        connection_id=connection.id,
        enabled=payload.enabled,
        effective_enabled=effective_enabled,
        message=message,
    )


@router.get("/summary", response_model=EmailIntegrationSummaryResponse)
async def email_integration_summary(
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> EmailIntegrationSummaryResponse:
    today = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    async def count(stmt: Select[tuple[int]]) -> int:
        return int(await session.scalar(stmt) or 0)

    return EmailIntegrationSummaryResponse(
        connected_accounts=await count(
            select(func.count(EmailConnectionModel.id)).where(
                *_email_owner_filters(
                    EmailConnectionModel.owner_user_id,
                    EmailConnectionModel.agency_id,
                    current_user,
                ),
                EmailConnectionModel.status.in_(_ACTIVE_CONNECTION_STATUSES),
            )
        ),
        relevant_emails_today=await count(
            select(func.count(EmailMessageModel.id)).where(
                *_email_owner_filters(
                    EmailMessageModel.owner_user_id,
                    EmailMessageModel.agency_id,
                    current_user,
                ),
                EmailMessageModel.relevance_status == "relevant",
                EmailMessageModel.received_at >= today,
            )
        ),
        documents_retrieved_today=await count(
            select(func.count(EmailArtifactModel.id)).where(
                *_email_owner_filters(
                    EmailArtifactModel.owner_user_id,
                    EmailArtifactModel.agency_id,
                    current_user,
                ),
                EmailArtifactModel.retrieved_at >= today,
            )
        ),
        automatically_matched_today=await count(
            select(func.count(EmailArtifactDocumentModel.id)).where(
                *_email_owner_filters(
                    EmailArtifactDocumentModel.owner_user_id,
                    EmailArtifactDocumentModel.agency_id,
                    current_user,
                ),
                EmailArtifactDocumentModel.created_at >= today,
                EmailArtifactDocumentModel.match_evidence["human_confirmed"]
                .as_boolean()
                .is_(False),
            )
        ),
        revisions_detected_today=await count(
            select(func.count(EmailReviewItemModel.id)).where(
                *_email_owner_filters(
                    EmailReviewItemModel.owner_user_id,
                    EmailReviewItemModel.agency_id,
                    current_user,
                ),
                EmailReviewItemModel.review_type == "possible_revision",
                EmailReviewItemModel.created_at >= today,
            )
        ),
        pending_review=await count(
            select(func.count(EmailReviewItemModel.id)).where(
                *_email_owner_filters(
                    EmailReviewItemModel.owner_user_id,
                    EmailReviewItemModel.agency_id,
                    current_user,
                ),
                EmailReviewItemModel.status.in_(_ACTIVE_REVIEW_STATUSES),
            )
        ),
        retrieval_failures_today=await count(
            select(func.count(EmailArtifactModel.id)).where(
                *_email_owner_filters(
                    EmailArtifactModel.owner_user_id,
                    EmailArtifactModel.agency_id,
                    current_user,
                ),
                EmailArtifactModel.retrieval_status == "failed",
                EmailArtifactModel.last_error_at >= today,
            )
        ),
    )


@router.get("/reviews", response_model=list[EmailReviewItemResponse])
async def list_email_reviews(
    review_status: str = Query(default="open", alias="status"),
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[EmailReviewItemResponse]:
    now = datetime.now(tz=UTC)
    if review_status not in {
        "open",
        "deferred",
        "resolved",
        "rejected",
        "cancelled",
        "all",
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported review status.",
        )
    stmt = (
        select(
            EmailReviewItemModel,
            EmailMessageModel,
            EmailArtifactModel,
            ClientGroupModel.name,
            PassportSubmissionModel.client_name,
        )
        .join(
            EmailMessageModel,
            and_(
                EmailMessageModel.id == EmailReviewItemModel.message_id,
                EmailMessageModel.owner_user_id == EmailReviewItemModel.owner_user_id,
            ),
        )
        .outerjoin(
            EmailArtifactModel,
            and_(
                EmailArtifactModel.id == EmailReviewItemModel.artifact_id,
                EmailArtifactModel.owner_user_id == EmailReviewItemModel.owner_user_id,
            ),
        )
        .outerjoin(
            ClientGroupModel,
            and_(
                ClientGroupModel.id == EmailReviewItemModel.candidate_group_id,
                ClientGroupModel.agency_id == EmailReviewItemModel.agency_id,
                _group_role_visibility_filter(current_user),
            ),
        )
        .outerjoin(
            PassportSubmissionModel,
            and_(
                PassportSubmissionModel.id == EmailReviewItemModel.candidate_passenger_id,
                PassportSubmissionModel.agency_id == EmailReviewItemModel.agency_id,
                _passport_role_visibility_filter(current_user),
            ),
        )
        .where(
            *_email_owner_filters(
                EmailReviewItemModel.owner_user_id,
                EmailReviewItemModel.agency_id,
                current_user,
            ),
            EmailMessageModel.owner_user_id == current_user.id,
            or_(
                EmailArtifactModel.id.is_(None),
                EmailArtifactModel.owner_user_id == current_user.id,
            ),
        )
    )
    if review_status == "open":
        stmt = stmt.where(
            or_(
                EmailReviewItemModel.status == "open",
                (
                    (EmailReviewItemModel.status == "deferred")
                    & (EmailReviewItemModel.deferred_until.is_not(None))
                    & (EmailReviewItemModel.deferred_until <= now)
                ),
            )
        )
    elif review_status == "deferred":
        stmt = stmt.where(
            EmailReviewItemModel.status == "deferred",
            or_(
                EmailReviewItemModel.deferred_until.is_(None),
                EmailReviewItemModel.deferred_until > now,
            ),
        )
    elif review_status != "all":
        stmt = stmt.where(EmailReviewItemModel.status == review_status)
    result = await session.execute(stmt.order_by(EmailReviewItemModel.created_at.desc()).limit(250))
    responses: list[EmailReviewItemResponse] = []
    for review, message, artifact, group_name, passenger_name in result.all():
        responses.append(
            EmailReviewItemResponse(
                id=review.id,
                email_message_id=message.id,
                artifact_id=artifact.id if artifact else None,
                status=(
                    "open"
                    if (
                        review.status == "deferred"
                        and review.deferred_until is not None
                        and review.deferred_until <= now
                    )
                    else review.status
                ),
                review_type=review.review_type,
                sender_email=message.sender_address or "Unknown sender",
                subject=message.subject or "(No subject)",
                received_at=message.received_at,
                artifact_name=artifact.filename if artifact else None,
                artifact_kind=artifact.kind if artifact else None,
                artifact_detected_type=artifact.detected_type if artifact else None,
                proposed_group_id=(review.candidate_group_id if group_name is not None else None),
                proposed_group_name=group_name,
                proposed_passenger_id=(
                    review.candidate_passenger_id if passenger_name is not None else None
                ),
                proposed_passenger_name=passenger_name,
                confidence=float(review.confidence or 0.0),
                evidence=_string_list(review.evidence.get("signals", [])),
                conflicts=_display_conflicts(review.conflicts),
                proposed_action=review.proposed_action,
                allowed_actions=_allowed_review_actions(review, artifact),
                revision=review.revision,
                created_at=review.created_at,
            )
        )
    return responses


@router.get("/review-options", response_model=EmailReviewOptionsResponse)
async def email_review_options(
    group_id: uuid.UUID | None = None,
    message_id: uuid.UUID | None = None,
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> EmailReviewOptionsResponse:
    context_agency_id: uuid.UUID | None = None
    if message_id is not None:
        context_agency_id = (
            await session.execute(
                select(EmailMessageModel.agency_id)
                .join(
                    EmailConnectionModel,
                    and_(
                        EmailConnectionModel.id
                        == EmailMessageModel.connection_id,
                        EmailConnectionModel.agency_id
                        == EmailMessageModel.agency_id,
                        EmailConnectionModel.owner_user_id
                        == EmailMessageModel.owner_user_id,
                    ),
                )
                .where(
                    EmailMessageModel.id == message_id,
                    EmailConnectionModel.owner_user_id == current_user.id,
                    *_email_owner_filters(
                        EmailMessageModel.owner_user_id,
                        EmailMessageModel.agency_id,
                        current_user,
                    ),
                )
            )
        ).scalar_one_or_none()
        if context_agency_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Email activity item was not found.",
            )

    groups_stmt = select(ClientGroupModel).where(
        ClientGroupModel.status.notin_({"archived", "deleted"})
    )
    if context_agency_id is not None:
        groups_stmt = groups_stmt.where(
            ClientGroupModel.agency_id == context_agency_id
        )
        groups_stmt = AuthorizationPolicy.apply_group_visibility_scope(
            groups_stmt,
            current_user,
        )
    elif current_user.role == UserRole.SUPER_ADMIN:
        groups_stmt = groups_stmt.where(
            ClientGroupModel.agency_id.in_(
                select(EmailConnectionModel.agency_id).where(
                    EmailConnectionModel.owner_user_id == current_user.id
                )
            )
        )
    else:
        _agency_scope(current_user)
        groups_stmt = AuthorizationPolicy.apply_group_visibility_scope(
            groups_stmt,
            current_user,
        )
    groups_result = await session.execute(groups_stmt.order_by(ClientGroupModel.created_at.desc()))
    groups = list(groups_result.scalars().all())
    passengers: list[PassportSubmissionModel] = []
    if group_id is not None:
        selected_group_stmt = select(ClientGroupModel).where(
            ClientGroupModel.id == group_id,
            ClientGroupModel.status.notin_({"archived", "deleted"}),
        )
        if context_agency_id is not None:
            selected_group_stmt = selected_group_stmt.where(
                ClientGroupModel.agency_id == context_agency_id
            )
            selected_group_stmt = (
                AuthorizationPolicy.apply_group_visibility_scope(
                    selected_group_stmt,
                    current_user,
                )
            )
        elif current_user.role == UserRole.SUPER_ADMIN:
            selected_group_stmt = selected_group_stmt.where(
                ClientGroupModel.agency_id.in_(
                    select(EmailConnectionModel.agency_id).where(
                        EmailConnectionModel.owner_user_id == current_user.id
                    )
                )
            )
        else:
            selected_group_stmt = AuthorizationPolicy.apply_group_visibility_scope(
                selected_group_stmt,
                current_user,
            )
        selected_group = await session.scalar(selected_group_stmt)
        if selected_group is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Client group was not found.",
            )
        passengers_stmt = select(PassportSubmissionModel).where(
            PassportSubmissionModel.agency_id == selected_group.agency_id,
            PassportSubmissionModel.group_id == group_id,
        )
        if current_user.role != UserRole.SUPER_ADMIN:
            passengers_stmt = AuthorizationPolicy.apply_passport_visibility_scope(
                passengers_stmt,
                current_user,
            )
        passengers_result = await session.execute(
            passengers_stmt.order_by(PassportSubmissionModel.client_name.asc()).limit(5_000)
        )
        passengers = list(passengers_result.scalars().all())
    return EmailReviewOptionsResponse(
        groups=[
            EmailReviewGroupOption(
                id=group.id,
                name=group.name,
                destination=group.destination,
                travel_date=group.travel_date,
            )
            for group in groups
        ],
        passengers=[
            EmailReviewPassengerOption(
                id=passenger.id,
                group_id=passenger.group_id,
                name=passenger.client_name,
                passport_number_hint=_passport_number_hint(passenger),
            )
            for passenger in passengers
        ],
    )


@router.post(
    "/reviews/{review_id}/resolve",
    response_model=EmailReviewActionResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def resolve_email_review(
    review_id: uuid.UUID,
    payload: ResolveEmailReviewRequest,
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> EmailReviewActionResponse:
    settings = get_settings()
    if payload.action in {"approve", "assign", "retry"}:
        _require_feature(settings)
    if payload.action == "retry" and not settings.email_sync_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email synchronization is disabled.",
        )
    review_identity = (
        await session.execute(
            select(
                EmailReviewItemModel.message_id,
                EmailReviewItemModel.artifact_id,
                EmailMessageModel.connection_id,
                EmailReviewItemModel.agency_id,
            )
            .join(
                EmailMessageModel,
                EmailMessageModel.id == EmailReviewItemModel.message_id,
            )
            .where(
                EmailReviewItemModel.id == review_id,
                *_email_owner_filters(
                    EmailReviewItemModel.owner_user_id,
                    EmailReviewItemModel.agency_id,
                    current_user,
                ),
                *_email_owner_filters(
                    EmailMessageModel.owner_user_id,
                    EmailMessageModel.agency_id,
                    current_user,
                ),
            )
        )
    ).one_or_none()
    if review_identity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email review item was not found.",
        )
    message_id, artifact_id, connection_id, agency_id = review_identity

    # Match the worker's lock order: connection -> message -> artifact ->
    # review. This serializes sync and every staff decision for one mailbox
    # without review/message or message/connection lock inversions.
    connection = await _owned_connection(
        session,
        connection_id=connection_id,
        owner_user_id=current_user.id,
        agency_id=agency_id,
        for_update=True,
    )
    message = await session.scalar(
        select(EmailMessageModel)
        .where(
            EmailMessageModel.id == message_id,
            EmailMessageModel.agency_id == agency_id,
            EmailMessageModel.owner_user_id == current_user.id,
            EmailMessageModel.connection_id == connection.id,
        )
        .with_for_update()
    )
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The source email is no longer available.",
        )
    artifact = (
        await session.scalar(
            select(EmailArtifactModel)
            .where(
                EmailArtifactModel.id == artifact_id,
                EmailArtifactModel.agency_id == agency_id,
                EmailArtifactModel.owner_user_id == current_user.id,
                EmailArtifactModel.message_id == message.id,
            )
            .with_for_update()
        )
        if artifact_id
        else None
    )
    review = await session.scalar(
        select(EmailReviewItemModel)
        .where(
            EmailReviewItemModel.id == review_id,
            EmailReviewItemModel.agency_id == agency_id,
            EmailReviewItemModel.owner_user_id == current_user.id,
            EmailReviewItemModel.message_id == message.id,
        )
        .with_for_update()
    )
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email review item was not found.",
        )
    if review.revision != payload.expected_revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This review item changed. Refresh it before deciding.",
        )
    if review.status not in _ACTIVE_REVIEW_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This email review item is already closed.",
        )
    if payload.action not in _allowed_review_actions(review, artifact):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="That action is not available for this review item.",
        )
    now = datetime.now(tz=UTC)
    should_queue_retry = False
    created_storage_keys: list[str] = []

    if payload.action in {"approve", "assign"}:
        if artifact is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This review item has no document to assign.",
            )
        if artifact.detected_type not in {"visa", "flight_ticket"}:
            if (
                artifact.detected_type == "unknown"
                and payload.document_type in {"visa", "flight_ticket"}
                and artifact.storage_key
            ):
                artifact.detected_type = payload.document_type
            else:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=("Choose a supported PDF document type before assigning this item."),
                )
        selected_group_id = payload.group_id or review.candidate_group_id
        selected_passenger_id = payload.passenger_id or review.candidate_passenger_id
        if selected_group_id is None or selected_passenger_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Choose both a client group and passenger.",
            )
        group_stmt = select(ClientGroupModel).where(
            ClientGroupModel.id == selected_group_id,
            ClientGroupModel.agency_id == agency_id,
            ClientGroupModel.status.notin_({"archived", "deleted"}),
        )
        passenger_stmt = select(PassportSubmissionModel).where(
            PassportSubmissionModel.id == selected_passenger_id,
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == selected_group_id,
        )
        if current_user.role != UserRole.SUPER_ADMIN:
            group_stmt = AuthorizationPolicy.apply_group_visibility_scope(
                group_stmt,
                current_user,
            )
            passenger_stmt = AuthorizationPolicy.apply_passport_visibility_scope(
                passenger_stmt,
                current_user,
            )
        group = await session.scalar(group_stmt)
        passenger = await session.scalar(passenger_stmt)
        if group is None or passenger is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="The selected group and passenger do not match.",
            )
        try:
            ingestion_result = await ingest_reviewed_artifact(
                session,
                review=review,
                group_id=selected_group_id,
                passenger_id=selected_passenger_id,
                created_by_user_id=current_user.id,
                actor_email=current_user.email,
            )
            created_storage_keys = list(ingestion_result.storage_keys)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from None
        review.selected_group_id = selected_group_id
        review.selected_passenger_id = selected_passenger_id
        review.status = "resolved"
        review.resolution_code = payload.action
        review.resolved_at = now
        result_message = (
            "The exact document was already present for this passenger; "
            "the duplicate was recorded without creating another copy."
            if ingestion_result.duplicate
            else "The email document was added to the passenger record."
        )
    elif payload.action == "mark_unrelated":
        review.status = "resolved"
        review.resolution_code = "marked_unrelated"
        review.resolved_at = now
        message.relevance_status = "ignored"
        message.processing_status = "ignored"
        evidence = dict(message.evidence_json or {})
        evidence["human_marked_unrelated"] = True
        evidence["human_marked_unrelated_at"] = now.isoformat()
        evidence["human_marked_unrelated_by"] = str(current_user.id)
        message.evidence_json = evidence
        await session.execute(
            update(EmailAiAnalysisModel)
            .where(
                EmailAiAnalysisModel.message_id == message.id,
                EmailAiAnalysisModel.connection_id == message.connection_id,
                EmailAiAnalysisModel.agency_id == agency_id,
                EmailAiAnalysisModel.owner_user_id == current_user.id,
                EmailAiAnalysisModel.status.in_(
                    {
                        "pending",
                        "processing",
                        "completed",
                        "review_required",
                        "failed",
                    }
                ),
            )
            .values(
                status="ignored",
                needs_attention=False,
                lease_token=None,
                lease_expires_at=None,
                next_attempt_at=None,
                completed_at=now,
                last_error_code="human_marked_unrelated",
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        await session.execute(
            update(EmailActionProposalModel)
            .where(
                EmailActionProposalModel.message_id == message.id,
                EmailActionProposalModel.agency_id == agency_id,
                EmailActionProposalModel.owner_user_id == current_user.id,
                EmailActionProposalModel.status.in_(
                    {"proposed", "approval_required", "blocked"}
                ),
            )
            .values(
                status="dismissed",
                decision_by_user_id=current_user.id,
                decision_at=now,
                decision_note="Source email marked unrelated by its owner.",
                revision=EmailActionProposalModel.revision + 1,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        await session.execute(
            update(EmailDetectedDeadlineModel)
            .where(
                EmailDetectedDeadlineModel.message_id == message.id,
                EmailDetectedDeadlineModel.agency_id == agency_id,
                EmailDetectedDeadlineModel.owner_user_id == current_user.id,
                EmailDetectedDeadlineModel.status.in_(
                    {"detected", "review_required", "acknowledged"}
                ),
            )
            .values(status="dismissed", updated_at=now)
            .execution_options(synchronize_session=False)
        )
        await session.execute(
            update(EmailReplyDraftModel)
            .where(
                EmailReplyDraftModel.message_id == message.id,
                EmailReplyDraftModel.agency_id == agency_id,
                EmailReplyDraftModel.owner_user_id == current_user.id,
                EmailReplyDraftModel.status.in_(
                    {"prepared", "edited", "approved"}
                ),
            )
            .values(
                status="dismissed",
                revision=EmailReplyDraftModel.revision + 1,
                edited_by_user_id=current_user.id,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        related_artifacts = list(
            (
                await session.execute(
                    select(EmailArtifactModel)
                    .where(
                        EmailArtifactModel.message_id == message.id,
                        EmailArtifactModel.owner_user_id == current_user.id,
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for related_artifact in related_artifacts:
            related_artifact.processing_status = "ignored"
            related_artifact.updated_at = now
        sibling_reviews = list(
            (
                await session.execute(
                    select(EmailReviewItemModel)
                    .where(
                        EmailReviewItemModel.message_id == message.id,
                        EmailReviewItemModel.owner_user_id == current_user.id,
                        EmailReviewItemModel.id != review.id,
                        EmailReviewItemModel.status.in_(_ACTIVE_REVIEW_STATUSES),
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for sibling in sibling_reviews:
            sibling.status = "cancelled"
            sibling.resolution_code = "message_marked_unrelated"
            sibling.resolved_by_user_id = current_user.id
            sibling.resolved_at = now
            sibling.revision += 1
            sibling.updated_at = now
        result_message = "The email was marked as unrelated."
    elif payload.action == "reject":
        review.status = "rejected"
        review.resolution_code = "rejected"
        review.resolved_at = now
        if artifact is not None:
            artifact.processing_status = "ignored"
        result_message = "The proposed email action was rejected."
    elif payload.action == "defer":
        review.status = "deferred"
        review.resolution_code = "deferred"
        review.deferred_until = now + timedelta(days=1)
        result_message = "The review was deferred for 24 hours."
    else:
        if connection.status not in {"active", "failing"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Resume or reconnect the email account before retrying.",
            )
        review.status = "resolved"
        review.resolution_code = "retry_queued"
        review.resolved_at = now
        if artifact is not None:
            artifact.retrieval_status = "pending"
            artifact.processing_status = "pending"
            artifact.next_retry_at = now
        message.processing_status = "queued"
        connection.sync_state = "queued"
        connection.next_sync_at = now
        should_queue_retry = True
        result_message = "The email item was queued for another processing attempt."

    review.resolved_by_user_id = None if payload.action == "defer" else current_user.id
    review.revision += 1
    review.updated_at = now
    session.add(
        EmailActivityEventModel(
            id=uuid.uuid4(),
            agency_id=agency_id,
            owner_user_id=current_user.id,
            connection_id=message.connection_id,
            message_id=message.id,
            artifact_id=artifact.id if artifact else None,
            review_item_id=review.id,
            event_key=f"{review.id}:resolved:{review.revision}",
            event_type="review_decision",
            stage="info" if payload.action == "defer" else "success",
            actor_type="user",
            actor_user_id=current_user.id,
            summary_code=f"EMAIL_REVIEW_{payload.action.upper()}",
            details={"action": payload.action},
            ai_used=False,
            changed_entity_type="email_review",
            changed_entity_id=review.id,
            occurred_at=now,
            created_at=now,
        )
    )
    try:
        await AuditLogRepository(session).record(
            action=f"email_review_{payload.action}",
            entity_type="email_review",
            entity_id=str(review.id),
            agency_id=agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "review_type": review.review_type,
                "group_id": str(review.selected_group_id) if review.selected_group_id else None,
                "passenger_id": str(review.selected_passenger_id)
                if review.selected_passenger_id
                else None,
            },
        )
        await session.flush()
        await refresh_message_processing_state(session, message)
        if should_queue_retry:
            message.processing_status = "queued"
            message.processed_at = None
            message.updated_at = now
        await session.flush()
    except Exception:
        await session.rollback()
        if created_storage_keys:
            await MinioStorageRepository().delete_files(created_storage_keys)
        raise
    try:
        await session.commit()
    except Exception:
        # A failed COMMIT acknowledgement has an ambiguous outcome. Do not
        # delete objects that a successfully committed row may reference;
        # the email storage reconciler removes only proven orphans later.
        await session.rollback()
        raise
    if should_queue_retry:
        _enqueue_connection_sync(
            connection,
            provider_message_id=message.provider_message_id,
        )
    return EmailReviewActionResponse(
        review_id=review.id,
        status=review.status,
        message=result_message,
    )


@router.get("/activity", response_model=list[EmailActivityItemResponse])
async def email_activity(
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[EmailActivityItemResponse]:
    result = await session.execute(
        select(
            EmailMessageModel,
            EmailConnectionModel.email_address,
            ClientGroupModel.name,
        )
        .join(
            EmailConnectionModel,
            and_(
                EmailConnectionModel.id == EmailMessageModel.connection_id,
                EmailConnectionModel.owner_user_id == EmailMessageModel.owner_user_id,
            ),
        )
        .outerjoin(
            ClientGroupModel,
            and_(
                ClientGroupModel.id == EmailMessageModel.group_id,
                ClientGroupModel.agency_id == EmailMessageModel.agency_id,
                _group_role_visibility_filter(current_user),
            ),
        )
        .where(
            *_email_owner_filters(
                EmailMessageModel.owner_user_id,
                EmailMessageModel.agency_id,
                current_user,
            )
        )
        .order_by(EmailMessageModel.received_at.desc())
        .limit(200)
    )
    rows = result.all()
    message_ids = [message.id for message, _, _ in rows]
    counts: dict[uuid.UUID, dict[str, int]] = {
        message_id: {"retrieved": 0, "matched": 0, "failed": 0} for message_id in message_ids
    }
    if message_ids:
        artifact_counts = await session.execute(
            select(
                EmailArtifactModel.message_id,
                func.count(func.distinct(EmailArtifactModel.id)).filter(
                    EmailArtifactModel.retrieval_status == "retrieved"
                ),
                func.count(func.distinct(EmailArtifactDocumentModel.id)),
                func.count(func.distinct(EmailArtifactModel.id)).filter(
                    EmailArtifactModel.retrieval_status == "failed"
                ),
            )
            .outerjoin(
                EmailArtifactDocumentModel,
                EmailArtifactDocumentModel.artifact_id == EmailArtifactModel.id,
            )
            .where(
                EmailArtifactModel.message_id.in_(message_ids),
                EmailArtifactModel.owner_user_id == current_user.id,
                or_(
                    EmailArtifactDocumentModel.id.is_(None),
                    EmailArtifactDocumentModel.owner_user_id == current_user.id,
                ),
            )
            .group_by(EmailArtifactModel.message_id)
        )
        for message_id, retrieved, matched, failed in artifact_counts.all():
            counts[message_id] = {
                "retrieved": int(retrieved or 0),
                "matched": int(matched or 0),
                "failed": int(failed or 0),
            }
    return [
        EmailActivityItemResponse(
            message_id=message.id,
            connection_id=message.connection_id,
            account_email=account_email,
            sender_email=message.sender_address or "Unknown sender",
            subject=message.subject or "(No subject)",
            received_at=message.received_at,
            relevance_status=message.relevance_status,
            processing_status=message.processing_status,
            group_name=group_name,
            retrieved_count=counts[message.id]["retrieved"],
            matched_count=counts[message.id]["matched"],
            review_count=message.review_count,
            failure_count=counts[message.id]["failed"],
        )
        for message, account_email, group_name in rows
    ]


@router.get("/messages/{message_id}", response_model=EmailMessageDetailResponse)
async def email_message_detail(
    message_id: uuid.UUID,
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> EmailMessageDetailResponse:
    row = (
        await session.execute(
            select(
                EmailMessageModel,
                EmailConnectionModel.email_address,
                EmailConnectionModel.provider,
                ClientGroupModel.name,
            )
            .join(
                EmailConnectionModel,
                and_(
                    EmailConnectionModel.id == EmailMessageModel.connection_id,
                    EmailConnectionModel.owner_user_id == EmailMessageModel.owner_user_id,
                ),
            )
            .outerjoin(
                ClientGroupModel,
                and_(
                    ClientGroupModel.id == EmailMessageModel.group_id,
                    ClientGroupModel.agency_id == EmailMessageModel.agency_id,
                    _group_role_visibility_filter(current_user),
                ),
            )
            .where(
                EmailMessageModel.id == message_id,
                *_email_owner_filters(
                    EmailMessageModel.owner_user_id,
                    EmailMessageModel.agency_id,
                    current_user,
                ),
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email activity item was not found.",
        )
    message, account_email, provider, group_name = row
    artifacts = list(
        (
            await session.execute(
                select(EmailArtifactModel)
                .where(
                    EmailArtifactModel.message_id == message.id,
                    EmailArtifactModel.owner_user_id == current_user.id,
                )
                .order_by(EmailArtifactModel.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    events = list(
        (
            await session.execute(
                select(EmailActivityEventModel)
                .where(
                    EmailActivityEventModel.message_id == message.id,
                    EmailActivityEventModel.owner_user_id == current_user.id,
                )
                .order_by(EmailActivityEventModel.occurred_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return EmailMessageDetailResponse(
        id=message.id,
        connection_id=message.connection_id,
        account_email=account_email,
        sender_email=message.sender_address or "Unknown sender",
        sender_name=message.sender_name,
        recipients=[
            str(item.get("address", ""))
            for item in message.recipients_json
            if isinstance(item, dict) and item.get("address")
        ],
        subject=message.subject or "(No subject)",
        body_excerpt=message.body_excerpt or "",
        original_email_url=_original_email_url(
            provider=provider,
            account_email=account_email,
            provider_message_id=message.provider_message_id,
        ),
        received_at=message.received_at,
        relevance_status=message.relevance_status,
        relevance_confidence=float(message.relevance_confidence or 0.0),
        relevance_evidence=_string_list(message.evidence_json.get("signals", [])),
        processing_status=message.processing_status,
        group_id=message.group_id if group_name is not None else None,
        group_name=group_name,
        ai_used=message.ai_used,
        artifacts=[
            EmailArtifactDetailResponse(
                id=artifact.id,
                kind=artifact.kind,
                filename=artifact.filename,
                source_host=_artifact_source_host(artifact),
                verified_content_type=artifact.verified_content_type,
                byte_size=artifact.size_bytes,
                retrieval_status=artifact.retrieval_status,
                processing_status=artifact.processing_status,
                detected_type=artifact.detected_type,
                match_confidence=artifact.match_confidence,
                group_id=artifact.group_id,
                passenger_id=artifact.passenger_id,
                error_message=artifact.error_message,
            )
            for artifact in artifacts
        ],
        events=[
            EmailActivityEventResponse(
                id=event.id,
                event_type=event.event_type,
                status=event.stage,
                title=_event_title(event),
                detail=_event_detail(event),
                created_at=event.occurred_at,
            )
            for event in events
        ],
    )
