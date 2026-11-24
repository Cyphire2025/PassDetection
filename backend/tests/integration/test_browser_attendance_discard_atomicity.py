"""Caught discard conflicts must not commit evidence reported as rejected."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.security.mobile_jwt import hash_mobile_lookup
from app.infrastructure.database.models import (
    AgencyModel,
    AttendanceDiscardTombstoneModel,
    AttendanceRuntimeRegistrationModel,
    AttendanceSessionModel,
    AttendanceSessionRuntimeParticipantModel,
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
    UserModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.security.auth_cookies import ATTENDANCE_RUNTIME_COOKIE_NAME
from tests.dashboard_session_fixtures import issue_dashboard_access
from tests.persistence import persist_graph


@pytest.fixture(autouse=True)
def _sqlite_named_conflict_targets(monkeypatch):
    """Translate only named PG conflict targets; run real rows/checks/FKs."""
    ignore = Insert.on_conflict_do_nothing
    update = Insert.on_conflict_do_update

    def do_nothing(statement, *args, **kwargs):
        constraint = kwargs.pop("constraint", None)
        if constraint is not None:
            assert constraint == "uq_attendance_discard_event"
            kwargs["index_elements"] = ["agency_id", "coordinator_user_id", "discard_event_id"]
        return ignore(statement, *args, **kwargs)

    def do_update(statement, *args, **kwargs):
        constraint = kwargs.pop("constraint", None)
        if constraint is not None:
            targets = {
                "uq_attendance_session_runtime_participant": [
                    "session_id",
                    "runtime_registration_id",
                ],
                "uq_attendance_runtime_identifier": [
                    "agency_id",
                    "coordinator_user_id",
                    "runtime_identifier_hash",
                ],
            }
            assert constraint in targets
            kwargs["index_elements"] = targets[constraint]
        return update(statement, *args, **kwargs)

    monkeypatch.setattr(Insert, "on_conflict_do_nothing", do_nothing)
    monkeypatch.setattr(Insert, "on_conflict_do_update", do_update)


async def _cohort(session):
    now = datetime.now(UTC)
    agency, actor, runtime = (uuid.uuid4() for _ in range(3))
    groups = [uuid.uuid4(), uuid.uuid4()]
    activities = [uuid.uuid4(), uuid.uuid4()]
    secret = "r" * 43
    rows = [
        AgencyModel(id=agency, name="Synthetic discard", email=f"{agency}@example.test"),
        UserModel(
            id=actor,
            agency_id=agency,
            email=f"{actor}@example.test",
            full_name="Synthetic coordinator",
            hashed_password="unused",
            role="agency_coordinator",
            is_active=True,
        ),
        AttendanceRuntimeRegistrationModel(
            id=runtime,
            agency_id=agency,
            coordinator_user_id=actor,
            runtime_kind="pwa",
            runtime_identifier_hash=hash_mobile_lookup(secret, purpose="attendance-runtime-pwa"),
            status="active",
            registered_at=now,
            expires_at=now + timedelta(days=1),
        ),
    ]
    for group, activity in zip(groups, activities, strict=True):
        rows.extend(
            [
                ClientGroupModel(
                    id=group,
                    agency_id=agency,
                    name="Synthetic trip",
                    token=uuid.uuid4().hex,
                    status="active",
                    travel_date=now.date() + timedelta(days=1),
                ),
                CoordinatorGroupAssignmentModel(
                    id=uuid.uuid4(),
                    agency_id=agency,
                    group_id=group,
                    coordinator_user_id=actor,
                    active=True,
                    assigned_at=now - timedelta(hours=1),
                ),
                AttendanceSessionModel(
                    id=activity,
                    canonical_session_id=activity,
                    agency_id=agency,
                    group_id=group,
                    name="Synthetic boarding",
                    normalized_name="synthetic boarding",
                    status="active",
                    created_by_user_id=actor,
                    started_at=now - timedelta(minutes=10),
                ),
            ]
        )
    await persist_graph(session, rows)
    access, _ = await issue_dashboard_access(
        session, user_id=actor, agency_id=agency, role="agency_coordinator"
    )
    await session.commit()
    return SimpleNamespace(
        now=now,
        agency=agency,
        actor=actor,
        runtime=runtime,
        groups=groups,
        activities=activities,
        access=access,
        secret=secret,
    )


def _item(f, event, *, index=0, reference="b" * 64):
    return dict(
        discard_event_id=str(event),
        group_id=str(f.groups[index]),
        session_id=str(f.activities[index]),
        scan_reference=reference,
        reason_category="operator_discard",
        captured_at=(f.now - timedelta(minutes=1)).isoformat(),
        discarded_at=f.now.isoformat(),
    )


async def _existing_receipt(session, f, event, *, index):
    session.add(
        AttendanceDiscardTombstoneModel(
            id=uuid.uuid4(),
            agency_id=f.agency,
            group_id=f.groups[index],
            session_id=f.activities[index],
            coordinator_user_id=f.actor,
            runtime_registration_id=f.runtime,
            discard_event_id=event,
            scan_reference="a" * 64,
            reason_category="operator_discard",
            captured_at=f.now - timedelta(minutes=1),
            discarded_at=f.now,
            received_at=f.now,
            status="accepted",
            retention_expires_at=f.now + timedelta(days=365),
            updated_at=f.now,
        )
    )
    await session.commit()


def _commit_requests(client, session, monkeypatch):
    # Production commits successful request dependencies. The ordinary client
    # fixture intentionally does not, so restore that boundary for this proof.
    async def committing_session():
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise

    monkeypatch.setitem(
        client._transport.app.dependency_overrides, get_db_session, committing_session
    )


async def _post(client, f, items):
    client.cookies.set(ATTENDANCE_RUNTIME_COOKIE_NAME, f"v1.pwa.{f.secret}")
    response = await client.post(
        "/api/v1/tour-operations/coordinator/attendance/discards",
        headers={"Authorization": f"Bearer {f.access}"},
        json={"items": items},
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


@pytest.mark.parametrize("independent_group", [False, True])
async def test_rejected_discard_group_cannot_commit_new_evidence(
    client,
    db_session,
    monkeypatch,
    independent_group,
):
    f = await _cohort(db_session)
    conflict, fresh = uuid.uuid4(), uuid.uuid4()
    rejected_index = int(independent_group)
    await _existing_receipt(db_session, f, conflict, index=rejected_index)
    _commit_requests(client, db_session, monkeypatch)
    replies = await _post(client, f, [_item(f, fresh), _item(f, conflict, index=rejected_index)])
    assert [item["status"] for item in replies] == (
        ["accepted", "rejected"] if independent_group else ["rejected", "rejected"]
    )
    sessions = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with sessions() as independent_reader:
        receipts = list(
            (await independent_reader.scalars(select(AttendanceDiscardTombstoneModel))).all()
        )
        expected_events = {conflict, fresh} if independent_group else {conflict}
        assert {row.discard_event_id for row in receipts} == expected_events
        original = next(row for row in receipts if row.discard_event_id == conflict)
        assert original.scan_reference == "a" * 64
        participants = list(
            (
                await independent_reader.scalars(select(AttendanceSessionRuntimeParticipantModel))
            ).all()
        )
        assert [row.session_id for row in participants] == (
            [f.activities[0]] if independent_group else []
        )


async def test_successful_discard_and_exact_replay_preserve_durable_receipt(
    client, db_session, monkeypatch
):
    f = await _cohort(db_session)
    event = uuid.uuid4()
    _commit_requests(client, db_session, monkeypatch)
    first = (await _post(client, f, [_item(f, event)]))[0]
    replay = (await _post(client, f, [_item(f, event)]))[0]
    assert first["status"] == "accepted" and replay["status"] == "already_applied"
    assert first["received_at"] == replay["received_at"]
    sessions = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with sessions() as independent_reader:
        receipts = list(
            (await independent_reader.scalars(select(AttendanceDiscardTombstoneModel))).all()
        )
        assert len(receipts) == 1 and receipts[0].discard_event_id == event
        participants = list(
            (
                await independent_reader.scalars(select(AttendanceSessionRuntimeParticipantModel))
            ).all()
        )
        assert len(participants) == 1 and participants[0].session_id == f.activities[0]
