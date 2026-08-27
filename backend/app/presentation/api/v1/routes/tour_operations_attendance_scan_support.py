"""Attendance-scan mutation support shared by dashboard and mobile routes."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fastapi import HTTPException, Request, status
from sqlalchemy import cast, literal, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.application.mobile.sync_journal import append_attendance_realtime_change
from app.domain.entities.entities import (
    OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES,
    User,
)
from app.infrastructure.database.models import (
    AttendanceRecordModel,
    AttendanceRuntimeRegistrationModel,
    AttendanceSessionModel,
    PassengerQRTokenModel,
    PassportSubmissionModel,
)
from app.infrastructure.repositories.attendance_runtime_repository import (
    AttendanceRuntimeRepository,
)
from app.presentation.api.v1.routes.tour_operations_qr_helpers import (
    qr_hash,
)
from app.presentation.api.v1.schemas.tour_operations_schemas import (
    AttendanceScanRequest,
    AttendanceScanResponse,
)

SUBMITTED_PASSENGER_STATUSES = OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES
SCANNABLE_ATTENDANCE_STATUSES = ("active", "completed")
ATTENDANCE_SCAN_CLOCK_SKEW = timedelta(minutes=15)


class _ResolveScannablePassenger(Protocol):
    async def __call__(
        self,
        session: AsyncSession,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        qr_payload: str,
    ) -> tuple[
        PassportSubmissionModel | None,
        PassengerQRTokenModel | None,
        str | None,
    ]: ...


class _InsertCanonicalAttendanceRecord(Protocol):
    async def __call__(
        self,
        *,
        session: AsyncSession,
        agency_id: uuid.UUID,
        attendance_session: AttendanceSessionModel,
        passenger_id: uuid.UUID,
        coordinator_user_id: uuid.UUID,
        scanned_at: datetime,
        sync_source: str,
        client_event_id: str,
        device_id: str | None,
        runtime_registration_id: uuid.UUID | None = None,
    ) -> uuid.UUID | None: ...


class _RecordQrAudit(Protocol):
    async def __call__(
        self,
        session: AsyncSession,
        current_user: User,
        request: Request,
        *,
        action: str,
        passenger_id: uuid.UUID,
        metadata: dict[str, object],
    ) -> None: ...


class _AttendanceScanResponse(Protocol):
    async def __call__(
        self,
        session: AsyncSession,
        attendance_session: AttendanceSessionModel,
        passenger_id: uuid.UUID | None,
        passenger_name: str | None,
        scan_status: str,
        message: str,
    ) -> AttendanceScanResponse: ...


@dataclass(frozen=True, slots=True)
class TourAttendanceScanDependencies:
    resolve_scannable_passenger: _ResolveScannablePassenger
    insert_canonical_attendance_record: _InsertCanonicalAttendanceRecord
    record_qr_audit: _RecordQrAudit
    attendance_scan_response: _AttendanceScanResponse


def counted_attendance_message(session_status: str, passenger_name: str) -> str:
    if session_status == "completed":
        return f"{passenger_name} counted as a late scan after completion."
    return f"{passenger_name} counted."


def attendance_scan_is_within_activity_window(
    attendance_session: AttendanceSessionModel,
    scanned_at: datetime,
) -> bool:
    if (
        attendance_session.started_at is not None
        and scanned_at < attendance_session.started_at - ATTENDANCE_SCAN_CLOCK_SKEW
    ):
        return False
    return not (
        attendance_session.completed_at is not None and scanned_at > attendance_session.completed_at
    )


async def record_coordinator_attendance_scan(
    *,
    requested_session_id: uuid.UUID,
    body: AttendanceScanRequest,
    request: Request,
    current_user: User,
    session: AsyncSession,
    agency_id: uuid.UUID,
    attendance_session: AttendanceSessionModel,
    runtime: AttendanceRuntimeRegistrationModel | None,
    dependencies: TourAttendanceScanDependencies,
) -> AttendanceScanResponse:
    scanned_at = _validated_scan_time(attendance_session, body)
    passenger, qr_token, rejection_reason = await dependencies.resolve_scannable_passenger(
        session=session,
        agency_id=agency_id,
        group_id=attendance_session.group_id,
        qr_payload=body.qr_payload,
    )
    if passenger is None:
        return await _invalid_scan_response(
            requested_session_id=requested_session_id,
            request=request,
            current_user=current_user,
            session=session,
            attendance_session=attendance_session,
            qr_token=qr_token,
            rejection_reason=rejection_reason,
            dependencies=dependencies,
        )

    inserted_id = await dependencies.insert_canonical_attendance_record(
        session=session,
        agency_id=agency_id,
        attendance_session=attendance_session,
        passenger_id=passenger.id,
        coordinator_user_id=current_user.id,
        scanned_at=scanned_at,
        sync_source=body.sync_source,
        client_event_id=body.client_event_id,
        device_id=body.device_id,
        runtime_registration_id=runtime.id if runtime is not None else None,
    )
    if inserted_id is None:
        return await _duplicate_scan_response(
            requested_session_id=requested_session_id,
            request=request,
            current_user=current_user,
            session=session,
            attendance_session=attendance_session,
            passenger=passenger,
            dependencies=dependencies,
        )

    if runtime is not None:
        await AttendanceRuntimeRepository(session).mark_participation(
            agency_id=agency_id,
            session_id=attendance_session.id,
            coordinator_user_id=current_user.id,
            runtime_registration_id=runtime.id,
            source="scan",
            occurred_at=scanned_at,
        )
    return await _counted_scan_response(
        requested_session_id=requested_session_id,
        request=request,
        current_user=current_user,
        session=session,
        attendance_session=attendance_session,
        passenger=passenger,
        inserted_id=inserted_id,
        dependencies=dependencies,
    )


def _validated_scan_time(
    attendance_session: AttendanceSessionModel,
    body: AttendanceScanRequest,
) -> datetime:
    if attendance_session.status not in SCANNABLE_ATTENDANCE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Attendance activity cannot be scanned",
        )
    scanned_at = body.scanned_at or datetime.now(tz=UTC)
    if attendance_session.status == "completed":
        _require_saved_pre_close_scan(attendance_session, body, scanned_at)
    if not attendance_scan_is_within_activity_window(attendance_session, scanned_at):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The scan timestamp is outside the attendance activity window",
        )
    return scanned_at


def _require_saved_pre_close_scan(
    attendance_session: AttendanceSessionModel,
    body: AttendanceScanRequest,
    scanned_at: datetime,
) -> None:
    if (
        body.sync_source == "offline"
        and body.scanned_at is not None
        and attendance_session.completed_at is not None
        and scanned_at <= attendance_session.completed_at
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "This activity is closed. Only a saved offline scan captured "
            "before closure can reconcile."
        ),
    )


async def _invalid_scan_response(
    *,
    requested_session_id: uuid.UUID,
    request: Request,
    current_user: User,
    session: AsyncSession,
    attendance_session: AttendanceSessionModel,
    qr_token: PassengerQRTokenModel | None,
    rejection_reason: str | None,
    dependencies: TourAttendanceScanDependencies,
) -> AttendanceScanResponse:
    if qr_token is not None:
        await dependencies.record_qr_audit(
            session,
            current_user,
            request,
            action="qr.scanned",
            passenger_id=qr_token.passenger_id,
            metadata={
                "attendance_session_id": str(attendance_session.id),
                "requested_attendance_session_id": str(requested_session_id),
                "group_id": str(attendance_session.group_id),
                "result": "rejected",
                "reason": rejection_reason or "not_authorized",
            },
        )
    return await dependencies.attendance_scan_response(
        session=session,
        attendance_session=attendance_session,
        passenger_id=None,
        passenger_name=None,
        scan_status="invalid",
        message="QR code is not valid for this group.",
    )


async def _duplicate_scan_response(
    *,
    requested_session_id: uuid.UUID,
    request: Request,
    current_user: User,
    session: AsyncSession,
    attendance_session: AttendanceSessionModel,
    passenger: PassportSubmissionModel,
    dependencies: TourAttendanceScanDependencies,
) -> AttendanceScanResponse:
    await dependencies.record_qr_audit(
        session,
        current_user,
        request,
        action="qr.scanned",
        passenger_id=passenger.id,
        metadata={
            "attendance_session_id": str(attendance_session.id),
            "requested_attendance_session_id": str(requested_session_id),
            "group_id": str(attendance_session.group_id),
            "result": "duplicate",
        },
    )
    return await dependencies.attendance_scan_response(
        session=session,
        attendance_session=attendance_session,
        passenger_id=passenger.id,
        passenger_name=passenger.client_name,
        scan_status="duplicate",
        message="This scan or passenger is already counted for this activity.",
    )


async def _counted_scan_response(
    *,
    requested_session_id: uuid.UUID,
    request: Request,
    current_user: User,
    session: AsyncSession,
    attendance_session: AttendanceSessionModel,
    passenger: PassportSubmissionModel,
    inserted_id: uuid.UUID,
    dependencies: TourAttendanceScanDependencies,
) -> AttendanceScanResponse:
    await dependencies.record_qr_audit(
        session,
        current_user,
        request,
        action="qr.scanned",
        passenger_id=passenger.id,
        metadata={
            "attendance_session_id": str(attendance_session.id),
            "requested_attendance_session_id": str(requested_session_id),
            "group_id": str(attendance_session.group_id),
            "attendance_record_id": str(inserted_id),
            "result": "counted",
        },
    )
    return await dependencies.attendance_scan_response(
        session=session,
        attendance_session=attendance_session,
        passenger_id=passenger.id,
        passenger_name=passenger.client_name,
        scan_status="counted",
        message=counted_attendance_message(
            attendance_session.status,
            passenger.client_name,
        ),
    )


async def insert_canonical_attendance_record(
    *,
    session: AsyncSession,
    agency_id: uuid.UUID,
    attendance_session: AttendanceSessionModel,
    passenger_id: uuid.UUID,
    coordinator_user_id: uuid.UUID,
    scanned_at: datetime,
    sync_source: str,
    client_event_id: str,
    device_id: str | None,
    runtime_registration_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Insert once across a canonical activity and all of its legacy aliases."""

    family_session = aliased(
        AttendanceSessionModel,
        name="attendance_session_family",
    )
    existing_family_record = (
        select(literal(1))
        .select_from(AttendanceRecordModel)
        .join(
            family_session,
            family_session.id == AttendanceRecordModel.session_id,
        )
        .where(
            family_session.canonical_session_id == attendance_session.id,
            or_(
                AttendanceRecordModel.passenger_id == passenger_id,
                AttendanceRecordModel.client_event_id == client_event_id,
            ),
        )
        .exists()
    )
    record_id = uuid.uuid4()
    record_columns = AttendanceRecordModel.__table__.c
    candidate = select(
        literal(record_id, type_=record_columns.id.type),
        literal(agency_id, type_=record_columns.agency_id.type),
        literal(attendance_session.id, type_=record_columns.session_id.type),
        literal(passenger_id, type_=record_columns.passenger_id.type),
        literal(coordinator_user_id, type_=record_columns.coordinator_user_id.type),
        literal(scanned_at, type_=record_columns.scanned_at.type),
        cast(
            literal(sync_source, type_=record_columns.sync_source.type),
            record_columns.sync_source.type,
        ),
        literal(client_event_id, type_=record_columns.client_event_id.type),
        cast(
            literal(device_id, type_=record_columns.device_id.type),
            record_columns.device_id.type,
        ),
        literal(
            runtime_registration_id,
            type_=record_columns.runtime_registration_id.type,
        ),
    ).where(~existing_family_record)
    insert_result = await session.execute(
        pg_insert(AttendanceRecordModel)
        .from_select(
            [
                "id",
                "agency_id",
                "session_id",
                "passenger_id",
                "coordinator_user_id",
                "scanned_at",
                "sync_source",
                "client_event_id",
                "device_id",
                "runtime_registration_id",
            ],
            candidate,
        )
        .on_conflict_do_nothing()
        .returning(AttendanceRecordModel.id)
    )
    inserted_id: uuid.UUID | None = insert_result.scalar_one_or_none()
    if inserted_id is not None:
        await append_attendance_realtime_change(
            session,
            agency_id=agency_id,
            group_id=attendance_session.group_id,
            attendance_record_id=inserted_id,
            coordinator_user_id=coordinator_user_id,
            occurred_at=scanned_at,
        )
    return inserted_id


