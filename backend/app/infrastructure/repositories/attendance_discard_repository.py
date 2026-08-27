"""Idempotent, privacy-safe attendance discard evidence persistence."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import AttendanceDiscardTombstoneModel
from app.infrastructure.repositories.attendance_runtime_repository import (
    AttendanceRuntimeRepository,
)

DiscardReason = Literal[
    "operator_discard",
    "coordinator_confirmed_rescan",
    "wrong_group",
    "expired_authorization",
    "activity_closed",
    "duplicate",
    "duplicate_local_evidence",
    "passenger_not_attending",
    "privacy_or_data_error",
    "server_rejected",
    "server_terminal_rejection",
    "corrupted_entry",
    "other",
]

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class AttendanceDiscardInput:
    discard_event_id: uuid.UUID
    scan_reference: str
    reason_category: DiscardReason
    discarded_at: datetime
    captured_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AttendanceDiscardResult:
    discard_event_id: uuid.UUID
    status: Literal["accepted", "already_applied"]
    received_at: datetime


class AttendanceDiscardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_batch(
        self,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        session_id: uuid.UUID,
        coordinator_user_id: uuid.UUID,
        runtime_registration_id: uuid.UUID | None,
        items: Sequence[AttendanceDiscardInput],
        retention_days: int,
        now: datetime | None = None,
    ) -> tuple[AttendanceDiscardResult, ...]:
        if not 1 <= len(items) <= 100:
            raise ValueError("Attendance discard batch size is invalid")
        if not 1 <= retention_days <= 3650:
            raise ValueError("Attendance discard retention is invalid")
        if len({item.discard_event_id for item in items}) != len(items):
            raise ValueError("Attendance discard batch contains duplicate event ids")
        observed = now or datetime.now(tz=UTC)
        if observed.tzinfo is None or observed.utcoffset() is None:
            observed = observed.replace(tzinfo=UTC)
        else:
            observed = observed.astimezone(UTC)
        retention_expires_at = observed + timedelta(days=retention_days)

        rows: list[dict[str, object]] = []
        for item in items:
            if _SHA256_HEX.fullmatch(item.scan_reference) is None:
                raise ValueError("Attendance discard scan reference is invalid")
            discarded_at = item.discarded_at
            if discarded_at.tzinfo is None or discarded_at.utcoffset() is None:
                raise ValueError("Attendance discard timestamp must be timezone aware")
            discarded_at = discarded_at.astimezone(UTC)
            if discarded_at > observed + timedelta(minutes=5):
                raise ValueError("Attendance discard timestamp is in the future")
            captured_at = item.captured_at
            if captured_at is not None:
                if captured_at.tzinfo is None or captured_at.utcoffset() is None:
                    raise ValueError("Attendance capture timestamp must be timezone aware")
                captured_at = captured_at.astimezone(UTC)
                if captured_at > discarded_at:
                    raise ValueError("Attendance capture cannot follow discard")
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "agency_id": agency_id,
                    "group_id": group_id,
                    "session_id": session_id,
                    "coordinator_user_id": coordinator_user_id,
                    "runtime_registration_id": runtime_registration_id,
                    "discard_event_id": item.discard_event_id,
                    "scan_reference": item.scan_reference,
                    "reason_category": item.reason_category,
                    "captured_at": captured_at,
                    "discarded_at": discarded_at,
                    "received_at": observed,
                    "status": "accepted",
                    "retention_expires_at": retention_expires_at,
                    "updated_at": observed,
                }
            )

        inserted_ids = set(
            (
                await self._session.execute(
                    pg_insert(AttendanceDiscardTombstoneModel)
                    .values(rows)
                    .on_conflict_do_nothing(constraint="uq_attendance_discard_event")
                    .returning(AttendanceDiscardTombstoneModel.discard_event_id)
                )
            ).scalars()
        )
        event_ids = tuple(item.discard_event_id for item in items)
        persisted = list(
            (
                await self._session.execute(
                    select(AttendanceDiscardTombstoneModel).where(
                        AttendanceDiscardTombstoneModel.agency_id == agency_id,
                        AttendanceDiscardTombstoneModel.coordinator_user_id == coordinator_user_id,
                        AttendanceDiscardTombstoneModel.discard_event_id.in_(event_ids),
                    )
                )
            ).scalars()
        )
        by_event = {row.discard_event_id: row for row in persisted}
        if len(by_event) != len(items):
            raise RuntimeError("Attendance discard persistence was incomplete")
        input_by_event = {item.discard_event_id: item for item in items}
        for event_id, persisted_row in by_event.items():
            supplied = input_by_event[event_id]
            if (
                persisted_row.group_id != group_id
                or persisted_row.session_id != session_id
                or persisted_row.runtime_registration_id != runtime_registration_id
                or persisted_row.scan_reference != supplied.scan_reference
                or persisted_row.reason_category != supplied.reason_category
            ):
                raise ValueError("Attendance discard idempotency conflict")
        if runtime_registration_id is not None:
            await AttendanceRuntimeRepository(self._session).mark_participation(
                agency_id=agency_id,
                session_id=session_id,
                coordinator_user_id=coordinator_user_id,
                runtime_registration_id=runtime_registration_id,
                source="discard",
                occurred_at=observed,
            )
        await self._session.flush()
        return tuple(
            AttendanceDiscardResult(
                discard_event_id=item.discard_event_id,
                status=("accepted" if item.discard_event_id in inserted_ids else "already_applied"),
                received_at=by_event[item.discard_event_id].received_at,
            )
            for item in items
        )


__all__ = [
    "AttendanceDiscardInput",
    "AttendanceDiscardRepository",
    "AttendanceDiscardResult",
    "DiscardReason",
]
