"""Bounded submitted-number discovery and ownership-proven trip guidance."""

from __future__ import annotations

import hmac
from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import and_, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only
from sqlalchemy.sql.elements import ColumnElement

from app.application.mobile.passenger_phone_authority import authoritative_submission_phone
from app.core.logging.logger import get_logger
from app.core.security.mobile_jwt import hash_mobile_lookup
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES, GroupStatus
from app.domain.value_objects.phone_number import normalize_phone_number
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
    MobilePassengerIdentityModel,
)
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel

PhoneSubmissionRow = tuple[PassportSubmissionModel, ClientGroupModel, GCGroupAccessModel | None]
TripAvailability = Literal["trip_not_active", "trip_starts_later", "trip_access_ended"]
_MAX_PHONE_SUBMISSIONS = 100
logger = get_logger(__name__)


def phone_digits_predicate(normalized_phone: str) -> ColumnElement[bool]:
    """Use SQL only as a candidate filter; canonical Python equality is final."""

    digits = normalized_phone.removeprefix("+")
    variants = {digits, f"00{digits}"}
    if normalized_phone.startswith("+91") and len(digits) == 12:
        variants.add(digits[2:])
    return func.regexp_replace(
        # Fixed SQL literals let even PostgreSQL generic prepared plans match
        # the expression index. User phone variants remain bound parameters.
        func.coalesce(PassportSubmissionModel.client_phone, literal_column("''")),
        literal_column(r"'\D'"), literal_column("''"), literal_column("'g'"),
    ).in_(sorted(variants))


async def submitted_phone_rows(session: AsyncSession, normalized_phone: str) -> list[PhoneSubmissionRow]:
    rows = (
        await session.execute(
            select(PassportSubmissionModel, ClientGroupModel, GCGroupAccessModel)
            .options(
                load_only(
                    PassportSubmissionModel.id, PassportSubmissionModel.agency_id,
                    PassportSubmissionModel.group_id, PassportSubmissionModel.client_phone,
                    PassportSubmissionModel.status, PassportSubmissionModel.client_reviewed_at,
                    PassportSubmissionModel.image_s3_key, PassportSubmissionModel.confidence_score,
                    PassportSubmissionModel.staff_metadata, raiseload=True,
                ),
                load_only(
                    ClientGroupModel.id, ClientGroupModel.agency_id,
                    ClientGroupModel.status, ClientGroupModel.deleted_at, raiseload=True,
                ),
                load_only(
                    GCGroupAccessModel.id, GCGroupAccessModel.agency_id, GCGroupAccessModel.group_id,
                    GCGroupAccessModel.is_enabled, GCGroupAccessModel.passenger_access_enabled,
                    GCGroupAccessModel.revoked_at, GCGroupAccessModel.access_starts_at,
                    GCGroupAccessModel.access_expires_at, raiseload=True,
                ),
            )
            .join(ClientGroupModel, and_(
                ClientGroupModel.id == PassportSubmissionModel.group_id,
                ClientGroupModel.agency_id == PassportSubmissionModel.agency_id,
            ))
            .outerjoin(GCGroupAccessModel, and_(
                GCGroupAccessModel.group_id == ClientGroupModel.id,
                GCGroupAccessModel.agency_id == ClientGroupModel.agency_id,
            ))
            .where(
                phone_digits_predicate(normalized_phone),
                PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
                PassportSubmissionModel.client_reviewed_at.is_not(None),
                ClientGroupModel.status.in_((GroupStatus.ACTIVE.value, GroupStatus.CLOSED.value)),
                ClientGroupModel.deleted_at.is_(None),
            )
            .order_by(PassportSubmissionModel.id)
            .limit(_MAX_PHONE_SUBMISSIONS + 1)
        )
    ).all()
    if len(rows) > _MAX_PHONE_SUBMISSIONS:
        # Never authorize a truncated proof set: a shared number may otherwise
        # look unambiguous. Keep the public response neutral and send no OTP.
        logger.warning("mobile_otp_submitted_phone_lookup_overflow", candidate_limit=_MAX_PHONE_SUBMISSIONS)
        return []
    return [
        (submission, group, access) for submission, group, access in rows
        if authoritative_submission_phone(submission) == normalized_phone
    ]


async def challenge_phone(
    session: AsyncSession, phone_lookup_hash: str, supplied_phone: str | None,
) -> str | None:
    """New apps echo the phone; old active-login clients use a hash-bound identity."""

    if supplied_phone is not None:
        normalized = normalize_phone_number(supplied_phone)
        if normalized is None or not hmac.compare_digest(
            hash_mobile_lookup(normalized, purpose="passenger-phone"), phone_lookup_hash,
        ):
            raise HTTPException(401, "Invalid or expired verification code")
        return normalized
    candidates = (
        await session.execute(
            select(MobilePassengerIdentityModel.normalized_phone_number)
            .where(MobilePassengerIdentityModel.phone_lookup_hash == phone_lookup_hash)
            .limit(51)
        )
    ).scalars().all()
    for candidate in candidates:
        normalized = normalize_phone_number(candidate)
        if normalized is not None and hmac.compare_digest(
            hash_mobile_lookup(normalized, purpose="passenger-phone"), phone_lookup_hash,
        ):
            return normalized
    return None


def unavailable_trip_status(rows: list[PhoneSubmissionRow]) -> TripAvailability | None:
    """No names, tenant identifiers, or dates are disclosed by this guidance."""

    if not rows:
        return None
    now = datetime.now(tz=UTC)
    states: set[TripAvailability] = set()
    for _submission, _group, access in rows:
        if access is None or not access.is_enabled or not access.passenger_access_enabled or access.revoked_at:
            states.add("trip_not_active")
        elif access.access_expires_at is not None and access.access_expires_at <= now:
            states.add("trip_access_ended")
        elif access.access_starts_at is not None and access.access_starts_at > now:
            states.add("trip_starts_later")
        else:
            # Active-but-ambiguous passengers need staff to repair their proof
            # data, rather than being told that their trip has not started.
            return None
    for state in ("trip_starts_later", "trip_not_active", "trip_access_ended"):
        if state in states:
            return state
    return None
