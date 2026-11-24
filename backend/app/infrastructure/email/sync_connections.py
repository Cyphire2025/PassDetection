"""Durable email synchronization: connections."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.application.interfaces.email_provider import (
    EmailProvider,
    EmailProviderAuthenticationError,
    EmailProviderResponseError,
)
from app.core.config.settings import Settings
from app.domain.entities.entities import UserRole
from app.infrastructure.database.email_models import EmailConnectionModel
from app.infrastructure.database.models import UserModel
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.email.gmail_provider import GmailEmailProvider
from app.infrastructure.email.outlook_provider import OutlookEmailProvider
from app.infrastructure.email.token_encryption import EmailTokenCipher, EncryptedToken

from .sync_contracts import SyncClaim, _connection_claim_filters


def provider_for_connection(
    connection: EmailConnectionModel | SyncClaim,
    *,
    settings: Settings | None = None,
) -> EmailProvider:
    if connection.provider == "gmail":
        return GmailEmailProvider(settings=settings)
    if connection.provider == "outlook":
        return OutlookEmailProvider(settings=settings)
    raise EmailProviderResponseError(
        "The connected email provider is not supported",
        code="EMAIL_PROVIDER_UNSUPPORTED",
    )


async def _claim_connection(
    session: AsyncSession,
    connection_id: uuid.UUID,
    *,
    agency_id: uuid.UUID,
    owner_user_id: uuid.UUID,
    provider_account_id: str,
    sync_generation: int,
    settings: Settings,
) -> SyncClaim | None:
    now = datetime.now(tz=UTC)
    result = await session.execute(
        select(EmailConnectionModel)
        .join(
            UserModel,
            UserModel.id == EmailConnectionModel.owner_user_id,
        )
        .options(
            undefer(EmailConnectionModel.access_token_ciphertext),
            undefer(EmailConnectionModel.refresh_token_ciphertext),
        )
        .where(
            EmailConnectionModel.id == connection_id,
            EmailConnectionModel.agency_id == agency_id,
            EmailConnectionModel.owner_user_id == owner_user_id,
            EmailConnectionModel.provider_account_id == provider_account_id,
            EmailConnectionModel.sync_generation == sync_generation,
            UserModel.is_active.is_(True),
            UserModel.role.in_(
                {
                    UserRole.SUPER_ADMIN.value,
                    UserRole.AGENCY_ADMIN.value,
                    UserRole.AGENCY_MANAGER.value,
                    UserRole.AGENCY_STAFF.value,
                }
            ),
            or_(
                UserModel.role == UserRole.SUPER_ADMIN.value,
                UserModel.agency_id == EmailConnectionModel.agency_id,
            ),
        )
        .with_for_update(skip_locked=True)
    )
    connection = result.scalar_one_or_none()
    if (
        connection is None
        or connection.status not in {"active", "failing"}
        or (connection.sync_lease_expires_at is not None and connection.sync_lease_expires_at > now)
        or not connection.access_token_ciphertext
    ):
        await session.rollback()
        return None

    cipher = EmailTokenCipher.from_settings(settings)
    access_token = cipher.decrypt(
        EncryptedToken(
            ciphertext=connection.access_token_ciphertext.decode("ascii"),
            key_version=connection.token_key_version,
        )
    )
    refresh_token = (
        cipher.decrypt(
            EncryptedToken(
                ciphertext=connection.refresh_token_ciphertext.decode("ascii"),
                key_version=connection.token_key_version,
            )
        )
        if connection.refresh_token_ciphertext
        else None
    )
    if connection.token_key_version != cipher.key_version:
        encrypted_access = cipher.encrypt(access_token)
        connection.access_token_ciphertext = encrypted_access.ciphertext.encode("ascii")
        if refresh_token is not None:
            encrypted_refresh = cipher.encrypt(refresh_token)
            connection.refresh_token_ciphertext = encrypted_refresh.ciphertext.encode("ascii")
        connection.token_key_version = cipher.key_version
    lease_token = uuid.uuid4().hex
    connection.sync_lease_token = lease_token
    connection.sync_lease_expires_at = now + timedelta(seconds=settings.email_sync_lease_seconds)
    connection.sync_state = "running"
    connection.last_sync_attempt_at = now
    connection.last_error_code = None
    connection.last_error_message = None
    await session.commit()
    return SyncClaim(
        connection_id=connection.id,
        agency_id=connection.agency_id,
        owner_user_id=connection.owner_user_id,
        provider=connection.provider,
        provider_account_id=connection.provider_account_id,
        lease_token=lease_token,
        generation=connection.sync_generation,
        access_token=access_token,
        refresh_token=refresh_token,
        token_expires_at=connection.token_expires_at,
        sync_cursor=connection.sync_cursor,
    )


async def _fresh_access_token(
    claim: SyncClaim,
    *,
    provider: EmailProvider,
    settings: Settings,
) -> tuple[str, str | None, datetime | None]:
    now = datetime.now(tz=UTC)
    expires_at = claim.token_expires_at
    if expires_at is None or expires_at > now + timedelta(seconds=90):
        return claim.access_token, claim.refresh_token, expires_at
    if not claim.refresh_token:
        raise EmailProviderAuthenticationError(
            "The email connection must be reauthorized",
            code="EMAIL_PROVIDER_REFRESH_TOKEN_MISSING",
        )

    token_set = await provider.refresh_access_token(
        refresh_token=claim.refresh_token,
    )
    refresh_token = token_set.refresh_token or claim.refresh_token
    cipher = EmailTokenCipher.from_settings(settings)
    encrypted_access = cipher.encrypt(token_set.access_token)
    encrypted_refresh = cipher.encrypt(refresh_token)
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(EmailConnectionModel)
            .where(
                *_connection_claim_filters(claim),
                EmailConnectionModel.sync_lease_token == claim.lease_token,
            )
            .with_for_update()
        )
        connection = result.scalar_one_or_none()
        if connection is None:
            raise EmailProviderResponseError(
                "The email connection changed while synchronization was running",
                code="EMAIL_CONNECTION_CHANGED",
            )
        connection.access_token_ciphertext = encrypted_access.ciphertext.encode("ascii")
        connection.refresh_token_ciphertext = encrypted_refresh.ciphertext.encode("ascii")
        connection.token_key_version = cipher.key_version
        connection.token_expires_at = token_set.expires_at
        if token_set.scopes:
            connection.scopes = list(token_set.scopes)
        await session.commit()
    return token_set.access_token, refresh_token, token_set.expires_at


async def _renew_connection_lease(
    claim: SyncClaim,
    *,
    settings: Settings,
) -> bool:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(EmailConnectionModel)
            .where(
                *_connection_claim_filters(claim),
                EmailConnectionModel.sync_lease_token == claim.lease_token,
                EmailConnectionModel.status.in_({"active", "failing"}),
            )
            .with_for_update()
        )
        connection = result.scalar_one_or_none()
        if connection is None:
            await session.rollback()
            return False
        connection.sync_lease_expires_at = datetime.now(tz=UTC) + timedelta(
            seconds=settings.email_sync_lease_seconds
        )
        await session.commit()
        return True


async def _finish_connection(
    session: AsyncSession,
    *,
    claim: SyncClaim,
    cursor: str | None,
    settings: Settings,
) -> None:
    result = await session.execute(
        select(EmailConnectionModel)
        .where(
            *_connection_claim_filters(claim),
            EmailConnectionModel.sync_lease_token == claim.lease_token,
        )
        .with_for_update()
    )
    connection = result.scalar_one_or_none()
    if connection is None:
        return
    now = datetime.now(tz=UTC)
    connection.sync_cursor = cursor
    connection.status = "active"
    connection.sync_state = "idle"
    connection.sync_lease_token = None
    connection.sync_lease_expires_at = None
    connection.last_successful_sync_at = now
    connection.last_sync_completed_at = now
    connection.next_sync_at = now + timedelta(seconds=settings.email_sync_interval_seconds)
    connection.consecutive_failures = 0
    connection.last_error_code = None
    connection.last_error_message = None
    connection.last_error_at = None
    connection.updated_at = now


async def _record_connection_failure(
    claim: SyncClaim,
    *,
    code: str,
    message: str,
    reconnect_required: bool,
    retry_after_seconds: int | None,
    settings: Settings,
) -> None:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(EmailConnectionModel)
            .where(
                *_connection_claim_filters(claim),
                EmailConnectionModel.sync_lease_token == claim.lease_token,
            )
            .with_for_update()
        )
        connection = result.scalar_one_or_none()
        if connection is None:
            return
        now = datetime.now(tz=UTC)
        connection.consecutive_failures += 1
        connection.status = "expired" if reconnect_required else "failing"
        connection.sync_state = "blocked" if reconnect_required else "retry_wait"
        connection.sync_lease_token = None
        connection.sync_lease_expires_at = None
        connection.last_error_code = code[:80]
        connection.last_error_message = message[:1_000]
        connection.last_error_at = now
        backoff = retry_after_seconds or min(
            settings.email_sync_interval_seconds * (2 ** min(connection.consecutive_failures, 6)),
            86_400,
        )
        connection.next_sync_at = None if reconnect_required else now + timedelta(seconds=backoff)
        connection.updated_at = now
        await session.commit()


async def _record_connection_start_failure(
    connection_id: uuid.UUID,
    *,
    agency_id: uuid.UUID,
    owner_user_id: uuid.UUID,
    provider_account_id: str,
    sync_generation: int,
    code: str,
    message: str,
) -> None:
    async with AsyncSessionFactory() as session:
        connection = await session.scalar(
            select(EmailConnectionModel)
            .where(
                EmailConnectionModel.id == connection_id,
                EmailConnectionModel.agency_id == agency_id,
                EmailConnectionModel.owner_user_id == owner_user_id,
                EmailConnectionModel.provider_account_id == provider_account_id,
                EmailConnectionModel.sync_generation == sync_generation,
            )
            .with_for_update()
        )
        if connection is None or connection.status in {
            "paused",
            "disconnecting",
            "disconnected",
        }:
            return
        now = datetime.now(tz=UTC)
        connection.status = "expired"
        connection.sync_state = "blocked"
        connection.sync_lease_token = None
        connection.sync_lease_expires_at = None
        connection.next_sync_at = None
        connection.consecutive_failures += 1
        connection.last_error_code = code[:80]
        connection.last_error_message = message[:1_000]
        connection.last_error_at = now
        connection.updated_at = now
        await session.commit()
