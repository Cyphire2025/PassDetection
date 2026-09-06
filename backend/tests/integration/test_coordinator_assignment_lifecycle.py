from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.infrastructure.database.models import (
    AgencyModel,
    AttendanceRecordModel,
    AuditLogModel,
    ClientGroupModel,
    CoordinatorAssignmentModel,
    CoordinatorGroupAssignmentModel,
    PassportSubmissionModel,
    StorageCleanupJobModel,
)
from app.infrastructure.repositories.coordinator_assignment_lifecycle import (
    current_trip_clause,
    expire_coordinator_assignments,
    expired_trip_clause,
)
from tests.sqlite_trip_timezone import register_sqlite_trip_timezone

NOW = datetime(2026, 9, 5, 19, tzinfo=UTC)  # 6 September in Kolkata, 5th in LA.


async def seed_groups(session: AsyncSession) -> tuple[list[ClientGroupModel], list[uuid.UUID]]:
    await register_sqlite_trip_timezone(session)
    agency_id, coordinator_id = uuid.uuid4(), uuid.uuid4()
    session.add(AgencyModel(id=agency_id, name="Expiry test", email="expiry@example.com"))
    cases = [
        ("ended", date(2026, 9, 1), date(2026, 9, 5), "Asia/Kolkata"),
        ("fallback-ended", date(2026, 9, 5), None, "Asia/Kolkata"),
        ("in-progress", date(2026, 9, 1), date(2026, 9, 7), "Asia/Kolkata"),
        ("today", date(2026, 9, 6), None, "Asia/Kolkata"),
        ("upcoming", date(2026, 9, 8), date(2026, 9, 10), "Asia/Kolkata"),
        ("undated", None, None, "Asia/Kolkata"),
        ("still-local-return-day", date(2026, 9, 1), date(2026, 9, 5), "America/Los_Angeles"),
    ]
    groups, submission_ids = [], []
    for name, travel_date, return_date, timezone in cases:
        group = ClientGroupModel(
            id=uuid.uuid4(),
            agency_id=agency_id,
            token=str(uuid.uuid4()),
            name=name,
            travel_date=travel_date,
            return_date=return_date,
            timezone=timezone,
            status="active",
            passport_legal_hold=True,
            passport_legal_hold_reason="Keep documents",
            passport_legal_hold_set_at=NOW - timedelta(days=1),
        )
        submission_id = uuid.uuid4()
        session.add_all(
            [
                group,
                PassportSubmissionModel(
                    id=submission_id,
                    agency_id=agency_id,
                    group_id=group.id,
                    client_name="Test Passenger",
                    image_s3_key=f"test/{submission_id}.jpg",
                ),
                CoordinatorGroupAssignmentModel(
                    id=uuid.uuid4(),
                    agency_id=agency_id,
                    group_id=group.id,
                    coordinator_user_id=coordinator_id,
                    active=True,
                ),
                CoordinatorAssignmentModel(
                    id=uuid.uuid4(),
                    agency_id=agency_id,
                    group_id=group.id,
                    coordinator_user_id=coordinator_id,
                    passenger_id=submission_id,
                    active=True,
                ),
                AttendanceRecordModel(
                    id=uuid.uuid4(),
                    agency_id=agency_id,
                    session_id=uuid.uuid4(),
                    passenger_id=submission_id,
                    coordinator_user_id=coordinator_id,
                    scanned_at=NOW - timedelta(days=1),
                    client_event_id=str(uuid.uuid4()),
                ),
            ]
        )
        groups.append(group)
        submission_ids.append(submission_id)
    await session.flush()
    return groups, submission_ids


async def test_date_clauses_match_trip_timezone_and_keep_undated_access(
    db_session: AsyncSession,
) -> None:
    await seed_groups(db_session)
    ended = set(
        (
            await db_session.scalars(select(ClientGroupModel.name).where(expired_trip_clause(NOW)))
        ).all()
    )
    current = set(
        (
            await db_session.scalars(select(ClientGroupModel.name).where(current_trip_clause(NOW)))
        ).all()
    )
    still_authorized = set(
        (
            await db_session.scalars(select(ClientGroupModel.name).where(~expired_trip_clause(NOW)))
        ).all()
    )
    assert ended == {"ended", "fallback-ended"}
    assert current == {"in-progress", "today", "upcoming", "still-local-return-day"}
    assert still_authorized == current | {"undated"}


