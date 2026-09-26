"""Personal mailbox scope, row locks and provider dispatch shared by email routes."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, undefer
from sqlalchemy.sql.elements import ColumnElement

from app.application.interfaces.email_provider import EmailProvider
from app.application.security.authorization_policy import AuthorizationPolicy
from app.core.config.settings import Settings
from app.core.logging.logger import get_logger
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.email_models import EmailConnectionModel
from app.infrastructure.database.models import AgencyModel
from app.infrastructure.email.gmail_provider import GmailEmailProvider
from app.infrastructure.email.outlook_provider import OutlookEmailProvider
from app.presentation.dependencies.auth import require_role

logger = get_logger(__name__)

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
