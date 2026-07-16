"""QR token lifecycle helpers for tour operations routes."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, time, timedelta
from hashlib import sha256

from fastapi import HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import PassportProcessingStatus, User
from app.infrastructure.database.models import (
    ClientGroupModel,
    CoordinatorAssignmentModel,
    PassengerQRTokenModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.schemas.tour_operations_schemas import (
    GroupPassengerQrCodeResponse,
    GroupPassengerQrCodesResponse,
    PassengerQrTokenResponse,
)

SUBMITTED_PASSENGER_STATUSES = (
    PassportProcessingStatus.CLIENT_SUBMITTED.value,
    PassportProcessingStatus.CONFIRMED.value,
)
QR_TOKEN_TTL = timedelta(days=365)
QR_RETURN_GRACE_DAYS = 2


async def group_passenger_qr_codes(
    session: AsyncSession,
    agency_id: uuid.UUID,
    group: ClientGroupModel,
) -> GroupPassengerQrCodesResponse:
    assignment_subquery = (
        select(
            CoordinatorAssignmentModel.passenger_id.label("passenger_id"),
            CoordinatorAssignmentModel.coordinator_user_id.label("coordinator_id"),
        )
        .where(
            CoordinatorAssignmentModel.agency_id == agency_id,
            CoordinatorAssignmentModel.group_id == group.id,
            CoordinatorAssignmentModel.active.is_(True),
        )
        .subquery()
    )
    result = await session.execute(
        select(
            PassportSubmissionModel,
            UserModel.id.label("coordinator_id"),
            UserModel.full_name.label("coordinator_name"),
        )
        .outerjoin(assignment_subquery, assignment_subquery.c.passenger_id == PassportSubmissionModel.id)
        .outerjoin(UserModel, UserModel.id == assignment_subquery.c.coordinator_id)
        .where(
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group.id,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
        )
        .order_by(PassportSubmissionModel.client_name.asc())
    )

    passenger_rows = list(result.all())
    token_by_passenger: dict[uuid.UUID, PassengerQRTokenModel] = {}
    passenger_ids = [passenger.id for passenger, _, _ in passenger_rows]
    if passenger_ids:
        token_result = await session.execute(
            select(PassengerQRTokenModel)
            .where(PassengerQRTokenModel.passenger_id.in_(passenger_ids))
            .order_by(
                PassengerQRTokenModel.passenger_id,
                PassengerQRTokenModel.token_version.desc(),
                PassengerQRTokenModel.created_at.desc(),
            )
        )
        for token in token_result.scalars().all():
            token_by_passenger.setdefault(token.passenger_id, token)

    for passenger, _, _ in passenger_rows:
        if passenger.id in token_by_passenger:
            continue
        token, _payload = await issue_passenger_qr(
            session,
            agency_id,
            passenger.id,
            group.created_by_user_id,
            group=group,
            regenerate=False,
        )
        token_by_passenger[passenger.id] = token

    passengers: list[GroupPassengerQrCodeResponse] = []
    for passenger, coordinator_id, coordinator_name in passenger_rows:
        token = token_by_passenger.get(passenger.id)
        status_value = qr_status(token)
        passengers.append(
            GroupPassengerQrCodeResponse(
                passenger_id=passenger.id,
                client_name=passenger.client_name,
                client_email=passenger.client_email,
                client_phone=passenger.client_phone,
                departure_city=passenger.departure_city,
                coordinator_id=coordinator_id,
                coordinator_name=coordinator_name,
                qr_status=status_value,
                qr_token_version=token.token_version if token else None,
                qr_created_at=token.created_at if token else None,
                qr_expires_at=token.expires_at if token else None,
                qr_revoked_at=token.revoked_at if token else None,
                qr_payload=token.qr_payload if token and status_value in {"active", "inactive"} else None,
            )
        )

    return GroupPassengerQrCodesResponse(
        group_id=group.id,
        group_name=group.name,
        generated_at=datetime.now(tz=UTC),
        passengers=passengers,
    )


def qr_payload() -> str:
    return f"pdatt:{secrets.token_urlsafe(32)}"


def qr_hash(payload: str) -> str:
    return sha256(payload.encode("utf-8")).hexdigest()


def qr_status(token: PassengerQRTokenModel | None, now: datetime | None = None) -> str:
    if token is None:
        return "not_generated"
    now = now or datetime.now(tz=UTC)
    if token.revoked_at is not None:
        return "revoked"
    if token.expires_at <= now:
        return "expired"
    return "active" if token.is_active else "inactive"


def qr_token_response(
    token: PassengerQRTokenModel,
    payload: str | None = None,
) -> PassengerQrTokenResponse:
    status_value = qr_status(token)
    return PassengerQrTokenResponse(
        passenger_id=token.passenger_id,
        status=status_value,
        token_version=token.token_version,
        created_at=token.created_at,
        expires_at=token.expires_at,
        revoked_at=token.revoked_at,
        qr_payload=payload if payload is not None else (token.qr_payload if status_value in {"active", "inactive"} else None),
    )


async def get_qr_passenger(
    session: AsyncSession,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    passenger_id: uuid.UUID,
) -> PassportSubmissionModel:
    result = await session.execute(
        select(PassportSubmissionModel).where(
            PassportSubmissionModel.id == passenger_id,
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
        )
    )
    passenger = result.scalar_one_or_none()
    if not passenger:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Passenger was not found in this group")
    return passenger


async def latest_passenger_qr(
    session: AsyncSession,
    passenger_id: uuid.UUID,
    *,
    lock: bool = False,
) -> PassengerQRTokenModel | None:
    stmt = (
        select(PassengerQRTokenModel)
        .where(PassengerQRTokenModel.passenger_id == passenger_id)
        .order_by(PassengerQRTokenModel.token_version.desc(), PassengerQRTokenModel.created_at.desc())
        .limit(1)
    )
    if lock:
        stmt = stmt.with_for_update()
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def issue_passenger_qr(
    session: AsyncSession,
    agency_id: uuid.UUID,
    passenger_id: uuid.UUID,
    created_by_user_id: uuid.UUID | None,
    *,
    group: ClientGroupModel,
    regenerate: bool,
) -> tuple[PassengerQRTokenModel, str]:
    await session.execute(
        select(PassportSubmissionModel.id)
        .where(PassportSubmissionModel.id == passenger_id, PassportSubmissionModel.agency_id == agency_id)
        .with_for_update()
    )
    previous = await latest_passenger_qr(session, passenger_id, lock=True)
    now = datetime.now(tz=UTC)
    if previous and not regenerate and qr_status(previous, now) in {"active", "inactive"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Passenger already has a usable QR token; regenerate it to reveal a replacement",
        )
    await session.execute(
        update(PassengerQRTokenModel)
        .where(
            PassengerQRTokenModel.passenger_id == passenger_id,
            PassengerQRTokenModel.is_active.is_(True),
        )
        .values(is_active=False, updated_at=now)
    )
    if previous and regenerate and previous.revoked_at is None:
        previous.revoked_at = now

    payload = qr_payload()
    token = PassengerQRTokenModel(
        agency_id=agency_id,
        passenger_id=passenger_id,
        token_hash=qr_hash(payload),
        qr_payload=payload,
        token_version=(previous.token_version + 1) if previous else 1,
        is_active=True,
        created_by_user_id=created_by_user_id,
        expires_at=qr_expires_at_for_group(group, now),
        created_at=now,
        updated_at=now,
    )
    session.add(token)
    await session.flush()
    return token, payload


async def ensure_passenger_qr(
    session: AsyncSession,
    agency_id: uuid.UUID,
    group: ClientGroupModel,
    passenger_id: uuid.UUID,
    created_by_user_id: uuid.UUID | None = None,
) -> PassengerQRTokenModel:
    previous = await latest_passenger_qr(session, passenger_id, lock=True)
    if previous:
        return previous
    token, _payload = await issue_passenger_qr(
        session,
        agency_id,
        passenger_id,
        created_by_user_id or group.created_by_user_id,
        group=group,
        regenerate=False,
    )
    return token


def qr_expires_at_for_group(group: ClientGroupModel, now: datetime | None = None) -> datetime:
    if group.return_date:
        return datetime.combine(group.return_date + timedelta(days=QR_RETURN_GRACE_DAYS), time.max, tzinfo=UTC)
    return (now or datetime.now(tz=UTC)) + QR_TOKEN_TTL


async def record_qr_audit(
    session: AsyncSession,
    current_user: User,
    request: Request,
    *,
    action: str,
    passenger_id: uuid.UUID,
    metadata: dict[str, object],
) -> None:
    await AuditLogRepository(session).record(
        action=action,
        entity_type="passenger_qr_token",
        agency_id=current_user.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        entity_id=str(passenger_id),
        ip_address=request.client.host if request.client else None,
        metadata=metadata,
    )