async def resolve_scannable_passenger(
    session: AsyncSession,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    qr_payload: str,
) -> tuple[PassportSubmissionModel | None, PassengerQRTokenModel | None, str | None]:
    now = datetime.now(tz=UTC)
    token_hash = qr_hash(qr_payload.strip())
    result = await session.execute(
        select(PassportSubmissionModel, PassengerQRTokenModel)
        .join(
            PassengerQRTokenModel,
            PassengerQRTokenModel.passenger_id == PassportSubmissionModel.id,
        )
        .where(
            PassengerQRTokenModel.agency_id == agency_id,
            PassengerQRTokenModel.token_hash == token_hash,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
        )
    )
    resolved = result.first()
    if not resolved:
        return None, None, "unknown_token"
    passenger, token = resolved
    if token.revoked_at is not None:
        return None, token, "revoked"
    if token.expires_at <= now:
        return None, token, "expired"
    if not token.is_active:
        return None, token, "inactive"
    if passenger.group_id != group_id:
        return None, token, "wrong_group"
    return passenger, token, None


__all__ = [
    "SCANNABLE_ATTENDANCE_STATUSES",
    "SUBMITTED_PASSENGER_STATUSES",
    "TourAttendanceScanDependencies",
    "attendance_scan_is_within_activity_window",
    "counted_attendance_message",
    "insert_canonical_attendance_record",
    "record_coordinator_attendance_scan",
    "resolve_scannable_passenger",
]
