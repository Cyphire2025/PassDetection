"""Token, device-session, refresh, and principal support for mobile authentication."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, Request, status
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.mobile_jwt import MobileAccessClaims, MobilePrincipalType
from app.domain.entities.entities import GroupStatus, UserRole
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerProfileModel,
    GCGroupAccessModel,
    MobileDeviceSessionModel,
    MobilePassengerIdentityModel,
    MobilePassengerSessionIdentityModel,
    MobileRefreshTokenModel,
)
from app.infrastructure.database.models import (
    AttendanceRuntimeRegistrationModel,
    ClientGroupModel,
    PassportSubmissionModel,
    UserModel,
)
from app.presentation.api.v1.schemas.mobile_schemas import (
    MobileDeviceInput,
    MobilePrincipalResponse,
    MobileTokenResponse,
)
from app.presentation.dependencies.mobile_auth import (
    client_manager_profile_allows_password_session,
)


@dataclass(frozen=True, slots=True)
class MobileSessionIssueDependencies:
    """Route-owned callables that preserve established monkeypatch seams."""

    validate_passenger_session_identities: Callable[..., None]
    revoke_same_device_session: Callable[..., Awaitable[None]]
    create_refresh_token: Callable[[], tuple[str, datetime]]
    create_access_token: Callable[..., tuple[str, datetime]]
    create_offline_authorization_lease: Callable[..., str]
    hash_lookup: Callable[..., str]
    hash_refresh_token: Callable[[str], str]
    request_digest: Callable[[Request, str], str | None]


async def mobile_offline_lease_generations(
    session: AsyncSession,
    *,
    principal_type: MobilePrincipalType,
    principal: UserModel | MobilePassengerIdentityModel,
    access: GCGroupAccessModel | None,
) -> tuple[int | None, int | None]:
    """Return revocation-relevant generations that exist for this principal scope."""

    principal_generation: int | None = None
    if principal_type == "passenger":
        candidate_generation = getattr(principal, "claim_generation", None)
        if isinstance(candidate_generation, int) and candidate_generation >= 0:
            principal_generation = candidate_generation
    elif principal_type == "client_manager" and isinstance(principal, UserModel):
        principal_generation = (
            await session.execute(
                select(ClientManagerProfileModel.access_generation).where(
                    ClientManagerProfileModel.user_id == principal.id,
                    ClientManagerProfileModel.agency_id == principal.agency_id,
                    ClientManagerProfileModel.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

    candidate_access_generation = (
        getattr(access, "access_generation", None) if access is not None else None
    )
    access_generation = (
        candidate_access_generation
        if isinstance(candidate_access_generation, int) and candidate_access_generation >= 0
        else None
    )
    return principal_generation, access_generation


def _normalize_direct_password_client_manager(
    profile: ClientManagerProfileModel,
    *,
    now: datetime,
) -> None:
    """Repair the retired restricted-password state without opening invitations."""

    direct_password_invited = (
        profile.status == "invited"
        and profile.invitation_token_hash is None
        and profile.invitation_expires_at is None
    )
    if not direct_password_invited and not profile.force_password_change:
        return
    if direct_password_invited:
        profile.status = "active"
        profile.activated_at = profile.activated_at or now
        profile.suspended_at = None
    profile.force_password_change = False
    profile.access_generation += 1
    profile.revision += 1
    profile.updated_at = now


async def issue_mobile_session(
    session: AsyncSession,
    *,
    principal_id: uuid.UUID,
    principal_type: MobilePrincipalType,
    agency_id: uuid.UUID,
    display_name: str,
    device: MobileDeviceInput,
    request: Request,
    password_change_required: bool,
    dependencies: MobileSessionIssueDependencies,
    user: UserModel | None = None,
    passenger_identity: MobilePassengerIdentityModel | None = None,
    passenger_authorized_identities: list[MobilePassengerIdentityModel] | None = None,
    access: GCGroupAccessModel | None = None,
) -> MobileTokenResponse:
    now = datetime.now(tz=UTC)
    device_hash = dependencies.hash_lookup(device.installation_id, purpose="device-installation")
    authorized_identities = passenger_authorized_identities or (
        [passenger_identity] if passenger_identity is not None else []
    )
    if passenger_identity is not None:
        dependencies.validate_passenger_session_identities(
            selected_identity=passenger_identity,
            authorized_identities=authorized_identities,
        )
    await dependencies.revoke_same_device_session(
        session,
        agency_id=agency_id,
        user_id=user.id if user else None,
        passenger_identity_id=passenger_identity.id if passenger_identity else None,
        passenger_authorized_identity_ids=[item.id for item in authorized_identities],
        device_hash=device_hash,
        now=now,
    )
    raw_refresh, refresh_expires = dependencies.create_refresh_token()
    family_id = uuid.uuid4()
    device_session = MobileDeviceSessionModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        subject_role=principal_type,
        user_id=user.id if user else None,
        account_id=principal_id,
        passenger_identity_id=passenger_identity.id if passenger_identity else None,
        passenger_subject_hash=(
            dependencies.hash_lookup(
                f"{agency_id}:{passenger_identity.phone_lookup_hash}",
                purpose="passenger-subject",
            )
            if passenger_identity
            else None
        ),
        selected_gc_group_access_id=access.id if access else None,
        selected_group_id=access.group_id if access else None,
        device_identifier_hash=device_hash,
        platform=device.platform,
        app_version=device.app_version,
        device_label=device.device_name,
        status="active",
        session_generation=1,
        refresh_family_id=family_id,
        created_ip_hash=dependencies.request_digest(request, "ip"),
        last_ip_hash=dependencies.request_digest(request, "ip"),
        last_seen_at=now,
        expires_at=refresh_expires,
        created_at=now,
        updated_at=now,
    )
    refresh_model = MobileRefreshTokenModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        session_id=device_session.id,
        family_id=family_id,
        token_hash=dependencies.hash_refresh_token(raw_refresh),
        token_generation=1,
        issued_at=now,
        expires_at=refresh_expires,
    )
    session_identities = [
        MobilePassengerSessionIdentityModel(
            session_id=device_session.id,
            passenger_identity_id=item.id,
            agency_id=item.agency_id,
            group_id=item.group_id,
            gc_group_access_id=item.gc_group_access_id,
            identity_claim_generation=item.claim_generation,
            authorized_at=now,
        )
        for item in authorized_identities
    ]
    session.add_all([device_session, refresh_model, *session_identities])
    await session.flush()
    access_token, access_expires = dependencies.create_access_token(
        principal_id=principal_id,
        account_id=device_session.account_id,
        principal_type=principal_type,
        agency_id=agency_id,
        session_id=device_session.id,
        session_generation=device_session.session_generation,
        password_change_required=password_change_required,
    )
    lease_principal: UserModel | MobilePassengerIdentityModel
    if passenger_identity is not None:
        lease_principal = passenger_identity
    elif user is not None:
        lease_principal = user
    else:
        raise ValueError("Mobile session issuance is missing its principal")
    principal_generation, access_generation = await mobile_offline_lease_generations(
        session,
        principal_type=principal_type,
        principal=lease_principal,
        access=access,
    )
    offline_authorization_lease = dependencies.create_offline_authorization_lease(
        principal_id=principal_id,
        account_id=device_session.account_id,
        principal_type=principal_type,
        agency_id=agency_id,
        passenger_id=(
            passenger_identity.passenger_submission_id if passenger_identity is not None else None
        ),
        session_id=device_session.id,
        session_generation=device_session.session_generation,
        installation_id=device.installation_id,
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
            id=principal_id,
            account_id=device_session.account_id,
            principal_type=principal_type,
            agency_id=agency_id,
            passenger_id=(
                passenger_identity.passenger_submission_id
                if passenger_identity is not None
                else None
            ),
            display_name=display_name,
            force_password_change=password_change_required,
        ),
    )


async def _revoke_session_family(
    session: AsyncSession,
    device_session: MobileDeviceSessionModel,
    *,
    reason: str,
    now: datetime,
) -> None:
    device_session.status = "revoked"
    device_session.session_generation += 1
    device_session.revoked_at = now
    device_session.revoke_reason = reason
    device_session.updated_at = now
    await session.execute(
        update(MobileRefreshTokenModel)
        .where(
            MobileRefreshTokenModel.session_id == device_session.id,
            MobileRefreshTokenModel.family_id == device_session.refresh_family_id,
            MobileRefreshTokenModel.revoked_at.is_(None),
        )
        .values(revoked_at=now, revoke_reason=reason)
    )
    await session.execute(
        update(AttendanceRuntimeRegistrationModel)
        .where(
            AttendanceRuntimeRegistrationModel.native_mobile_session_id
            == device_session.id,
            AttendanceRuntimeRegistrationModel.agency_id == device_session.agency_id,
            AttendanceRuntimeRegistrationModel.status == "active",
        )
        .values(
            status=("replaced" if reason == "session_replaced" else "revoked"),
            revoked_at=now,
            revoke_reason=reason[:80],
            updated_at=now,
        )
    )


async def _refresh_principal(
    session: AsyncSession,
    device_session: MobileDeviceSessionModel,
) -> tuple[
    UserModel | MobilePassengerIdentityModel,
    str,
    bool,
    GCGroupAccessModel | None,
]:
    if device_session.subject_role == "passenger":
        now = datetime.now(tz=UTC)
        rows = list(
            (
                await session.execute(
                    select(MobilePassengerIdentityModel, GCGroupAccessModel)
                    .join(
                        MobilePassengerSessionIdentityModel,
                        MobilePassengerSessionIdentityModel.passenger_identity_id
                        == MobilePassengerIdentityModel.id,
                    )
                    .join(
                        GCGroupAccessModel,
                        and_(
                            GCGroupAccessModel.id
                            == MobilePassengerSessionIdentityModel.gc_group_access_id,
                            GCGroupAccessModel.agency_id
                            == MobilePassengerSessionIdentityModel.agency_id,
                            GCGroupAccessModel.group_id
                            == MobilePassengerSessionIdentityModel.group_id,
                        ),
                    )
                    .join(
                        ClientGroupModel,
                        and_(
                            ClientGroupModel.id == MobilePassengerSessionIdentityModel.group_id,
                            ClientGroupModel.agency_id
                            == MobilePassengerSessionIdentityModel.agency_id,
                        ),
                    )
                    .where(
                        MobilePassengerSessionIdentityModel.session_id == device_session.id,
                        MobilePassengerSessionIdentityModel.agency_id == device_session.agency_id,
                        MobilePassengerSessionIdentityModel.passenger_identity_id
                        == device_session.passenger_identity_id,
                        MobilePassengerSessionIdentityModel.gc_group_access_id
                        == device_session.selected_gc_group_access_id,
                        MobilePassengerSessionIdentityModel.group_id
                        == device_session.selected_group_id,
                        MobilePassengerIdentityModel.id == device_session.passenger_identity_id,
                        MobilePassengerIdentityModel.agency_id == device_session.agency_id,
                        MobilePassengerIdentityModel.gc_group_access_id
                        == MobilePassengerSessionIdentityModel.gc_group_access_id,
                        MobilePassengerIdentityModel.group_id
                        == MobilePassengerSessionIdentityModel.group_id,
                        MobilePassengerIdentityModel.claim_generation
                        == MobilePassengerSessionIdentityModel.identity_claim_generation,
                        MobilePassengerIdentityModel.status == "claimed",
                        MobilePassengerIdentityModel.revoked_at.is_(None),
                        GCGroupAccessModel.id == device_session.selected_gc_group_access_id,
                        GCGroupAccessModel.agency_id == device_session.agency_id,
                        GCGroupAccessModel.group_id == device_session.selected_group_id,
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
                        ClientGroupModel.status.in_(
                            (GroupStatus.ACTIVE.value, GroupStatus.CLOSED.value)
                        ),
                        ClientGroupModel.deleted_at.is_(None),
                    )
                    .limit(2)
                    .with_for_update()
                )
            ).all()
        )
        if len(rows) != 1:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Mobile identity is inactive"
            )
        identity, access = rows[0]
        name = (
            await session.execute(
                select(PassportSubmissionModel.client_name).where(
                    PassportSubmissionModel.id == identity.passenger_submission_id,
                    PassportSubmissionModel.agency_id == identity.agency_id,
                    PassportSubmissionModel.group_id == identity.group_id,
                )
            )
        ).scalar_one()
        return identity, name, False, access

    expected_role = (
        UserRole.CLIENT_MANAGER.value
        if device_session.subject_role == "client_manager"
        else UserRole.AGENCY_COORDINATOR.value
    )
    user = (
        await session.execute(
            select(UserModel).where(
                UserModel.id == device_session.user_id,
                UserModel.agency_id == device_session.agency_id,
                UserModel.role == expected_role,
                UserModel.is_active.is_(True),
                UserModel.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Mobile account is inactive"
        )
    if device_session.subject_role == "client_manager":
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
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Mobile account is inactive"
            )
        _normalize_direct_password_client_manager(
            profile,
            now=datetime.now(tz=UTC),
        )
    return user, user.full_name, False, None


async def _principal_display_name(session: AsyncSession, claims: MobileAccessClaims) -> str:
    name, _email, _phone_number, _passenger_id = await _principal_profile(session, claims)
    return name


async def _principal_profile(
    session: AsyncSession,
    claims: MobileAccessClaims,
) -> tuple[str, str | None, str | None, uuid.UUID | None]:
    principal: tuple[str, str | None, str | None, uuid.UUID | None] | None
    if claims.principal_type == "passenger":
        passenger = (
            await session.execute(
                select(
                    PassportSubmissionModel.client_name,
                    PassportSubmissionModel.client_email,
                    MobilePassengerIdentityModel.normalized_phone_number,
                    MobilePassengerIdentityModel.passenger_submission_id,
                )
                .join(
                    MobilePassengerIdentityModel,
                    MobilePassengerIdentityModel.passenger_submission_id
                    == PassportSubmissionModel.id,
                )
                .where(
                    MobilePassengerIdentityModel.id == claims.principal_id,
                    MobilePassengerIdentityModel.agency_id == claims.agency_id,
                )
            )
        ).first()
        principal = (
            (
                str(passenger[0]),
                str(passenger[1]) if passenger[1] else None,
                str(passenger[2]) if passenger[2] else None,
                passenger[3],
            )
            if passenger is not None and passenger[0]
            else None
        )
    else:
        user = (
            await session.execute(
                select(UserModel.full_name, UserModel.email).where(
                    UserModel.id == claims.principal_id,
                    UserModel.agency_id == claims.agency_id,
                )
            )
        ).first()
        if user is None:
            principal = None
        else:
            phone_number = None
            if claims.principal_type == "client_manager":
                phone_number = (
                    await session.execute(
                        select(ClientManagerProfileModel.normalized_phone_number).where(
                            ClientManagerProfileModel.user_id == claims.principal_id,
                            ClientManagerProfileModel.agency_id == claims.agency_id,
                            ClientManagerProfileModel.deleted_at.is_(None),
                        )
                    )
                ).scalar_one_or_none()
            principal = (
                (
                    str(user[0]),
                    str(user[1]) if user[1] else None,
                    str(phone_number) if phone_number else None,
                    None,
                )
                if user[0]
                else None
            )
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Mobile principal is inactive"
        )
    return principal
