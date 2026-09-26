"""Qr for tour operations; preserve tenant, lock and transaction boundaries."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.models import PassengerQRTokenModel
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.tour_operations_qr_helpers import (
    get_qr_passenger as _get_qr_passenger,
)
from app.presentation.api.v1.routes.tour_operations_qr_helpers import (
    group_passenger_qr_codes as _group_passenger_qr_codes,
)
from app.presentation.api.v1.routes.tour_operations_qr_helpers import (
    issue_passenger_qr as _issue_passenger_qr,
)
from app.presentation.api.v1.routes.tour_operations_qr_helpers import (
    latest_passenger_qr as _latest_passenger_qr,
)
from app.presentation.api.v1.routes.tour_operations_qr_helpers import (
    qr_token_response as _qr_token_response,
)
from app.presentation.api.v1.routes.tour_operations_qr_helpers import (
    record_qr_audit as _record_qr_audit,
)
from app.presentation.api.v1.schemas.tour_operations_schemas import (
    GroupPassengerQrCodesResponse,
    PassengerQrTokenResponse,
    SetPassengerQrActiveRequest,
    SetPassengerQrExpirationRequest,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

from .tour_operations_access import (
    COORDINATOR_MANAGEMENT_ROLES,
    _get_manageable_group,
    _require_agency,
)

router = APIRouter()


@router.get(
    "/groups/{group_id}/qr-codes",
    response_model=GroupPassengerQrCodesResponse,
    status_code=status.HTTP_200_OK,
    summary="List QR lifecycle status for submitted passengers in an office-managed group",
)
async def get_group_passenger_qr_codes(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> GroupPassengerQrCodesResponse:
    agency_id = _require_agency(current_user)
    group = await _get_manageable_group(session, agency_id, group_id, current_user)
    return await _group_passenger_qr_codes(session, agency_id, group)


@router.post(
    "/groups/{group_id}/passengers/{passenger_id}/qr",
    dependencies=[Depends(require_cookie_csrf)],
    response_model=PassengerQrTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a secure attendance QR token and reveal it once",
)
async def generate_passenger_qr(
    group_id: uuid.UUID,
    passenger_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> PassengerQrTokenResponse:
    agency_id = _require_agency(current_user)
    group = await _get_manageable_group(session, agency_id, group_id, current_user)
    await _get_qr_passenger(session, agency_id, group_id, passenger_id)
    token, payload = await _issue_passenger_qr(
        session, agency_id, passenger_id, current_user.id, group=group, regenerate=False
    )
    await _record_qr_audit(
        session,
        current_user,
        request,
        action="qr.generated",
        passenger_id=passenger_id,
        metadata={"group_id": str(group_id), "token_version": token.token_version},
    )
    return _qr_token_response(token, payload)


@router.post(
    "/groups/{group_id}/passengers/{passenger_id}/qr/regenerate",
    dependencies=[Depends(require_cookie_csrf)],
    response_model=PassengerQrTokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Revoke the current attendance QR and reveal a random replacement once",
)
async def regenerate_passenger_qr(
    group_id: uuid.UUID,
    passenger_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> PassengerQrTokenResponse:
    agency_id = _require_agency(current_user)
    group = await _get_manageable_group(session, agency_id, group_id, current_user)
    await _get_qr_passenger(session, agency_id, group_id, passenger_id)
    token, payload = await _issue_passenger_qr(
        session, agency_id, passenger_id, current_user.id, group=group, regenerate=True
    )
    await _record_qr_audit(
        session,
        current_user,
        request,
        action="qr.regenerated",
        passenger_id=passenger_id,
        metadata={"group_id": str(group_id), "token_version": token.token_version},
    )
    return _qr_token_response(token, payload)


@router.post(
    "/groups/{group_id}/passengers/{passenger_id}/qr/revoke",
    dependencies=[Depends(require_cookie_csrf)],
    response_model=PassengerQrTokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Permanently revoke a passenger attendance QR",
)
async def revoke_passenger_qr(
    group_id: uuid.UUID,
    passenger_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> PassengerQrTokenResponse:
    agency_id = _require_agency(current_user)
    await _get_manageable_group(session, agency_id, group_id, current_user)
    await _get_qr_passenger(session, agency_id, group_id, passenger_id)
    token = await _latest_passenger_qr(session, passenger_id, lock=True)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Passenger has no QR token"
        )
    if token.revoked_at is None:
        now = datetime.now(tz=UTC)
        token.is_active = False
        token.revoked_at = now
        token.updated_at = now
        await session.flush()
    await _record_qr_audit(
        session,
        current_user,
        request,
        action="qr.revoked",
        passenger_id=passenger_id,
        metadata={"group_id": str(group_id), "token_version": token.token_version},
    )
    return _qr_token_response(token)


@router.patch(
    "/groups/{group_id}/passengers/{passenger_id}/qr/active",
    dependencies=[Depends(require_cookie_csrf)],
    response_model=PassengerQrTokenResponse,
    summary="Mark the latest passenger QR active or inactive",
)
async def set_passenger_qr_active(
    group_id: uuid.UUID,
    passenger_id: uuid.UUID,
    body: SetPassengerQrActiveRequest,
    request: Request,
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> PassengerQrTokenResponse:
    agency_id = _require_agency(current_user)
    await _get_manageable_group(session, agency_id, group_id, current_user)
    await _get_qr_passenger(session, agency_id, group_id, passenger_id)
    token = await _latest_passenger_qr(session, passenger_id, lock=True)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Passenger has no QR token"
        )
    now = datetime.now(tz=UTC)
    if body.is_active and (token.revoked_at is not None or token.expires_at <= now):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Revoked or expired QR tokens cannot be activated; regenerate the QR instead",
        )
    if body.is_active:
        await session.execute(
            update(PassengerQRTokenModel)
            .where(
                PassengerQRTokenModel.passenger_id == passenger_id,
                PassengerQRTokenModel.id != token.id,
                PassengerQRTokenModel.is_active.is_(True),
            )
            .values(is_active=False, updated_at=now)
        )
    token.is_active = body.is_active
    token.updated_at = now
    await session.flush()
    await _record_qr_audit(
        session,
        current_user,
        request,
        action="qr.activated" if body.is_active else "qr.deactivated",
        passenger_id=passenger_id,
        metadata={"group_id": str(group_id), "token_version": token.token_version},
    )
    return _qr_token_response(token)


@router.patch(
    "/groups/{group_id}/passengers/{passenger_id}/qr/expiration",
    dependencies=[Depends(require_cookie_csrf)],
    response_model=PassengerQrTokenResponse,
    summary="Change or immediately expire the latest passenger QR",
)
async def set_passenger_qr_expiration(
    group_id: uuid.UUID,
    passenger_id: uuid.UUID,
    body: SetPassengerQrExpirationRequest,
    request: Request,
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> PassengerQrTokenResponse:
    agency_id = _require_agency(current_user)
    await _get_manageable_group(session, agency_id, group_id, current_user)
    await _get_qr_passenger(session, agency_id, group_id, passenger_id)
    token = await _latest_passenger_qr(session, passenger_id, lock=True)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Passenger has no QR token"
        )
    if token.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Revoked QR tokens cannot be changed"
        )
    expires_at = body.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    now = datetime.now(tz=UTC)
    token.expires_at = expires_at
    if expires_at <= now:
        token.is_active = False
    token.updated_at = now
    await session.flush()
    await _record_qr_audit(
        session,
        current_user,
        request,
        action="qr.expired" if expires_at <= now else "qr.expiration_changed",
        passenger_id=passenger_id,
        metadata={
            "group_id": str(group_id),
            "token_version": token.token_version,
            "expires_at": expires_at.isoformat(),
        },
    )
    return _qr_token_response(token)
