"""Idempotent QR issuance for operationally approved passengers."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, time, timedelta
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import (
    OFFICE_VISIBLE_PASSPORT_STATUS_VALUES,
    OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES,
    ClientGroup,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    PassengerQRTokenModel,
    PassportSubmissionModel,
)
from app.infrastructure.repositories.operational_roster import operational_roster_member

QR_TOKEN_TTL = timedelta(days=365)
QR_RETURN_GRACE_DAYS = 2


def qr_payload() -> str:
    return f"pdatt:{secrets.token_urlsafe(32)}"


def qr_hash(payload: str) -> str:
    return sha256(payload.encode("utf-8")).hexdigest()


def qr_status(
    token: PassengerQRTokenModel | None,
    now: datetime | None = None,
) -> str:
    if token is None:
        return "not_generated"
    current_time = now or datetime.now(tz=UTC)
    if token.revoked_at is not None:
        return "revoked"
    if token.expires_at <= current_time:
        return "expired"
    return "active" if token.is_active else "inactive"


def qr_expires_at_for_group(
    group: ClientGroup | ClientGroupModel,
    now: datetime | None = None,
) -> datetime:
    if group.return_date:
        return datetime.combine(
            group.return_date + timedelta(days=QR_RETURN_GRACE_DAYS),
            time.max,
            tzinfo=UTC,
        )
    return (now or datetime.now(tz=UTC)) + QR_TOKEN_TTL


def build_passenger_qr_token(
    *,
    agency_id: uuid.UUID,
    passenger_id: uuid.UUID,
    created_by_user_id: uuid.UUID | None,
    group: ClientGroupModel,
    token_version: int,
    now: datetime | None = None,
) -> tuple[PassengerQRTokenModel, str]:
    """Build one token with the shared payload, hash, and expiry policy."""

    issued_at = now or datetime.now(tz=UTC)
    payload = qr_payload()
    return (
        PassengerQRTokenModel(
            agency_id=agency_id,
            passenger_id=passenger_id,
            token_hash=qr_hash(payload),
            qr_payload=payload,
            token_version=token_version,
            is_active=True,
            created_by_user_id=created_by_user_id,
            expires_at=qr_expires_at_for_group(group, issued_at),
            created_at=issued_at,
            updated_at=issued_at,
        ),
        payload,
    )


async def ensure_approved_passenger_qr(
    session: AsyncSession,
    submission_id: uuid.UUID,
    *,
    created_by_user_id: uuid.UUID | None = None,
) -> PassengerQRTokenModel | None:
    """Issue one token only after approval, serialized by the passenger row."""

    result = await session.execute(
        select(PassportSubmissionModel, ClientGroupModel)
        .join(
            ClientGroupModel,
            ClientGroupModel.id == PassportSubmissionModel.group_id,
        )
        .where(
            PassportSubmissionModel.id == submission_id,
            PassportSubmissionModel.status.in_(
                OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES
            ),
            operational_roster_member(),
        )
        .with_for_update(of=PassportSubmissionModel)
    )
    row = result.first()
    if not row:
        return None
    submission, group = row
    # Defense in depth for test doubles and any dialect-specific filtering.
    if (
        submission.status
        not in OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES
    ):
        return None

    existing_result = await session.execute(
        select(PassengerQRTokenModel)
        .where(PassengerQRTokenModel.passenger_id == submission.id)
        .order_by(
            PassengerQRTokenModel.token_version.desc(),
            PassengerQRTokenModel.created_at.desc(),
        )
        .limit(1)
        .with_for_update()
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        return existing

    token, _payload = build_passenger_qr_token(
        agency_id=submission.agency_id,
        passenger_id=submission.id,
        created_by_user_id=created_by_user_id or group.created_by_user_id,
        group=group,
        token_version=1,
    )
    session.add(token)
    await session.flush()
    return token


async def ensure_approved_passenger_qrs(
    session: AsyncSession,
    submission_ids: list[uuid.UUID],
    *,
    created_by_user_id: uuid.UUID | None = None,
) -> list[PassengerQRTokenModel]:
    """Issue missing QR tokens for a locked approval batch in bounded queries."""

    ordered_ids = sorted(set(submission_ids), key=str)
    if not ordered_ids:
        return []

    result = await session.execute(
        select(PassportSubmissionModel, ClientGroupModel)
        .join(ClientGroupModel, ClientGroupModel.id == PassportSubmissionModel.group_id)
        .where(
            PassportSubmissionModel.id.in_(ordered_ids),
            PassportSubmissionModel.status.in_(
                OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES
            ),
            operational_roster_member(),
        )
        .order_by(PassportSubmissionModel.id)
        .with_for_update(of=PassportSubmissionModel)
    )
    approved_rows = list(result.all())
    approved_ids = [submission.id for submission, _group in approved_rows]
    if not approved_ids:
        return []

    existing_result = await session.execute(
        select(PassengerQRTokenModel)
        .where(PassengerQRTokenModel.passenger_id.in_(approved_ids))
        .order_by(
            PassengerQRTokenModel.passenger_id,
            PassengerQRTokenModel.token_version.desc(),
            PassengerQRTokenModel.created_at.desc(),
        )
        .with_for_update()
    )
    existing_by_passenger: dict[uuid.UUID, PassengerQRTokenModel] = {}
    for token_row in existing_result.scalars().all():
        existing_by_passenger.setdefault(token_row.passenger_id, token_row)

    tokens: list[PassengerQRTokenModel] = []
    for submission, group in approved_rows:
        existing_token = existing_by_passenger.get(submission.id)
        if existing_token is not None:
            tokens.append(existing_token)
            continue
        token, _payload = build_passenger_qr_token(
            agency_id=submission.agency_id,
            passenger_id=submission.id,
            created_by_user_id=created_by_user_id or group.created_by_user_id,
            group=group,
            token_version=1,
        )
        tokens.append(token)
        session.add(token)

    await session.flush()
    return tokens


async def ensure_mobile_passenger_qr(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    passenger_id: uuid.UUID,
) -> PassengerQRTokenModel | None:
    """Return or issue a usable QR for an authenticated passenger identity.

    Dashboard rendering is an operational convenience, not an authorization
    boundary.  Mobile ownership has already been proven by the caller, so the
    source passenger row is locked and scoped again here before issuing the
    same opaque attendance payload used by Tour Ops.  Expired/revoked tokens
    are replaced instead of exposing an unusable QR offline.
    """

    row = (
        await session.execute(
            select(PassportSubmissionModel, ClientGroupModel)
            .join(ClientGroupModel, ClientGroupModel.id == PassportSubmissionModel.group_id)
            .where(
                PassportSubmissionModel.id == passenger_id,
                operational_roster_member(),
                PassportSubmissionModel.agency_id == agency_id,
                PassportSubmissionModel.group_id == group_id,
                PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
                ClientGroupModel.id == group_id,
                ClientGroupModel.agency_id == agency_id,
            )
            .with_for_update(of=PassportSubmissionModel)
        )
    ).first()
    if row is None:
        return None
    submission, group = row
    existing = (
        await session.execute(
            select(PassengerQRTokenModel)
            .where(
                PassengerQRTokenModel.agency_id == agency_id,
                PassengerQRTokenModel.passenger_id == passenger_id,
            )
            .order_by(
                PassengerQRTokenModel.token_version.desc(),
                PassengerQRTokenModel.created_at.desc(),
            )
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    now = datetime.now(tz=UTC)
    if (
        existing is not None
        and existing.qr_payload
        and existing.is_active
        and existing.revoked_at is None
        and existing.expires_at > now
    ):
        return existing
    if existing is not None:
        existing.is_active = False
        if existing.revoked_at is None:
            existing.revoked_at = now
        existing.updated_at = now

    token, _payload = build_passenger_qr_token(
        agency_id=submission.agency_id,
        passenger_id=submission.id,
        created_by_user_id=group.created_by_user_id,
        group=group,
        token_version=(existing.token_version + 1) if existing is not None else 1,
        now=now,
    )
    session.add(token)
    await session.flush()
    return token
