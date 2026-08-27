"""Bounded, idempotent browser attendance batch processing."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Protocol

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging.logger import get_logger
from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    AttendanceRuntimeRegistrationModel,
    AttendanceScanBatchModel,
    AttendanceScanBatchResultModel,
    AttendanceSessionModel,
    PassportSubmissionModel,
)
from app.presentation.api.v1.routes.tour_operations_attendance_scan_support import (
    TourAttendanceScanDependencies,
    record_coordinator_attendance_scan,
)
from app.presentation.api.v1.schemas.tour_operations_schemas import (
    AttendanceScanBatchItemRequest,
    AttendanceScanBatchItemResponse,
    AttendanceScanBatchRequest,
    AttendanceScanBatchResponse,
    AttendanceScanRequest,
    AttendanceScanResponse,
)

logger = get_logger(__name__)


class _AttendanceScanResponseFactory(Protocol):
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
class AttendanceBatchDependencies:
    scan: TourAttendanceScanDependencies
    attendance_scan_response: _AttendanceScanResponseFactory


async def process_coordinator_attendance_scan_batch(
    *,
    body: AttendanceScanBatchRequest,
    request: Request,
    current_user: User,
    session: AsyncSession,
    agency_id: uuid.UUID,
    attendance_session: AttendanceSessionModel,
    runtime: AttendanceRuntimeRegistrationModel | None,
    dependencies: AttendanceBatchDependencies,
) -> AttendanceScanBatchResponse:
    batch_fingerprint = _batch_fingerprint(body)
    await _require_batch_identity(
        session=session,
        body=body,
        agency_id=agency_id,
        attendance_session=attendance_session,
        current_user=current_user,
        runtime=runtime,
        request_fingerprint=batch_fingerprint,
    )

    items: list[AttendanceScanBatchItemResponse] = []
    for ordinal, item in enumerate(body.scans):
        fingerprint = _item_fingerprint(item)
        existing = await _load_existing_result(
            session=session,
            agency_id=agency_id,
            session_id=attendance_session.id,
            client_event_id=item.client_event_id,
        )
        if existing is not None:
            items.append(
                await _replay_existing_result(
                    session=session,
                    attendance_session=attendance_session,
                    existing=existing,
                    request_fingerprint=fingerprint,
                    dependencies=dependencies,
                )
            )
            continue

        response = await _process_new_item(
            item=item,
            request=request,
            current_user=current_user,
            session=session,
            agency_id=agency_id,
            attendance_session=attendance_session,
            runtime=runtime,
            dependencies=dependencies,
        )
        if response.retryable:
            items.append(response)
            continue

        persisted = await _persist_terminal_result(
            session=session,
            batch_id=body.batch_id,
            agency_id=agency_id,
            session_id=attendance_session.id,
            coordinator_user_id=current_user.id,
            ordinal=ordinal,
            item=item,
            response=response,
            request_fingerprint=fingerprint,
        )
        items.append(
            await _replay_existing_result(
                session=session,
                attendance_session=attendance_session,
                existing=persisted,
                request_fingerprint=fingerprint,
                dependencies=dependencies,
            )
        )

    return AttendanceScanBatchResponse(batch_id=body.batch_id, items=items)


async def _require_batch_identity(
    *,
    session: AsyncSession,
    body: AttendanceScanBatchRequest,
    agency_id: uuid.UUID,
    attendance_session: AttendanceSessionModel,
    current_user: User,
    runtime: AttendanceRuntimeRegistrationModel | None,
    request_fingerprint: str,
) -> None:
    await session.execute(
        pg_insert(AttendanceScanBatchModel)
        .values(
            batch_id=body.batch_id,
            agency_id=agency_id,
            group_id=attendance_session.group_id,
            session_id=attendance_session.id,
            coordinator_user_id=current_user.id,
            runtime_registration_id=runtime.id if runtime is not None else None,
            request_fingerprint=request_fingerprint,
            item_count=len(body.scans),
        )
        .on_conflict_do_nothing(index_elements=[AttendanceScanBatchModel.batch_id])
    )
    result = await session.execute(
        select(AttendanceScanBatchModel)
        .where(AttendanceScanBatchModel.batch_id == body.batch_id)
        .with_for_update()
    )
    existing = result.scalar_one()
    expected_scope = (
        agency_id,
        attendance_session.group_id,
        attendance_session.id,
        current_user.id,
        runtime.id if runtime is not None else None,
        request_fingerprint,
        len(body.scans),
    )
    current_scope = (
        existing.agency_id,
        existing.group_id,
        existing.session_id,
        existing.coordinator_user_id,
        existing.runtime_registration_id,
        existing.request_fingerprint,
        existing.item_count,
    )
    if current_scope != expected_scope:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ATTENDANCE_SCAN_BATCH_CONFLICT",
                "message": "This batch_id is already bound to a different attendance request.",
            },
        )


async def _process_new_item(
    *,
    item: AttendanceScanBatchItemRequest,
    request: Request,
    current_user: User,
    session: AsyncSession,
    agency_id: uuid.UUID,
    attendance_session: AttendanceSessionModel,
    runtime: AttendanceRuntimeRegistrationModel | None,
    dependencies: AttendanceBatchDependencies,
) -> AttendanceScanBatchItemResponse:
    try:
        async with session.begin_nested():
            scan = await record_coordinator_attendance_scan(
                requested_session_id=attendance_session.id,
                body=AttendanceScanRequest(
                    client_event_id=item.client_event_id,
                    qr_payload=item.qr_payload,
                    scanned_at=item.scanned_at,
                    sync_source="offline",
                ),
                request=request,
                current_user=current_user,
                session=session,
                agency_id=agency_id,
                attendance_session=attendance_session,
                runtime=runtime,
                dependencies=dependencies.scan,
            )
    except HTTPException as exc:
        error_code, retryable = _stable_error_code(exc)
        return AttendanceScanBatchItemResponse(
            client_event_id=item.client_event_id,
            outcome="rejected",
            retryable=retryable,
            error_code=error_code,
        )
    except Exception as exc:
        logger.error(
            "attendance_scan_batch_item_failed",
            client_event_id=item.client_event_id,
            error_code="ATTENDANCE_SCAN_TEMPORARY_FAILURE",
            error_type=type(exc).__name__,
        )
        return AttendanceScanBatchItemResponse(
            client_event_id=item.client_event_id,
            outcome="rejected",
            retryable=True,
            error_code="ATTENDANCE_SCAN_TEMPORARY_FAILURE",
        )

    if scan.status == "invalid":
        return AttendanceScanBatchItemResponse(
            client_event_id=item.client_event_id,
            outcome="rejected",
            retryable=False,
            error_code="ATTENDANCE_QR_INVALID",
        )
    outcome = "counted" if scan.status == "counted" else "duplicate"
    return AttendanceScanBatchItemResponse(
        client_event_id=item.client_event_id,
        outcome=outcome,
        retryable=False,
        scan=scan,
    )


async def _persist_terminal_result(
    *,
    session: AsyncSession,
    batch_id: uuid.UUID,
    agency_id: uuid.UUID,
    session_id: uuid.UUID,
    coordinator_user_id: uuid.UUID,
    ordinal: int,
    item: AttendanceScanBatchItemRequest,
    response: AttendanceScanBatchItemResponse,
    request_fingerprint: str,
) -> AttendanceScanBatchResultModel:
    await session.execute(
        pg_insert(AttendanceScanBatchResultModel)
        .values(
            id=uuid.uuid4(),
            batch_id=batch_id,
            agency_id=agency_id,
            session_id=session_id,
            coordinator_user_id=coordinator_user_id,
            client_event_id=item.client_event_id,
            request_ordinal=ordinal,
            request_fingerprint=request_fingerprint,
            outcome=response.outcome,
            retryable=response.retryable,
            passenger_id=response.scan.passenger_id if response.scan is not None else None,
            error_code=response.error_code,
        )
        .on_conflict_do_nothing(
            index_elements=[
                AttendanceScanBatchResultModel.agency_id,
                AttendanceScanBatchResultModel.session_id,
                AttendanceScanBatchResultModel.client_event_id,
            ]
        )
    )
    result = await session.execute(
        select(AttendanceScanBatchResultModel)
        .where(
            AttendanceScanBatchResultModel.agency_id == agency_id,
            AttendanceScanBatchResultModel.session_id == session_id,
            AttendanceScanBatchResultModel.client_event_id == item.client_event_id,
        )
        .with_for_update()
    )
    return result.scalar_one()


async def _load_existing_result(
    *,
    session: AsyncSession,
    agency_id: uuid.UUID,
    session_id: uuid.UUID,
    client_event_id: str,
) -> AttendanceScanBatchResultModel | None:
    result = await session.execute(
        select(AttendanceScanBatchResultModel).where(
            AttendanceScanBatchResultModel.agency_id == agency_id,
            AttendanceScanBatchResultModel.session_id == session_id,
            AttendanceScanBatchResultModel.client_event_id == client_event_id,
        )
    )
    return result.scalar_one_or_none()


async def _replay_existing_result(
    *,
    session: AsyncSession,
    attendance_session: AttendanceSessionModel,
    existing: AttendanceScanBatchResultModel,
    request_fingerprint: str,
    dependencies: AttendanceBatchDependencies,
) -> AttendanceScanBatchItemResponse:
    if existing.request_fingerprint != request_fingerprint:
        return AttendanceScanBatchItemResponse(
            client_event_id=existing.client_event_id,
            outcome="rejected",
            retryable=False,
            error_code="ATTENDANCE_SCAN_IDEMPOTENCY_CONFLICT",
        )
    if existing.outcome == "rejected":
        return AttendanceScanBatchItemResponse(
            client_event_id=existing.client_event_id,
            outcome="rejected",
            retryable=existing.retryable,
            error_code=existing.error_code or "ATTENDANCE_SCAN_REJECTED",
        )

    passenger_name: str | None = None
    if existing.passenger_id is not None:
        passenger_name = (
            await session.execute(
                select(PassportSubmissionModel.client_name).where(
                    PassportSubmissionModel.id == existing.passenger_id
                )
            )
        ).scalar_one_or_none()
    scan = await dependencies.attendance_scan_response(
        session=session,
        attendance_session=attendance_session,
        passenger_id=existing.passenger_id,
        passenger_name=passenger_name,
        scan_status=existing.outcome,
        message="Attendance scan already reconciled.",
    )
    return AttendanceScanBatchItemResponse(
        client_event_id=existing.client_event_id,
        outcome=existing.outcome,
        retryable=False,
        scan=scan,
    )


def _stable_error_code(exc: HTTPException) -> tuple[str, bool]:
    if isinstance(exc.detail, dict):
        code = exc.detail.get("code")
        if isinstance(code, str) and code:
            return code[:80], exc.status_code in {429, 500, 502, 503, 504}
    if exc.status_code in {429, 500, 502, 503, 504}:
        return "ATTENDANCE_SCAN_TEMPORARY_FAILURE", True
    if exc.status_code == status.HTTP_409_CONFLICT:
        return "ATTENDANCE_SCAN_CONFLICT", False
    return "ATTENDANCE_SCAN_REJECTED", False


def _item_fingerprint(item: AttendanceScanBatchItemRequest) -> str:
    canonical = json.dumps(
        {
            "client_event_id": item.client_event_id,
            "qr_payload": item.qr_payload,
            "scanned_at": item.scanned_at.isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _batch_fingerprint(body: AttendanceScanBatchRequest) -> str:
    canonical = json.dumps(
        {
            "batch_id": str(body.batch_id),
            "items": [_item_fingerprint(item) for item in body.scans],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
