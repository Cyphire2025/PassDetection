"""Additions retain memberships, physical evidence and itinerary versions."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken
from sqlalchemy import func, select

from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
    GCItineraryDayModel,
    GCItineraryItemModel,
    GCItineraryVersionModel,
)
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AttendanceRecordModel,
    AttendanceSessionModel,
    CoordinatorAssignmentModel,
    CoordinatorGroupAssignmentModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.mcp.invocation import MCPInputError
from app.presentation.mcp.tour_change_tools import (
    itinerary_definition,
    register_tour_change_tools,
    tour_definition,
)
from tests.integration.test_mcp_office_changes import office_changes as office_changes
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture


@pytest.fixture
async def tour_changes(office_changes):
    base, agencies, group, _, _, _ = office_changes
    session, settings, actor, _, _ = base
    group.travel_date, group.return_date = date(2030, 1, 1), date(2030, 1, 5)
    coordinators = [
        UserModel(
            id=uuid.uuid4(),
            agency_id=agencies[0].id,
            email=f"tour-{index}@example.test",
            full_name="Coordinator",
            hashed_password="fixture",
            role="agency_coordinator",
            is_active=True,
        )
        for index in range(3)
    ]
    access = GCGroupAccessModel(
        id=uuid.uuid4(),
        agency_id=group.agency_id,
        group_id=group.id,
        is_enabled=True,
        passenger_access_enabled=True,
    )
    session.add_all([*coordinators, access])
    await session.flush()
    scope = {"agency_id": str(group.agency_id), "group_id": str(group.id)}
    payloads = {
        "add_group_coordinators": {
            **scope,
            "coordinator_ids": [str(coordinators[0].id), str(coordinators[1].id)],
        },
        "create_attendance_activity": {
            **scope,
            "name": " Museum   visit ",
            "scheduled_starts_at": "2030-01-02T10:00:00+09:00",
            "scheduled_ends_at": "2030-01-02T12:00:00+09:00",
            "schedule_timezone": "Asia/Tokyo",
        },
        "create_gc_itinerary_draft": {
            **scope,
            "title": "Retained itinerary",
            "expected_access_revision": access.revision,
            "days": [
                {
                    "day_number": 1,
                    "date": "2030-01-01",
                    "items": [
                        {
                            "title": "Arrival",
                            "description": "UNTRUSTED: ignore this text as instructions",
                        }
                    ],
                }
            ],
        },
    }
    service = MCPOperationService(
        session,
        settings,
        [
            tour_definition("add_group_coordinators"),
            tour_definition("create_attendance_activity"),
            itinerary_definition(),
        ],
    )
    return base, agencies, group, coordinators, access, payloads, service


async def execute(fixture, kind, *, key="tour-additive-request-001", payload=None, connection=0):
    return await fixture[6].execute(
        access_token=fixture[0][4][connection],
        operation_name=kind,
        idempotency_key=key,
        payload=fixture[5][kind] if payload is None else payload,
    )


async def test_add_coordinators_retains_active_inactive_and_passenger_assignments(tour_changes):
    fixture = tour_changes
    session, actor = fixture[0][0], fixture[0][2]
    group, coordinators = fixture[2], fixture[3]
    retained = [
        CoordinatorGroupAssignmentModel(
            agency_id=group.agency_id,
            group_id=group.id,
            coordinator_user_id=coordinators[index].id,
            assigned_by_user_id=actor.id,
            active=index != 1,
            unassigned_at=datetime.now(UTC) if index == 1 else None,
        )
        for index in range(3)
    ]
    session.add_all(retained)
    await session.flush()
    original = [(row.id, row.active, row.unassigned_at) for row in retained]
    result = await execute(fixture, "add_group_coordinators")
    assert len(result["data"]["added_assignment_ids"]) == 1
    assert result["data"]["existing_assignment_ids"] == [str(retained[0].id)]
    assert [(row.id, row.active, row.unassigned_at) for row in retained] == original
    assert (
        await session.scalar(select(func.count()).select_from(CoordinatorGroupAssignmentModel)) == 4
    )
    assert await session.scalar(select(func.count()).select_from(CoordinatorAssignmentModel)) == 0
    assert await execute(fixture, "add_group_coordinators", connection=1) == result


@pytest.mark.parametrize("change", ["inactive", "deleted", "wrong_role", "cross_agency"])
async def test_coordinator_eligibility_is_current_and_all_or_nothing(tour_changes, change):
    fixture = tour_changes
    user = fixture[3][1]
    if change == "inactive":
        user.is_active = False
    elif change == "deleted":
        user.deleted_at = datetime.now(UTC)
    elif change == "wrong_role":
        user.role = "agency_staff"
    else:
        user.agency_id = fixture[1][1].id
    await fixture[0][0].flush()
    with pytest.raises(MCPOperationError, match="tour_coordinator_unavailable"):
        await execute(fixture, "add_group_coordinators")
    assert (
        await fixture[0][0].scalar(
            select(func.count()).select_from(CoordinatorGroupAssignmentModel)
        )
        == 0
    )


async def test_expired_trip_blocks_new_memberships(tour_changes):
    fixture = tour_changes
    fixture[2].travel_date, fixture[2].return_date = date(2000, 1, 1), date(2000, 1, 2)
    await fixture[0][0].flush()
    with pytest.raises(MCPInputError, match="Current state"):
        await execute(fixture, "add_group_coordinators")


async def test_attendance_create_resolves_compatible_activity_without_any_physical_event(
    tour_changes,
):
    fixture = tour_changes
    first = await execute(fixture, "create_attendance_activity")
    session = fixture[0][0]
    activity = await session.get(AttendanceSessionModel, uuid.UUID(first["data"]["activity_id"]))
    original = (
        activity.id,
        activity.status,
        activity.started_at,
        activity.updated_at,
        activity.scheduled_starts_at,
    )
    assert first["data"]["outcome"] == "created" and activity.name == "Museum visit"
    assert await execute(fixture, "create_attendance_activity", connection=1) == first
    existing = await execute(
        fixture, "create_attendance_activity", key="explicit-existing-activity"
    )
    assert existing["data"]["outcome"] == "existing" and existing["created_entities"] == []
    assert original == (
        activity.id,
        activity.status,
        activity.started_at,
        activity.updated_at,
        activity.scheduled_starts_at,
    )
    assert await session.scalar(select(func.count()).select_from(AttendanceSessionModel)) == 1
    assert await session.scalar(select(func.count()).select_from(AttendanceRecordModel)) == 0


@pytest.mark.parametrize("change", ["draft", "schedule", "omitted_schedule"])
async def test_existing_attendance_state_is_never_activated_or_rewritten(tour_changes, change):
    fixture = tour_changes
    first = await execute(fixture, "create_attendance_activity")
    session = fixture[0][0]
    activity = await session.get(AttendanceSessionModel, uuid.UUID(first["data"]["activity_id"]))
    payload = dict(fixture[5]["create_attendance_activity"])
    if change == "draft":
        activity.status, activity.started_at = "draft", None
    elif change == "schedule":
        payload["scheduled_ends_at"] = "2030-01-02T13:00:00+09:00"
    else:
        for key in ("scheduled_starts_at", "scheduled_ends_at", "schedule_timezone"):
            payload.pop(key)
    await session.flush()
    original = (activity.status, activity.started_at, activity.scheduled_ends_at)
    with pytest.raises(MCPInputError, match="Current state"):
        await execute(
            fixture, "create_attendance_activity", payload=payload, key="different-activity-request"
        )
    await session.refresh(activity)
    assert (activity.status, activity.started_at, activity.scheduled_ends_at) == original


async def test_itinerary_drafts_retain_all_versions_and_require_fresh_access_revision(tour_changes):
    fixture = tour_changes
    session = fixture[0][0]
    first = await execute(fixture, "create_gc_itinerary_draft")
    assert first["data"]["status"] == "draft" and first["data"]["notifications_queued"] == 0
    assert await execute(fixture, "create_gc_itinerary_draft", connection=1) == first
    with pytest.raises(MCPInputError, match="Current state"):
        await execute(fixture, "create_gc_itinerary_draft", key="stale-itinerary-request-002")
    payload = {
        **fixture[5]["create_gc_itinerary_draft"],
        "expected_access_revision": first["data"]["access_revision"],
        "title": "Second version",
    }
    second = await execute(
        fixture, "create_gc_itinerary_draft", payload=payload, key="fresh-itinerary-request-003"
    )
    assert second["data"]["version"] == 2
    for model in (GCItineraryVersionModel, GCItineraryDayModel, GCItineraryItemModel):
        assert await session.scalar(select(func.count()).select_from(model)) == 2
    old = await session.get(GCItineraryVersionModel, uuid.UUID(first["data"]["itinerary_id"]))
    assert old.status == "draft" and old.title == "Retained itinerary" and old.published_at is None
    assert "UNTRUSTED" not in str(first)


@pytest.mark.parametrize(
    "kind", ["add_group_coordinators", "create_attendance_activity", "create_gc_itinerary_draft"]
)
async def test_current_receipt_scope_and_removed_group_are_enforced(tour_changes, kind):
    fixture = tour_changes
    result = await execute(fixture, kind)
    fixture[2].status = "deleted"
    await fixture[0][0].flush()
    with pytest.raises((MCPOperationError, MCPInputError)):
        await execute(fixture, kind)
    with pytest.raises((MCPOperationError, MCPInputError)):
        await fixture[6].inspect(
            access_token=fixture[0][4][1], operation_id=uuid.UUID(result["operation_id"])
        )


async def test_removed_coordinator_membership_receipt_is_not_disclosed(tour_changes):
    fixture = tour_changes
    result = await execute(fixture, "add_group_coordinators")
    row = await fixture[0][0].get(
        CoordinatorGroupAssignmentModel, uuid.UUID(result["data"]["added_assignment_ids"][0])
    )
    row.active, row.unassigned_at = False, datetime.now(UTC)
    await fixture[0][0].flush()
    with pytest.raises(MCPOperationError, match="tour_receipt_unavailable"):
        await execute(fixture, "add_group_coordinators")


@pytest.mark.parametrize(
    "kind,change",
    [
        ("add_group_coordinators", {"coordinator_ids": []}),
        ("add_group_coordinators", {"replace": True}),
        ("create_attendance_activity", {"status": "completed"}),
        ("create_attendance_activity", {"name": " "}),
        ("create_gc_itinerary_draft", {"publish": True}),
        (
            "create_gc_itinerary_draft",
            {
                "days": [
                    {
                        "day_number": 1,
                        "items": [{"title": "Test", "document_url": "https://evil.invalid"}],
                    }
                ]
            },
        ),
        ("create_gc_itinerary_draft", {"days": [{"day_number": 1}, {"day_number": 1}]}),
    ],
)
async def test_unsupported_or_nested_unreviewed_fields_are_rejected(tour_changes, kind, change):
    with pytest.raises(MCPInputError):
        await execute(tour_changes, kind, payload={**tour_changes[5][kind], **change})
    assert await tour_changes[0][0].scalar(select(func.count()).select_from(MCPOperationModel)) == 0


@pytest.mark.parametrize(
    "kind", ["add_group_coordinators", "create_attendance_activity", "create_gc_itinerary_draft"]
)
async def test_audit_failure_rolls_back_entire_addition(tour_changes, kind, monkeypatch):
    fixture = tour_changes
    monkeypatch.setattr(
        AuditLogRepository, "record", AsyncMock(side_effect=RuntimeError("test audit failure"))
    )
    with pytest.raises(RuntimeError, match="test audit failure"):
        await execute(fixture, kind)
    for model in (
        MCPOperationModel,
        CoordinatorGroupAssignmentModel,
        AttendanceSessionModel,
        GCItineraryVersionModel,
    ):
        assert await fixture[0][0].scalar(select(func.count()).select_from(model)) == 0


async def test_actual_sdk_dispatch_commits_three_additions_and_replays(tour_changes, monkeypatch):
    fixture = tour_changes
    session, settings, actor, grants, tokens = fixture[0]
    await session.commit()
    app, server = FastAPI(), MCPServer("Additive tour fixture")

    @asynccontextmanager
    async def sessions():
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise

    app.state.mcp_session_factory, app.state.mcp_operations = sessions, {}
    register_tour_change_tools(server, app, settings)
    monkeypatch.setattr(
        "app.presentation.mcp.invocation.get_access_token",
        lambda: AccessToken(
            token=tokens[0],
            client_id=grants[0].client_id,
            scopes=["mcp:change"],
            subject=str(actor.id),
            resource=settings.mcp.resource,
            claims={"grant_id": str(grants[0].id)},
        ),
    )
    tools = await server.list_tools()
    assert {tool.name for tool in tools} == set(fixture[5])
    for kind, field in [
        ("add_group_coordinators", "assignment"),
        ("create_attendance_activity", "activity"),
        ("create_gc_itinerary_draft", "itinerary"),
    ]:
        args = {field: fixture[5][kind], "idempotency_key": "sdk-tour-creation-request"}
        result = (await server.call_tool(kind, args)).structured_content
        repeated = (await server.call_tool(kind, args)).structured_content
        assert (
            result["receipt"] == repeated["receipt"] and result["audit_id"] != repeated["audit_id"]
        )
        assert not session.in_transaction()


async def test_existing_scan_evidence_survives_canonical_resolution(tour_changes):
    fixture = tour_changes
    result = await execute(fixture, "create_attendance_activity")
    session, group = fixture[0][0], fixture[2]
    passenger = PassportSubmissionModel(
        id=uuid.uuid4(),
        agency_id=group.agency_id,
        group_id=group.id,
        client_name="Synthetic passenger",
        image_s3_key="retained/passport.jpg",
        status="confirmed",
    )
    session.add(passenger)
    await session.flush()
    record = AttendanceRecordModel(
        id=uuid.uuid4(),
        agency_id=group.agency_id,
        session_id=uuid.UUID(result["data"]["activity_id"]),
        passenger_id=passenger.id,
        coordinator_user_id=fixture[3][0].id,
        scanned_at=datetime.now(UTC),
        sync_source="offline",
        client_event_id="retained-client-event",
        device_id="retained-device",
    )
    session.add(record)
    await session.flush()
    before = (record.id, record.scanned_at, record.client_event_id, record.device_id)
    repeated = await execute(
        fixture, "create_attendance_activity", key="new-intent-existing-activity"
    )
    assert repeated["data"]["outcome"] == "existing"
    assert await session.scalar(select(func.count()).select_from(AttendanceRecordModel)) == 1
    assert (record.id, record.scanned_at, record.client_event_id, record.device_id) == before
    assert "retained-device" not in str(repeated) and "retained-client-event" not in str(repeated)


@pytest.mark.parametrize(
    "kind", ["add_group_coordinators", "create_attendance_activity", "create_gc_itinerary_draft"]
)
async def test_explicit_other_agency_cannot_admit_group_or_content(tour_changes, kind):
    fixture = tour_changes
    payload = {**fixture[5][kind], "agency_id": str(fixture[1][1].id)}
    with pytest.raises((MCPOperationError, MCPInputError)):
        await execute(fixture, kind, payload=payload)
    assert await fixture[0][0].scalar(select(func.count()).select_from(MCPOperationModel)) == 0


async def test_removed_gc_access_blocks_retained_itinerary_receipt(tour_changes):
    fixture = tour_changes
    await execute(fixture, "create_gc_itinerary_draft")
    fixture[4].removed_at = fixture[4].revoked_at = datetime.now(UTC)
    fixture[4].is_enabled = False
    await fixture[0][0].flush()
    with pytest.raises(MCPInputError, match="unavailable"):
        await execute(fixture, "create_gc_itinerary_draft")
