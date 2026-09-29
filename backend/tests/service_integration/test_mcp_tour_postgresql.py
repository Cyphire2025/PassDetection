"""PostgreSQL additive tour/GC races on guarded disposable local resources."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import date

import pytest
from sqlalchemy import func, select

from app.application.mcp.operations import MCPOperationService
from app.infrastructure.database.gc_mobile_models import GCGroupAccessModel, GCItineraryVersionModel
from app.infrastructure.database.models import (
    AgencyModel,
    AttendanceRecordModel,
    AttendanceSessionModel,
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
    UserModel,
)
from app.presentation.mcp.invocation import MCPInputError
from app.presentation.mcp.tour_change_tools import itinerary_definition, tour_definition
from tests.service_integration.test_mcp_concurrency_postgresql import mcp_sessions as mcp_sessions
from tests.service_integration.test_mcp_operations_postgresql import (
    operation_sessions as operation_sessions,
)

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1",
        reason="isolated PostgreSQL required",
    ),
]


@pytest.fixture
async def tour_sessions(operation_sessions):
    sessions, settings, actor_id, _, tokens = operation_sessions
    async with sessions() as session:
        agency = AgencyModel(
            id=uuid.uuid4(), name="Synthetic tour", email=f"{uuid.uuid4()}@example.test"
        )
        session.add(agency)
        await session.flush()
        group = ClientGroupModel(
            id=uuid.uuid4(),
            agency_id=agency.id,
            name="Synthetic tour",
            token=uuid.uuid4().hex,
            travel_date=date(2030, 1, 1),
            return_date=date(2030, 1, 5),
        )
        coordinator = UserModel(
            id=uuid.uuid4(),
            agency_id=agency.id,
            role="agency_coordinator",
            is_active=True,
            full_name="Synthetic coordinator",
            email=f"{uuid.uuid4()}@example.test",
            hashed_password="fixture",
        )
        session.add_all([group, coordinator])
        await session.flush()
        access = GCGroupAccessModel(
            id=uuid.uuid4(),
            agency_id=agency.id,
            group_id=group.id,
            is_enabled=True,
            passenger_access_enabled=True,
        )
        session.add(access)
        await session.flush()
        scope = {"agency_id": str(agency.id), "group_id": str(group.id)}
        payloads = {
            "add_group_coordinators": {**scope, "coordinator_ids": [str(coordinator.id)]},
            "create_attendance_activity": {
                **scope,
                "name": "Museum visit",
                "scheduled_starts_at": "2030-01-02T10:00:00+09:00",
                "scheduled_ends_at": "2030-01-02T12:00:00+09:00",
                "schedule_timezone": "Asia/Tokyo",
            },
            "create_gc_itinerary_draft": {
                **scope,
                "title": "Retained trip",
                "expected_access_revision": access.revision,
                "days": [{"day_number": 1, "items": [{"title": "Arrival"}]}],
            },
        }
        await session.commit()
    return sessions, settings, tokens, payloads, group.id, coordinator.id, actor_id


async def invoke(fixture, kind, *, index=0, key="pg-tour-creation-001", payload=None):
    async with fixture[0]() as session:
        definition = (
            itinerary_definition() if kind == "create_gc_itinerary_draft" else tour_definition(kind)
        )
        service = MCPOperationService(session, fixture[1], [definition])
        try:
            result = await service.execute(
                access_token=fixture[2][index],
                operation_name=kind,
                idempotency_key=key,
                payload=fixture[3][kind] if payload is None else payload,
            )
            await session.commit()
            return result
        except BaseException:
            await session.rollback()
            raise


@pytest.mark.parametrize(
    "kind,model",
    [
        ("add_group_coordinators", CoordinatorGroupAssignmentModel),
        ("create_attendance_activity", AttendanceSessionModel),
        ("create_gc_itinerary_draft", GCItineraryVersionModel),
    ],
)
async def test_six_cross_connection_retries_create_one_entity(tour_sessions, kind, model):
    fixture = tour_sessions
    results = await asyncio.wait_for(
        asyncio.gather(*(invoke(fixture, kind, index=index % 2) for index in range(6))), 20
    )
    assert all(result == results[0] for result in results)
    async with fixture[0]() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(model).where(model.group_id == fixture[4])
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AttendanceRecordModel)
                .where(AttendanceRecordModel.agency_id == uuid.UUID(fixture[3][kind]["agency_id"]))
            )
            == 0
        )


async def test_distinct_membership_intents_retain_inactive_history_and_add_once(tour_sessions):
    fixture = tour_sessions
    async with fixture[0]() as session:
        old = CoordinatorGroupAssignmentModel(
            agency_id=uuid.UUID(fixture[3]["add_group_coordinators"]["agency_id"]),
            group_id=fixture[4],
            coordinator_user_id=fixture[5],
            assigned_by_user_id=fixture[6],
            active=False,
        )
        session.add(old)
        await session.flush()
        old_id = old.id
        await session.commit()
    results = await asyncio.wait_for(
        asyncio.gather(
            invoke(fixture, "add_group_coordinators", key="first-member-intent-001"),
            invoke(fixture, "add_group_coordinators", index=1, key="second-member-intent-002"),
        ),
        20,
    )
    assert sorted(len(result["data"]["added_assignment_ids"]) for result in results) == [0, 1]
    async with fixture[0]() as session:
        assert (await session.get(CoordinatorGroupAssignmentModel, old_id)).active is False
        assert (
            await session.scalar(
                select(func.count())
                .select_from(CoordinatorGroupAssignmentModel)
                .where(CoordinatorGroupAssignmentModel.group_id == fixture[4])
            )
            == 2
        )


async def test_distinct_itinerary_intents_at_same_revision_have_one_winner(tour_sessions):
    fixture = tour_sessions
    results = await asyncio.wait_for(
        asyncio.gather(
            invoke(fixture, "create_gc_itinerary_draft", key="first-draft-intent-001"),
            invoke(fixture, "create_gc_itinerary_draft", index=1, key="second-draft-intent-002"),
            return_exceptions=True,
        ),
        20,
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    assert (
        sum(
            isinstance(result, MCPInputError) and result.code == "tour_creation_conflict"
            for result in results
        )
        == 1
    )


async def test_same_activity_name_distinct_intents_never_rewrite_schedule(tour_sessions):
    fixture = tour_sessions
    results = await asyncio.wait_for(
        asyncio.gather(
            invoke(fixture, "create_attendance_activity", key="first-activity-intent-001"),
            invoke(
                fixture, "create_attendance_activity", index=1, key="second-activity-intent-002"
            ),
        ),
        20,
    )
    assert {result["data"]["outcome"] for result in results} == {"created", "existing"}
    assert len({result["data"]["activity_id"] for result in results}) == 1
    payload = {
        **fixture[3]["create_attendance_activity"],
        "scheduled_ends_at": "2030-01-02T13:00:00+09:00",
    }
    with pytest.raises(MCPInputError, match="Current state"):
        await invoke(
            fixture,
            "create_attendance_activity",
            key="conflicting-schedule-intent",
            payload=payload,
        )
