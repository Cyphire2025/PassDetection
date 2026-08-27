"""Bounded offline-attendance batch orchestration for the native mobile API."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.mobile_access_policy import AuthorizedMobileTrip
from app.core.security.mobile_jwt import MobileAccessClaims
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
    MobileSyncChangeModel,
)
from app.infrastructure.database.models import (
    AttendanceRuntimeRegistrationModel,
    AttendanceSessionModel,
    PassengerQRTokenModel,
    PassportSubmissionModel,
)
from app.presentation.api.v1.routes.tour_operations_attendance_scan_support import (
    attendance_scan_is_within_activity_window,
)
from app.presentation.api.v1.schemas.mobile_schemas import (
    MobileAttendanceActionInput,
    MobileAttendanceActionResult,
    MobileAttendanceBatchRequest,
    MobileAttendanceBatchResponse,
)

_MAX_SCAN_CLOCK_SKEW = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class PreparedAttendanceAction:
    action: MobileAttendanceActionInput
    attendance_session: AttendanceSessionModel
    passenger: PassportSubmissionModel


@dataclass(slots=True)
class AttendanceReplaySnapshot:
    passengers: set[tuple[uuid.UUID, uuid.UUID]]
    event_passengers: dict[tuple[uuid.UUID, str], set[uuid.UUID]]


@dataclass(frozen=True, slots=True)
class _AppliedAttendanceAction:
    result: MobileAttendanceActionResult
    passenger_change: tuple[PassportSubmissionModel, datetime] | None = None
    participated_at: datetime | None = None


class _AttendanceSessionsForActions(Protocol):
    async def __call__(
        self,
        session: AsyncSession,
        claims: MobileAccessClaims,
        group_id: uuid.UUID,
        *,
        actions: Sequence[MobileAttendanceActionInput],
    ) -> dict[uuid.UUID | None, AttendanceSessionModel | None]: ...


class _ScannablePassengerSnapshot(Protocol):
    async def __call__(
        self,
        session: AsyncSession,
        *,
        claims: MobileAccessClaims,
        actions: Sequence[MobileAttendanceActionInput],
    ) -> dict[str, tuple[PassportSubmissionModel, PassengerQRTokenModel]]: ...


class _ResolveScannablePassenger(Protocol):
    def __call__(
        self,
        snapshot: dict[
            str,
            tuple[PassportSubmissionModel, PassengerQRTokenModel],
        ],
        *,
        group_id: uuid.UUID,
        qr_payload: str,
    ) -> tuple[PassportSubmissionModel | None, str | None]: ...


class _AttendanceReplaySnapshotLoader(Protocol):
    async def __call__(
        self,
        session: AsyncSession,
        *,
        claims: MobileAccessClaims,
        prepared: Sequence[PreparedAttendanceAction],
    ) -> AttendanceReplaySnapshot: ...


class _ReplayStateFromSnapshot(Protocol):
    def __call__(
        self,
        snapshot: AttendanceReplaySnapshot,
        *,
        attendance_session: AttendanceSessionModel,
        passenger_id: uuid.UUID,
        client_event_id: str,
    ) -> str: ...


class _AttendanceReplayState(Protocol):
    async def __call__(
        self,
        session: AsyncSession,
        *,
        claims: MobileAccessClaims,
        attendance_session: AttendanceSessionModel,
        passenger_id: uuid.UUID,
        client_event_id: str,
    ) -> str: ...


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


class _CurrentAttendanceRuntime(Protocol):
    async def __call__(
        self,
        session: AsyncSession,
        claims: MobileAccessClaims,
    ) -> AttendanceRuntimeRegistrationModel: ...


class _RuntimeParticipationRepository(Protocol):
    async def mark_participation(
        self,
        *,
        agency_id: uuid.UUID,
        session_id: uuid.UUID,
        coordinator_user_id: uuid.UUID,
        runtime_registration_id: uuid.UUID,
        source: Literal["scan", "checkpoint", "discard", "legacy"],
        occurred_at: datetime | None = None,
    ) -> None: ...


class _RuntimeRepositoryFactory(Protocol):
    def __call__(
        self,
        session: AsyncSession,
    ) -> _RuntimeParticipationRepository: ...


class _AppendSyncChange(Protocol):
    async def __call__(
        self,
        session: AsyncSession,
        *,
        access: GCGroupAccessModel,
        entity_type: str,
        entity_id: uuid.UUID | None,
        operation: Literal["upsert", "delete"],
        version: int,
        changed_by_user_id: uuid.UUID | None,
        audience: Literal["all", "passenger", "client_manager", "coordinator"],
        payload: dict[str, object] | None,
        flush: bool,
    ) -> MobileSyncChangeModel: ...


class _CoordinatorRosterRevision(Protocol):
    async def __call__(
        self,
        session: AsyncSession,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
    ) -> int: ...


@dataclass(frozen=True, slots=True)
class MobileAttendanceActionDependencies:
    attendance_sessions_for_actions: _AttendanceSessionsForActions
    scannable_passenger_snapshot: _ScannablePassengerSnapshot
    resolve_scannable_passenger: _ResolveScannablePassenger
    attendance_replay_snapshot: _AttendanceReplaySnapshotLoader
    replay_state_from_snapshot: _ReplayStateFromSnapshot
    attendance_replay_state: _AttendanceReplayState
    insert_canonical_attendance_record: _InsertCanonicalAttendanceRecord
    current_attendance_runtime: _CurrentAttendanceRuntime
    runtime_repository_factory: _RuntimeRepositoryFactory
    append_sync_change: _AppendSyncChange
    coordinator_roster_revision: _CoordinatorRosterRevision


async def apply_mobile_attendance_action_batch(
    *,
    group_id: uuid.UUID,
    body: MobileAttendanceBatchRequest,
    claims: MobileAccessClaims,
    session: AsyncSession,
    trip: AuthorizedMobileTrip,
    dependencies: MobileAttendanceActionDependencies,
) -> MobileAttendanceBatchResponse:
    resolved_results, session_candidates = _partition_clock_valid_actions(
        body.actions,
        now=datetime.now(tz=UTC),
    )
    prepared_by_index = await _prepare_actions(
        session=session,
        claims=claims,
        group_id=group_id,
        session_candidates=session_candidates,
        resolved_results=resolved_results,
        dependencies=dependencies,
    )
    runtime = (
        await dependencies.current_attendance_runtime(session, claims)
        if prepared_by_index
        else None
    )
    replay_snapshot = await dependencies.attendance_replay_snapshot(
        session,
        claims=claims,
        prepared=list(prepared_by_index.values()),
    )
    results, accepted_roster_changes, participated_sessions = await _apply_actions(
        session=session,
        claims=claims,
        actions=body.actions,
        resolved_results=resolved_results,
        prepared_by_index=prepared_by_index,
        runtime=runtime,
        replay_snapshot=replay_snapshot,
        dependencies=dependencies,
    )
    await _mark_runtime_participation(
        session=session,
        claims=claims,
        runtime=runtime,
        participated_sessions=participated_sessions,
        dependencies=dependencies,
    )
    await _append_targeted_roster_changes(
        session=session,
        claims=claims,
        group_id=group_id,
        trip=trip,
        accepted_roster_changes=accepted_roster_changes,
        dependencies=dependencies,
    )
    return MobileAttendanceBatchResponse(results=results)


def _partition_clock_valid_actions(
    actions: Sequence[MobileAttendanceActionInput],
    *,
    now: datetime,
) -> tuple[
    dict[int, MobileAttendanceActionResult],
    list[tuple[int, MobileAttendanceActionInput]],
]:
    resolved_results: dict[int, MobileAttendanceActionResult] = {}
    session_candidates: list[tuple[int, MobileAttendanceActionInput]] = []
    for index, action in enumerate(actions):
        if action.scanned_at > now + _MAX_SCAN_CLOCK_SKEW:
            resolved_results[index] = _rejected_result(
                action,
                reason_code="SCANNED_AT_IN_FUTURE",
            )
        else:
            session_candidates.append((index, action))
    return resolved_results, session_candidates


async def _prepare_actions(
    *,
    session: AsyncSession,
    claims: MobileAccessClaims,
    group_id: uuid.UUID,
    session_candidates: Sequence[tuple[int, MobileAttendanceActionInput]],
    resolved_results: dict[int, MobileAttendanceActionResult],
    dependencies: MobileAttendanceActionDependencies,
) -> dict[int, PreparedAttendanceAction]:
    attendance_sessions = await dependencies.attendance_sessions_for_actions(
        session,
        claims,
        group_id,
        actions=[action for _, action in session_candidates],
    )
    qr_candidates = _resolve_session_candidates(
        session_candidates,
        attendance_sessions=attendance_sessions,
        resolved_results=resolved_results,
    )
    qr_snapshot = await dependencies.scannable_passenger_snapshot(
        session,
        claims=claims,
        actions=[action for _, action, _ in qr_candidates],
    )
    prepared_by_index: dict[int, PreparedAttendanceAction] = {}
    for index, action, attendance_session in qr_candidates:
        passenger, rejection_reason = dependencies.resolve_scannable_passenger(
            qr_snapshot,
            group_id=group_id,
            qr_payload=action.signed_qr,
        )
        if passenger is None:
            resolved_results[index] = _rejected_result(
                action,
                reason_code=attendance_rejection_code(rejection_reason),
            )
            continue
        prepared_by_index[index] = PreparedAttendanceAction(
            action=action,
            attendance_session=attendance_session,
            passenger=passenger,
        )
    return prepared_by_index


def _resolve_session_candidates(
    session_candidates: Sequence[tuple[int, MobileAttendanceActionInput]],
    *,
    attendance_sessions: dict[
        uuid.UUID | None,
        AttendanceSessionModel | None,
    ],
    resolved_results: dict[int, MobileAttendanceActionResult],
) -> list[tuple[int, MobileAttendanceActionInput, AttendanceSessionModel]]:
    qr_candidates: list[tuple[int, MobileAttendanceActionInput, AttendanceSessionModel]] = []
    for index, action in session_candidates:
        attendance_session = attendance_sessions.get(action.session_id)
        if attendance_session is None:
            resolved_results[index] = MobileAttendanceActionResult(
                client_event_id=action.client_event_id,
                status="refresh_required",
                reason_code="ATTENDANCE_SESSION_SELECTION_REQUIRED",
            )
            continue
        if not attendance_scan_is_within_activity_window(
            attendance_session,
            action.scanned_at,
        ):
            resolved_results[index] = _rejected_result(
                action,
                reason_code="SCANNED_OUTSIDE_SESSION_WINDOW",
            )
            continue
        qr_candidates.append((index, action, attendance_session))
    return qr_candidates


async def _apply_actions(
    *,
    session: AsyncSession,
    claims: MobileAccessClaims,
    actions: Sequence[MobileAttendanceActionInput],
    resolved_results: dict[int, MobileAttendanceActionResult],
    prepared_by_index: dict[int, PreparedAttendanceAction],
    runtime: AttendanceRuntimeRegistrationModel | None,
    replay_snapshot: AttendanceReplaySnapshot,
    dependencies: MobileAttendanceActionDependencies,
) -> tuple[
    list[MobileAttendanceActionResult],
    list[tuple[PassportSubmissionModel, datetime]],
    dict[uuid.UUID, datetime],
]:
    results: list[MobileAttendanceActionResult] = []
    accepted_roster_changes: list[tuple[PassportSubmissionModel, datetime]] = []
    participated_sessions: dict[uuid.UUID, datetime] = {}
    for index, action in enumerate(actions):
        resolved_result = resolved_results.get(index)
        if resolved_result is not None:
            results.append(resolved_result)
            continue
        applied = await _apply_prepared_action(
            session=session,
            claims=claims,
            prepared=prepared_by_index[index],
            runtime=runtime,
            replay_snapshot=replay_snapshot,
            dependencies=dependencies,
        )
        results.append(applied.result)
        if applied.passenger_change is not None:
            accepted_roster_changes.append(applied.passenger_change)
        if applied.participated_at is not None:
            participated_sessions[prepared_by_index[index].attendance_session.id] = (
                applied.participated_at
            )
    return results, accepted_roster_changes, participated_sessions


async def _apply_prepared_action(
    *,
    session: AsyncSession,
    claims: MobileAccessClaims,
    prepared: PreparedAttendanceAction,
    runtime: AttendanceRuntimeRegistrationModel | None,
    replay_snapshot: AttendanceReplaySnapshot,
    dependencies: MobileAttendanceActionDependencies,
) -> _AppliedAttendanceAction:
    action = prepared.action
    client_event_id = str(action.client_event_id)
    replay_state = dependencies.replay_state_from_snapshot(
        replay_snapshot,
        attendance_session=prepared.attendance_session,
        passenger_id=prepared.passenger.id,
        client_event_id=client_event_id,
    )
    if replay_state == "event_reused":
        return _AppliedAttendanceAction(
            result=_rejected_result(action, reason_code="IDEMPOTENCY_KEY_REUSED")
        )
    if replay_state == "already_applied":
        return _AppliedAttendanceAction(
            result=_successful_result(action, status="already_applied"),
            participated_at=action.scanned_at,
        )

    inserted_id = await dependencies.insert_canonical_attendance_record(
        session=session,
        agency_id=claims.agency_id,
        attendance_session=prepared.attendance_session,
        passenger_id=prepared.passenger.id,
        coordinator_user_id=claims.principal_id,
        scanned_at=action.scanned_at.astimezone(UTC),
        sync_source="offline",
        client_event_id=client_event_id,
        device_id=str(claims.session_id),
        runtime_registration_id=runtime.id if runtime is not None else None,
    )
    if inserted_id is None:
        conflict_result = await _resolve_insert_conflict(
            session=session,
            claims=claims,
            prepared=prepared,
            replay_snapshot=replay_snapshot,
            dependencies=dependencies,
        )
        if conflict_result is not None:
            return _AppliedAttendanceAction(result=conflict_result)
    else:
        changed_at = datetime.now(tz=UTC)
        prepared.attendance_session.updated_at = changed_at
        passenger_change = (prepared.passenger, changed_at)

    record_attendance_replay(
        replay_snapshot,
        attendance_session=prepared.attendance_session,
        passenger_id=prepared.passenger.id,
        client_event_id=client_event_id,
    )
    return _AppliedAttendanceAction(
        result=_successful_result(
            action,
            status="accepted" if inserted_id is not None else "already_applied",
        ),
        passenger_change=passenger_change if inserted_id is not None else None,
        participated_at=action.scanned_at,
    )


async def _resolve_insert_conflict(
    *,
    session: AsyncSession,
    claims: MobileAccessClaims,
    prepared: PreparedAttendanceAction,
    replay_snapshot: AttendanceReplaySnapshot,
    dependencies: MobileAttendanceActionDependencies,
) -> MobileAttendanceActionResult | None:
    action = prepared.action
    replay_state = await dependencies.attendance_replay_state(
        session,
        claims=claims,
        attendance_session=prepared.attendance_session,
        passenger_id=prepared.passenger.id,
        client_event_id=str(action.client_event_id),
    )
    if replay_state == "event_reused":
        return _rejected_result(action, reason_code="IDEMPOTENCY_KEY_REUSED")
    if replay_state == "unknown":
        return MobileAttendanceActionResult(
            client_event_id=action.client_event_id,
            status="refresh_required",
            reason_code="ATTENDANCE_CONFLICT",
        )
    record_attendance_replay(
        replay_snapshot,
        attendance_session=prepared.attendance_session,
        passenger_id=prepared.passenger.id,
        client_event_id=str(action.client_event_id),
    )
    return None


async def _mark_runtime_participation(
    *,
    session: AsyncSession,
    claims: MobileAccessClaims,
    runtime: AttendanceRuntimeRegistrationModel | None,
    participated_sessions: dict[uuid.UUID, datetime],
    dependencies: MobileAttendanceActionDependencies,
) -> None:
    repository = dependencies.runtime_repository_factory(session)
    for participated_session_id, participated_at in participated_sessions.items():
        if runtime is None:
            raise RuntimeError("Native attendance runtime registration was incomplete")
        await repository.mark_participation(
            agency_id=claims.agency_id,
            session_id=participated_session_id,
            coordinator_user_id=claims.principal_id,
            runtime_registration_id=runtime.id,
            source="scan",
            occurred_at=participated_at,
        )


async def _append_targeted_roster_changes(
    *,
    session: AsyncSession,
    claims: MobileAccessClaims,
    group_id: uuid.UUID,
    trip: AuthorizedMobileTrip,
    accepted_roster_changes: Sequence[tuple[PassportSubmissionModel, datetime]],
    dependencies: MobileAttendanceActionDependencies,
) -> None:
    targeted_roster_changes: list[MobileSyncChangeModel] = []
    for passenger, changed_at in accepted_roster_changes:
        targeted_roster_changes.append(
            await dependencies.append_sync_change(
                session,
                access=trip.access,
                audience="coordinator",
                entity_type="coordinator_passenger",
                entity_id=passenger.id,
                operation="upsert",
                version=max(0, int(changed_at.timestamp() * 1000)),
                changed_by_user_id=claims.principal_id,
                payload={
                    "resource_path": (
                        f"/api/v1/mobile/coordinator/groups/{group_id}/passengers/{passenger.id}"
                    )
                },
                flush=False,
            )
        )
    if not targeted_roster_changes:
        return
    await session.flush()
    roster_revision = await dependencies.coordinator_roster_revision(
        session,
        agency_id=claims.agency_id,
        group_id=group_id,
    )
    for change in targeted_roster_changes:
        change.payload = {**change.payload, "roster_revision": roster_revision}
    await session.flush()


def _rejected_result(
    action: MobileAttendanceActionInput,
    *,
    reason_code: str,
) -> MobileAttendanceActionResult:
    return MobileAttendanceActionResult(
        client_event_id=action.client_event_id,
        status="rejected",
        reason_code=reason_code,
    )


def _successful_result(
    action: MobileAttendanceActionInput,
    *,
    status: Literal["accepted", "already_applied"],
) -> MobileAttendanceActionResult:
    return MobileAttendanceActionResult(
        client_event_id=action.client_event_id,
        status=status,
        server_version=None,
        reason_code=None,
    )


def record_attendance_replay(
    snapshot: AttendanceReplaySnapshot,
    *,
    attendance_session: AttendanceSessionModel,
    passenger_id: uuid.UUID,
    client_event_id: str,
) -> None:
    key = (attendance_session.id, client_event_id)
    snapshot.passengers.add((attendance_session.id, passenger_id))
    snapshot.event_passengers.setdefault(key, set()).add(passenger_id)


def attendance_rejection_code(value: str | None) -> str:
    return {
        "unknown_token": "QR_UNKNOWN",
        "revoked": "QR_REVOKED",
        "expired": "QR_EXPIRED",
        "inactive": "QR_INACTIVE",
        "wrong_group": "QR_WRONG_GROUP",
    }.get(value or "", "QR_INVALID")


__all__ = [
    "AttendanceReplaySnapshot",
    "MobileAttendanceActionDependencies",
    "PreparedAttendanceAction",
    "apply_mobile_attendance_action_batch",
    "attendance_rejection_code",
    "record_attendance_replay",
]
