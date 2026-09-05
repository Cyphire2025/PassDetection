"""Bind mailbox authorization to the initiating browser and account generation."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass

from fastapi import Request, Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import Settings
from app.domain.entities.entities import UserRole
from app.infrastructure.database.email_models import EmailOAuthStateModel
from app.infrastructure.database.models import AgencyModel, UserModel
from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository


def oauth_cookie_name(provider: str) -> str:
    return f"email_oauth_{provider}"


def oauth_cookie_path(provider: str) -> str:
    return f"/api/v1/email-integrations/oauth/{provider}"


def _binding_digest(nonce: str, user_id: uuid.UUID, generation: int) -> str:
    return hashlib.sha256(f"{nonce}:{user_id}:{generation}".encode("ascii")).hexdigest()


def start_oauth_browser_binding(
    response: Response,
    *,
    provider: str,
    user_id: uuid.UUID,
    session_version: int,
    settings: Settings,
) -> str:
    nonce = secrets.token_urlsafe(32)
    response.set_cookie(
        oauth_cookie_name(provider),
        nonce,
        max_age=settings.email_oauth_state_ttl_seconds,
        httponly=True,
        secure=settings.jwt.cookie_secure or settings.is_production,
        # Provider callbacks are top-level cross-site GET navigations.
        samesite="lax",
        path=oauth_cookie_path(provider),
    )
    return _binding_digest(nonce, user_id, session_version)


async def verify_oauth_browser_binding(
    request: Request,
    state: EmailOAuthStateModel | OAuthBindingSnapshot,
    session: AsyncSession,
    *,
    lock_security: bool = False,
) -> bool:
    nonce = request.cookies.get(oauth_cookie_name(state.provider), "")
    if len(nonce) != 43 or not nonce.isascii() or not state.nonce_hash:
        return False
    security = await IdentitySecurityRepository(session).get_state(
        state.user_id, lock=lock_security
    )
    if security is None or security.credential_state != "active":
        return False
    # A short-lived nonce authenticates this browser independently of the
    # access cookie's lifetime. Logout-all/password/MFA fencing invalidates it.
    # Ordinary access expiry during provider consent therefore remains safe.
    expected = _binding_digest(nonce, state.user_id, security.session_version)
    return hmac.compare_digest(expected, state.nonce_hash)


@dataclass(frozen=True, slots=True)
class OAuthBindingSnapshot:
    """Retain immutable authorization evidence across the provider exchange."""

    provider: str
    user_id: uuid.UUID
    nonce_hash: str | None


async def revalidate_oauth_actor_for_persistence(
    request: Request,
    binding: OAuthBindingSnapshot,
    *,
    agency_id: uuid.UUID,
    session: AsyncSession,
) -> bool:
    """Fence slow provider responses with short account/security row locks.

    Consent may take long enough for logout-all, a password reset, role change,
    or account disable to complete. Check again immediately before storing any
    mailbox grant, in the same transaction that persists the connection.
    """
    actor = await session.scalar(
        select(UserModel.id)
        .outerjoin(AgencyModel, AgencyModel.id == UserModel.agency_id)
        .where(
            UserModel.id == binding.user_id,
            UserModel.is_active.is_(True),
            UserModel.deleted_at.is_(None),
            or_(
                UserModel.role == UserRole.SUPER_ADMIN.value,
                (UserModel.agency_id == agency_id)
                & UserModel.role.in_(
                    {
                        UserRole.AGENCY_ADMIN.value,
                        UserRole.AGENCY_MANAGER.value,
                        UserRole.AGENCY_STAFF.value,
                    }
                )
                & AgencyModel.is_active.is_(True),
            ),
        )
        .with_for_update(of=UserModel)
    )
    return actor is not None and await verify_oauth_browser_binding(
        request, binding, session, lock_security=True
    )


def clear_oauth_browser_bindings(response: Response, settings: Settings) -> None:
    for provider in ("gmail", "outlook"):
        response.delete_cookie(
            oauth_cookie_name(provider),
            path=oauth_cookie_path(provider),
            httponly=True,
            secure=settings.jwt.cookie_secure or settings.is_production,
            samesite="lax",
        )