async def test_expiry_is_bounded_idempotent_and_preserves_every_history_row(
    db_session: AsyncSession,
) -> None:
    groups, submission_ids = await seed_groups(db_session)
    old_unassigned = NOW - timedelta(days=2)
    historic = CoordinatorGroupAssignmentModel(
        id=uuid.uuid4(),
        agency_id=groups[0].agency_id,
        group_id=groups[0].id,
        coordinator_user_id=uuid.uuid4(),
        active=False,
        unassigned_at=old_unassigned,
    )
    db_session.add(historic)
    await db_session.flush()
    first = await expire_coordinator_assignments(db_session, now=NOW, batch_size=1)
    assert first.as_dict() == {"groups": 1, "group_assignments": 1, "passenger_assignments": 1}
    second = await expire_coordinator_assignments(db_session, now=NOW, batch_size=1)
    assert second == first
    assert (await expire_coordinator_assignments(db_session, now=NOW)).as_dict() == {
        "groups": 0,
        "group_assignments": 0,
        "passenger_assignments": 0,
    }
    await db_session.flush()
    for model in (CoordinatorGroupAssignmentModel, CoordinatorAssignmentModel):
        rows = list((await db_session.scalars(select(model))).all())
        expected = len(groups) + (model is CoordinatorGroupAssignmentModel)
        assert len(rows) == expected
        for row in rows:
            if row.id == historic.id:
                assert row.active is False
                assert row.unassigned_at == old_unassigned
            elif row.group_id in {groups[0].id, groups[1].id}:
                assert row.active is False
                assert row.unassigned_at.replace(tzinfo=UTC) == NOW
            else:
                assert row.active is True
                assert row.unassigned_at is None
    assert len((await db_session.scalars(select(ClientGroupModel))).all()) == len(groups)
    assert len((await db_session.scalars(select(AttendanceRecordModel))).all()) == len(groups)
    for group in groups:
        await db_session.refresh(group)
        assert group.status == "active" and group.closed_at is None
        assert group.passport_legal_hold is True
    for submission_id in submission_ids:
        submission = await db_session.get(PassportSubmissionModel, submission_id)
        assert submission is not None and submission.image_s3_key == f"test/{submission_id}.jpg"
    assert await db_session.scalar(select(func.count()).select_from(StorageCleanupJobModel)) == 0
    audits = list((await db_session.scalars(select(AuditLogModel))).all())
    assert len(audits) == 2
    assert {audit.action for audit in audits} == {"coordinator_assignments_expired"}


async def test_legacy_passenger_assignments_expire_without_a_group_assignment(
    db_session: AsyncSession,
) -> None:
    await seed_groups(db_session)
    await db_session.execute(update(CoordinatorGroupAssignmentModel).values(active=False))
    result = await expire_coordinator_assignments(db_session, now=NOW)
    assert result.groups == 2
    assert result.group_assignments == 0
    assert result.passenger_assignments == 2


async def test_sql_checks_use_the_same_instant_for_different_input_offsets(
    db_session: AsyncSession,
) -> None:
    await seed_groups(db_session)
    for timestamp in (NOW, NOW.astimezone(ZoneInfo("Pacific/Kiritimati"))):
        ended = set(
            (
                await db_session.scalars(
                    select(ClientGroupModel.name).where(expired_trip_clause(timestamp))
                )
            ).all()
        )
        assert ended == {"ended", "fallback-ended"}


def test_alias_sql_is_correlated_and_uses_canonical_timezone() -> None:
    group = aliased(ClientGroupModel, name="visible_group")
    sql = str(
        select(group.id)
        .where(expired_trip_clause(NOW, group_model=group))
        .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "coalesce(visible_group.return_date, visible_group.travel_date)" in sql
    assert "timezone(coalesce(nullif(trim(visible_group.timezone)" in sql
    assert "Asia/Kolkata" in sql
    assert "FROM client_groups AS visible_group" in sql


@pytest.mark.parametrize("batch_size", [0, -1, 101])
async def test_expiry_rejects_unbounded_batch_sizes(
    db_session: AsyncSession, batch_size: int
) -> None:
    with pytest.raises(ValueError, match="batch_size"):
        await expire_coordinator_assignments(db_session, now=NOW, batch_size=batch_size)
