"""Bearer-only authentication dependencies for the GC mobile API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.mobile_jwt import MobileAccessClaims, decode_mobile_access_token
from app.domain.entities.entities import UserRole
from app.domain.exceptions.exceptions import AuthenticationError, AuthorizationError
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerProfileModel,
    MobileDeviceSessionModel,
    MobilePassengerIdentityModel,
    MobilePassengerSessionIdentityModel,
)
from app.infrastructure.database.models import UserModel
from app.infrastructure.database.session import get_db_session

_mobile_bearer = HTTPBearer(auto_error=False)


def client_manager_profile_allows_password_session(
    profile: ClientManagerProfileModel,
) -> bool:
    """Keep invitation redemption separate from temporary-password login.

    Invitation accounts carry a one-time activation token and must use the
    activation endpoint. Legacy/temporary-password accounts can also be in the
    ``invited`` state, but are distinguishable because they have no invitation
    token pair and must enter the restricted password-change flow.
    """

    if profile.status == "active":
        return True
    return (
        profile.status == "invited"
        and profile.invitation_token_hash is None
        and profile.invitation_expires_at is None
    )


async def get_current_mobile_claims(
    credentials: HTTPAuthorizationCredentials | None = Depends(_mobile_bearer),
    session: AsyncSession = Depends(get_db_session),
) -> MobileAccessClaims:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("Mobile bearer token is required")
    claims = decode_mobile_access_token(credentials.credentials)
    now = datetime.now(tz=UTC)
    result = await session.execute(
        select(MobileDeviceSessionModel)
        .where(
            MobileDeviceSessionModel.id == claims.session_id,
            MobileDeviceSessionModel.agency_id == claims.agency_id,
            MobileDeviceSessionModel.subject_role == claims.principal_type,
            MobileDeviceSessionModel.status == "active",
            MobileDeviceSessionModel.session_generation == claims.session_generation,
            MobileDeviceSessionModel.revoked_at.is_(None),
            MobileDeviceSessionModel.expires_at > now,
        )
        .limit(1)
    )
    device_session = result.scalar_one_or_none()
    if device_session is None:
        raise AuthenticationError("Mobile session is no longer active")
    if device_session.account_id != claims.account_id:
        raise AuthenticationError("Mobile session account mismatch")

    if claims.principal_type == "passenger":
        if device_session.passenger_identity_id != claims.principal_id:
            raise AuthenticationError("Mobile session subject mismatch")
        identity = (
            await session.execute(
                select(MobilePassengerIdentityModel.id)
                .join(
                    MobilePassengerSessionIdentityModel,
                    MobilePassengerSessionIdentityModel.passenger_identity_id
                    == MobilePassengerIdentityModel.id,
                )
                .where(
                    MobilePassengerSessionIdentityModel.session_id == claims.session_id,
                    MobilePassengerSessionIdentityModel.agency_id == claims.agency_id,
                    MobilePassengerSessionIdentityModel.passenger_identity_id
                    == claims.principal_id,
                    MobilePassengerSessionIdentityModel.gc_group_access_id
                    == device_session.selected_gc_group_access_id,
                    MobilePassengerSessionIdentityModel.group_id
                    == device_session.selected_group_id,
                    MobilePassengerIdentityModel.id == claims.principal_id,
                    MobilePassengerIdentityModel.agency_id == claims.agency_id,
                    MobilePassengerIdentityModel.gc_group_access_id
                    == MobilePassengerSessionIdentityModel.gc_group_access_id,
                    MobilePassengerIdentityModel.group_id
                    == MobilePassengerSessionIdentityModel.group_id,
                    MobilePassengerIdentityModel.claim_generation
                    == MobilePassengerSessionIdentityModel.identity_claim_generation,
                    MobilePassengerIdentityModel.status.in_(("eligible", "claimed")),
                    MobilePassengerIdentityModel.revoked_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if identity is None:
            raise AuthenticationError("Mobile passenger identity is inactive")
    else:
        expected_role = (
            UserRole.CLIENT_MANAGER.value
            if claims.principal_type == "client_manager"
            else UserRole.AGENCY_COORDINATOR.value
        )
        if device_session.user_id != claims.principal_id:
            raise AuthenticationError("Mobile session subject mismatch")
        user = (
            await session.execute(
                select(UserModel).where(
                    UserModel.id == claims.principal_id,
                    UserModel.agency_id == claims.agency_id,
                    UserModel.role == expected_role,
                    UserModel.is_active.is_(True),
                    UserModel.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if user is None:
            raise AuthenticationError("Mobile account is inactive")
        if claims.principal_type == "client_manager":
            profile = (
                await session.execute(
                    select(ClientManagerProfileModel).where(
                        ClientManagerProfileModel.user_id == claims.principal_id,
                        ClientManagerProfileModel.agency_id == claims.agency_id,
                        ClientManagerProfileModel.status.in_(("invited", "active")),
                        ClientManagerProfileModel.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if profile is None or not client_manager_profile_allows_password_session(profile):
                raise AuthenticationError("Client Manager profile is inactive")
            if profile.force_password_change and not claims.password_change_required:
                raise AuthenticationError("Password change is required")

    # Bound write amplification: refresh activity at most once every five minutes.
    if device_session.last_seen_at is None or device_session.last_seen_at <= now - timedelta(minutes=5):
        device_session.last_seen_at = now
    return claims


async def require_unrestricted_mobile_claims(
    claims: MobileAccessClaims = Depends(get_current_mobile_claims),
) -> MobileAccessClaims:
    if claims.password_change_required:
        raise AuthorizationError("Password change is required before using the mobile app")
    return claims
