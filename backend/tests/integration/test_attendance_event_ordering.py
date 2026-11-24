"""Real constraints must accept delayed events without reversing runtime history."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    AgencyModel,
    AttendanceDiscardTombstoneModel,
    AttendanceRuntimeRegistrationModel,
    AttendanceSessionModel,
    AttendanceSessionRuntimeParticipantModel,
    ClientGroupModel,
    UserModel,
)
from app.infrastructure.repositories.attendance_closeout_repository import (
    AttendanceCloseoutCounts,
    AttendanceCloseoutRepository,
)
from app.infrastructure.repositories.attendance_discard_repository import (
    AttendanceDiscardInput,
    AttendanceDiscardRepository,
)
from app.infrastructure.repositories.attendance_runtime_repository import (
    AttendanceRuntimeRepository,
)
from tests.persistence import persist_graph

NOW = datetime(2026, 10, 31, 10, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _sqlite_conflict_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Translate named PG targets only; execute real rows/checks/FKs unchanged."""
    original = Insert.on_conflict_do_update
    columns = {
        "uq_attendance_session_runtime_participant": ["session_id", "runtime_registration_id"],
        "uq_attendance_closeout_checkpoint_runtime": [
            "session_id",
            "coordinator_user_id",
            "runtime_registration_id",
        ],
    }

    def translated(statement, *args, **kwargs):
        constraint = kwargs.get("constraint")
        if constraint is not None:
            assert constraint in columns
            kwargs["index_elements"] = columns[kwargs.pop("constraint")]
        return original(statement, *args, **kwargs)

    monkeypatch.setattr(Insert, "on_conflict_do_update", translated)
    original_nothing = Insert.on_conflict_do_nothing

    def translated_nothing(statement, *args, **kwargs):
        constraint = kwargs.pop("constraint", None)
        assert constraint == "uq_attendance_discard_event"
        return original_nothing(
            statement,
            *args,
            index_elements=["agency_id", "coordinator_user_id", "discard_event_id"],
            **kwargs,
        )

    monkeypatch.setattr(Insert, "on_conflict_do_nothing", translated_nothing)


async def _seed(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    agency_id, coordinator_id, group_id, activity_id, runtime_id = (uuid.uuid4() for _ in range(5))
    await persist_graph(
        session,
        [
            AgencyModel(id=agency_id, name="Synthetic ordering", email="ordering@example.test"),
            UserModel(
                id=coordinator_id,
                agency_id=agency_id,
                email="coordinator-order@example.test",
                full_name="Synthetic coordinator",
                hashed_password="unused",
                role="agency_coordinator",
            ),
            ClientGroupModel(
                id=group_id, agency_id=agency_id, token=str(uuid.uuid4()), name="Synthetic trip"
            ),
            AttendanceSessionModel(
                id=activity_id,
                canonical_session_id=activity_id,
                agency_id=agency_id,
                group_id=group_id,
                created_by_user_id=coordinator_id,
                name="Boarding",
                normalized_name="boarding",
                status="active",
            ),
            AttendanceRuntimeRegistrationModel(
                id=runtime_id,
                agency_id=agency_id,
                coordinator_user_id=coordinator_id,
                runtime_kind="pwa",
                runtime_identifier_hash="a" * 64,
                status="active",
                registered_at=NOW - timedelta(days=1),
                last_seen_at=NOW,
                expires_at=NOW + timedelta(days=1),
            ),
        ],
    )
    return agency_id, coordinator_id, activity_id, runtime_id


async def _interval(session: AsyncSession, runtime_id: uuid.UUID) -> tuple[datetime, datetime]:
    # Select columns rather than a cached ORM identity after a native upsert.
    row = (
        await session.execute(
            select(
                AttendanceSessionRuntimeParticipantModel.first_participated_at,
                AttendanceSessionRuntimeParticipantModel.last_participated_at,
            ).where(AttendanceSessionRuntimeParticipantModel.runtime_registration_id == runtime_id)
        )
    ).one()
    return tuple(value.replace(tzinfo=UTC) for value in row)


@pytest.mark.parametrize(
    "offsets",
    [(0, -300), (-300, 0, -60), (0, 300, -300, 600)],
)
async def test_out_of_order_runtime_events_keep_earliest_and_latest_time(
    db_session: AsyncSession, offsets: tuple[int, ...]
) -> None:
    agency_id, coordinator_id, activity_id, runtime_id = await _seed(db_session)
    repository = AttendanceRuntimeRepository(db_session)
    for seconds in offsets:
        await repository.mark_participation(
            agency_id=agency_id,
            session_id=activity_id,
            coordinator_user_id=coordinator_id,
            runtime_registration_id=runtime_id,
            source="scan",
            occurred_at=NOW + timedelta(seconds=seconds),
        )
    assert await _interval(db_session, runtime_id) == (
        NOW + timedelta(seconds=min(offsets)),
        NOW + timedelta(seconds=max(offsets)),
    )


async def test_closeout_checkpoint_preserves_later_clock_skewed_scan_participation(
    db_session: AsyncSession,
) -> None:
    agency_id, coordinator_id, activity_id, runtime_id = await _seed(db_session)
    await AttendanceRuntimeRepository(db_session).mark_participation(
        agency_id=agency_id,
        session_id=activity_id,
        coordinator_user_id=coordinator_id,
        runtime_registration_id=runtime_id,
        source="scan",
        occurred_at=NOW + timedelta(minutes=1),
    )
    checkpoint = await AttendanceCloseoutRepository(db_session).publish(
        agency_id=agency_id,
        session_id=activity_id,
        coordinator_user_id=coordinator_id,
        runtime_registration_id=runtime_id,
        counts=AttendanceCloseoutCounts(0, 0, 0, 0, 0, None),
        reported_at=NOW,
    )
    assert checkpoint.pending_count == 0
    assert await _interval(db_session, runtime_id) == (NOW, NOW + timedelta(minutes=1))


@pytest.mark.parametrize("seconds", [-60, 60, 300])
async def test_allowed_discard_clock_skew_preserves_receipt_order_and_idempotency(
    db_session: AsyncSession, seconds: int
) -> None:
    agency_id, coordinator_id, activity_id, runtime_id = await _seed(db_session)
    group_id = await db_session.scalar(
        select(AttendanceSessionModel.group_id).where(AttendanceSessionModel.id == activity_id)
    )
    discarded_at = NOW + timedelta(seconds=seconds)
    captured_at = discarded_at - timedelta(seconds=30)
    item = AttendanceDiscardInput(
        discard_event_id=uuid.uuid4(),
        scan_reference="b" * 64,
        reason_category="operator_discard",
        discarded_at=discarded_at,
        captured_at=captured_at,
    )
    repository = AttendanceDiscardRepository(db_session)
    arguments = dict(
        agency_id=agency_id,
        group_id=group_id,
        session_id=activity_id,
        coordinator_user_id=coordinator_id,
        runtime_registration_id=runtime_id,
        items=(item,),
        retention_days=365,
    )
    receipt = await repository.record_batch(**arguments, now=NOW)
    assert receipt[0].status == "accepted"
    row = (await db_session.scalars(select(AttendanceDiscardTombstoneModel))).one()
    assert row.captured_at.replace(tzinfo=UTC) == min(captured_at, NOW)
    assert row.discarded_at.replace(tzinfo=UTC) == min(discarded_at, NOW)
    assert row.received_at.replace(tzinfo=UTC) == NOW
    retry = await repository.record_batch(**arguments, now=NOW + timedelta(minutes=10))
    assert retry[0].status == "already_applied"
    assert retry[0].received_at.replace(tzinfo=UTC) == NOW
