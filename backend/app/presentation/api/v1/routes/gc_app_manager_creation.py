"""One-time client-manager invitation creation and durable publication."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.contact_normalization import normalize_whatsapp_phone
from app.core.security.mobile_jwt import hash_mobile_lookup
from app.core.security.password import hash_password, run_password_work
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerGroupAssignmentModel,
    ClientManagerProfileModel,
)
from app.infrastructure.database.models import (
    UserModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.gc_app_manager_support import (
    _manager_group_map,
    _validate_manager_groups,
)
from app.presentation.api.v1.routes.gc_app_scope import (
    GC_ADMIN_ROLES,
    _audit,
    _client_manager_duplicate_message,
    _client_manager_response,
    _get_organization,
    _tenant_id,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ClientManagerCreateRequest,
    ClientManagerResponse,
)
from app.presentation.dependencies.auth import require_recent_mfa, require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.post(
    "/client-managers",
    response_model=ClientManagerResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def create_client_manager(
    body: ClientManagerCreateRequest,
    request: Request,
    http_response: Response,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> ClientManagerResponse:
    tenant_id = _tenant_id(current_user, agency_id)
    organization = await _get_organization(session, tenant_id, body.organization_id, lock=True)
    normalized_phone = normalize_whatsapp_phone(body.phone_number)
    if normalized_phone is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Phone number is not valid for WhatsApp/mobile matching",
        )
    email = str(body.email).lower().strip()
    email_exists, phone_exists = (
        await session.execute(
            select(
                exists().where(UserModel.email == email),
                exists().where(
                    ClientManagerProfileModel.agency_id == tenant_id,
                    ClientManagerProfileModel.normalized_phone_number == normalized_phone,
                    ClientManagerProfileModel.deleted_at.is_(None),
                ),
            )
        )
    ).one()
    if email_exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already in use")
    if phone_exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Mobile number is already assigned to another Client Manager",
        )

    access_by_group = await _validate_manager_groups(
        session, tenant_id, organization.id, body.group_ids
    )
    temporary_password = f"Gc1{secrets.token_urlsafe(32)}"
    activation_token = secrets.token_urlsafe(32)
    initial_status = "invited"
    try:
        password_hash = await run_password_work(hash_password, temporary_password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    now = datetime.now(tz=UTC)
    user = UserModel(
        id=uuid.uuid4(),
        email=email,
        hashed_password=password_hash,
        full_name=" ".join(body.full_name.split()),
        role=UserRole.CLIENT_MANAGER.value,
        agency_id=tenant_id,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    profile = ClientManagerProfileModel(
        id=uuid.uuid4(),
        agency_id=tenant_id,
        user_id=user.id,
        organization_id=organization.id,
        normalized_phone_number=normalized_phone,
        status=initial_status,
        force_password_change=False,
        invitation_token_hash=(
            hash_mobile_lookup(activation_token, purpose="manager-invitation")
            if activation_token
            else None
        ),
        invitation_expires_at=now + timedelta(days=7) if activation_token else None,
        activated_at=None,
        access_generation=1,
        revision=1,
        created_by_user_id=current_user.id,
        updated_by_user_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    # These models intentionally do not expose broad ORM relationships. Flush
    # each dependency explicitly so PostgreSQL never receives the profile
    # before its newly-created credential row.
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        # The explicit checks above provide precise normal-case feedback. The
        # database constraints remain the race-safe authority when concurrent
        # requests attempt the same email or phone number.
        await session.rollback()
        duplicate_message = _client_manager_duplicate_message(exc)
        if duplicate_message is None:
            raise
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=duplicate_message,
        ) from exc
    session.add(profile)
    try:
        await session.flush()
    except IntegrityError as exc:
        # Keep the user/profile write atomic. A live-phone collision can still
        # happen here when two creates race after the explicit preflight check.
        await session.rollback()
        duplicate_message = _client_manager_duplicate_message(exc)
        if duplicate_message is None:
            raise
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=duplicate_message,
        ) from exc
    for group_id, access in access_by_group.items():
        session.add(
            ClientManagerGroupAssignmentModel(
                id=uuid.uuid4(),
                agency_id=tenant_id,
                organization_id=organization.id,
                group_id=group_id,
                profile_id=profile.id,
                gc_group_access_id=access.id,
                is_active=True,
                can_view_passenger_names=False,
                personal_document_access_enabled=False,
                assigned_by_user_id=current_user.id,
                assigned_at=now,
                updated_at=now,
            )
        )
    if access_by_group:
        try:
            await session.flush()
        except IntegrityError:
            # Group-assignment failures are not account-identity duplicates.
            # Keep the operation atomic and preserve the database error for logs.
            await session.rollback()
            raise
    await _audit(
        session,
        current_user,
        request,
        agency_id=tenant_id,
        action="gc_app.client_manager_created",
        entity_type="client_manager_profile",
        entity_id=profile.id,
        metadata={"group_count": len(access_by_group)},
    )
    assigned_groups = (await _manager_group_map(session, [profile.id])).get(profile.id, [])
    response = _client_manager_response(profile, user, organization, assigned_groups)
    response.activation_token = activation_token
    http_response.headers["Cache-Control"] = "private, no-store, max-age=0"
    http_response.headers["Pragma"] = "no-cache"
    await session.commit()
    return response
