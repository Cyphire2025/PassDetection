"""Office projections retain history, organization identity and physical evidence."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.operations_reads import (
    MENU_KINDS,
    ROOMING_KINDS,
    TOUR_KINDS,
    MCPOperationsReadService,
)
from app.infrastructure.database.menu_models import (
    MealPlanEntryModel,
    MealPlanModel,
    MenuCategoryModel,
    MenuDishModel,
)
from app.infrastructure.database.models import (
    AgencyModel,
    AttendanceRecordModel,
    AttendanceSessionModel,
    AuditLogModel,
    ClientGroupModel,
    CoordinatorAssignmentModel,
    CoordinatorGroupAssignmentModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    RoomingAssignmentModel,
    RoomingCheckinModel,
    RoomingHotelModel,
    RoomingHotelPassengerModel,
    RoomingRoomModel,
    UserModel,
)


@pytest.fixture
async def office_reads(db_session):
    actor = UserModel(id=uuid.uuid4(), email="SECRET_ACTOR@example.test", hashed_password="SECRET_HASH", full_name="Reader", role="super_admin")
    agencies = [AgencyModel(id=uuid.uuid4(), name="Same agency name", email=f"SECRET_AGENCY{index}@example.test") for index in range(2)]
    db_session.add_all([actor, *agencies])
    await db_session.flush()
    groups = [ClientGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Same group name", token=f"SECRET_TOKEN{index}", import_only=True,
                               travel_date=date(2000, 1, 1), return_date=date(2000, 1, 2)) for index, agency in enumerate(agencies)]
    coordinators = [UserModel(id=uuid.uuid4(), agency_id=agency.id, email=f"SECRET_COORDINATOR{index}@example.test", hashed_password="SECRET_HASH",
                             full_name="Coordinator", role="agency_coordinator") for index, agency in enumerate(agencies)]
    db_session.add_all([*groups, *coordinators])
    await db_session.flush()
    return db_session, actor, agencies, groups, coordinators, MCPOperationsReadService(db_session, cursor_secret="office-test-secret")


async def add_passengers(session, group):
    passengers = [PassportSubmissionModel(id=uuid.uuid4(), agency_id=group.agency_id, group_id=group.id, client_name="Person",
        image_s3_key="SECRET_IMAGE", status=status) for status in ("confirmed", "staff_approved", "uploaded")]
    session.add_all(passengers)
    await session.flush()
    return passengers


@pytest.mark.asyncio
async def test_empty_import_only_group_and_invalid_scopes(office_reads):
    _, actor, agencies, groups, _, service = office_reads
    for method, kinds in ((service.tour, TOUR_KINDS), (service.rooming, ROOMING_KINDS)):
        for kind in kinds:
            result = await method(user_id=actor.id, group_id=groups[0].id, kind=kind)
            assert result["items"] == [] and result["completeness"] == "complete"
        with pytest.raises(ValueError, match="scope"):
            await method(user_id=actor.id, group_id=groups[0].id, agency_id=agencies[1].id, kind=next(iter(kinds)))
    with pytest.raises(ValueError, match="Hotel"):
        await service.rooming(user_id=actor.id, group_id=groups[0].id, kind="rooms", hotel_id=uuid.uuid4())
    with pytest.raises(ValueError, match="Activity"):
        await service.tour(user_id=actor.id, group_id=groups[0].id, kind="attendance_records", session_id=uuid.uuid4())
    for kind in MENU_KINDS - {"entries"}:
        assert (await service.menu(user_id=actor.id, kind=kind))["items"] == []


@pytest.mark.asyncio
async def test_tour_retains_inactive_assignment_and_original_scan_without_credentials(office_reads):
    session, actor, _, groups, coordinators, service = office_reads
    group, coordinator = groups[0], coordinators[0]
    passengers = await add_passengers(session, group)
    session.add(PassportRosterResolutionModel(id=uuid.uuid4(), agency_id=group.agency_id, client_group_id=group.id,
        submission_id=passengers[1].id, resolution_type="rejected", status="active", excluded_submission_ids=[], resolved_by_user_id=actor.id))
    session.add(CoordinatorGroupAssignmentModel(id=uuid.uuid4(), group_id=group.id, agency_id=group.agency_id, coordinator_user_id=coordinator.id, active=False))
    session.add_all([CoordinatorAssignmentModel(id=uuid.uuid4(), group_id=group.id, agency_id=group.agency_id,
        coordinator_user_id=coordinator.id, passenger_id=person.id, active=index != 1) for index, person in enumerate(passengers)])
    activity_id = uuid.uuid4()
    activity = AttendanceSessionModel(id=activity_id, agency_id=group.agency_id, group_id=group.id, name="Arrival",
        normalized_name="arrival", canonical_session_id=activity_id, status="completed", created_by_user_id=actor.id)
    session.add(activity)
    await session.flush()
    session.add(AttendanceRecordModel(id=uuid.uuid4(), agency_id=group.agency_id, session_id=activity.id,
        passenger_id=passengers[1].id, coordinator_user_id=coordinator.id, scanned_at=datetime.now(UTC), sync_source="offline",
        client_event_id="SECRET_EVENT", device_id="SECRET_DEVICE"))
    await session.flush()
    args = dict(user_id=actor.id, group_id=group.id)
    coordinations = await service.tour(**args, kind="coordinators")
    assert coordinations["items"][0]["active"] is False and coordinations["group"]["trip_has_ended"] is True
    assert (await service.tour(**args, kind="coordinators", include_inactive=False))["items"] == []
    assignments = await service.tour(**args, kind="passenger_assignments")
    assert len(assignments["items"]) == 3 and sum(row["passenger_is_operational"] for row in assignments["items"]) == 1
    records = await service.tour(**args, kind="attendance_records", session_id=activity.id)
    assert records["items"][0]["sync_source"] == "offline" and records["items"][0]["passenger_is_operational"] is False
    assert "SECRET" not in json.dumps([coordinations, assignments, records])
    activity_result = await service.tour(**args, kind="activities")
    assert activity_result["items"][0]["canonical_session_id"] == str(activity.id)
    assert activity.status == "completed" and coordinations["items"][0]["active"] is False


@pytest.mark.asyncio
async def test_rooming_selection_allocation_checkin_and_live_membership_are_distinct(office_reads):
    session, actor, _, groups, _, service = office_reads
    group = groups[0]
    passengers = await add_passengers(session, group)
    hotel = RoomingHotelModel(id=uuid.uuid4(), group_id=group.id, agency_id=group.agency_id, hotel_name="Hotel", allocation_revision=3)
    session.add(hotel)
    await session.flush()
    room = RoomingRoomModel(id=uuid.uuid4(), hotel_id=hotel.id, room_number="101", capacity=2, is_saved=True, roommate_notes="SECRET_NOTES")
    session.add(room)
    await session.flush()
    for person in passengers[:2]:
        session.add(RoomingHotelPassengerModel(id=uuid.uuid4(), group_id=group.id, agency_id=group.agency_id,
            hotel_id=hotel.id, passenger_id=person.id, is_vip=person == passengers[0]))
    session.add(RoomingAssignmentModel(id=uuid.uuid4(), hotel_id=hotel.id, room_id=room.id, passenger_id=passengers[0].id))
    session.add(RoomingCheckinModel(id=uuid.uuid4(), agency_id=group.agency_id, hotel_id=hotel.id, room_id=room.id,
        passenger_id=passengers[0].id, checked_in=True, key_issued=False, welcome_letter_issued=True, remarks="SECRET_REMARKS"))
    await session.flush()
    results = {kind: await service.rooming(user_id=actor.id, group_id=group.id, kind=kind, hotel_id=hotel.id) for kind in ROOMING_KINDS}
    assert len(results["selected_passengers"]["items"]) == 2
    assert len(results["allocations"]["items"]) == 1 and results["hotels"]["items"][0]["allocation_revision"] == 3
    assert results["checkins"]["items"][0]["checked_in"] is True and results["checkins"]["items"][0]["key_issued"] is False
    assert "SECRET" not in json.dumps(results)
    passengers[0].status = "uploaded"
    await session.flush()
    changed = await service.rooming(user_id=actor.id, group_id=group.id, kind="checkins")
    assert changed["items"][0]["passenger_is_operational"] is False and changed["items"][0]["checked_in"] is True
    assert room.is_saved is True and hotel.allocation_revision == 3


@pytest.mark.asyncio
async def test_menu_platform_is_not_agency_and_saved_entry_names_survive_library_changes(office_reads):
    session, actor, agencies, _, _, service = office_reads
    categories = [MenuCategoryModel(id=uuid.uuid4(), agency_id=scope, name="Main", normalized_name="main") for scope in (None, agencies[0].id, agencies[1].id)]
    session.add_all(categories)
    await session.flush()
    dish = MenuDishModel(id=uuid.uuid4(), category_id=categories[1].id, name="New name", normalized_name="new name", is_active=False)
    plan = MealPlanModel(id=uuid.uuid4(), agency_id=agencies[0].id, name="Plan", trip_days=2, generation_seed=123)
    session.add_all([dish, plan])
    await session.flush()
    session.add(MealPlanEntryModel(id=uuid.uuid4(), plan_id=plan.id, day_number=1, meal_type="lunch", dish_id=dish.id,
        category_id=categories[1].id, dish_name="Retained original", category_name="Original category", notes="x" * 2500))
    await session.flush()
    platform = await service.menu(user_id=actor.id, kind="categories")
    assert [row["id"] for row in platform["items"]] == [str(categories[0].id)]
    agency = await service.menu(user_id=actor.id, kind="categories", agency_id=agencies[0].id)
    assert [row["id"] for row in agency["items"]] == [str(categories[1].id)]
    dishes = await service.menu(user_id=actor.id, kind="dishes", agency_id=agencies[0].id, category_id=categories[1].id)
    assert dishes["items"][0]["is_active"] is False
    assert (await service.menu(user_id=actor.id, kind="dishes", agency_id=agencies[0].id, include_inactive=False))["items"] == []
    entries = await service.menu(user_id=actor.id, kind="entries", agency_id=agencies[0].id, plan_id=plan.id)
    assert entries["items"][0]["dish_name"] == "Retained original"
    assert entries["items"][0]["notes_truncated"] is True and len(entries["items"][0]["notes"]) == 2000
    with pytest.raises(ValueError, match="organization"):
        await service.menu(user_id=actor.id, kind="entries", plan_id=plan.id)
    assert plan.generation_seed == 123 and dish.name == "New name"


@pytest.mark.asyncio
async def test_directory_minimal_fields_distinct_counts_and_contact_audit(office_reads):
    session, actor, agencies, groups, coordinators, service = office_reads
    await add_passengers(session, groups[0])
    coordinators[1].deleted_at = datetime.now(UTC)
    await session.flush()
    directory = await service.directory(user_id=actor.id, kind="agencies")
    counts = {row["id"]: row for row in directory["items"]}
    assert counts[str(agencies[0].id)]["passport_submission_count"] == 3
    assert counts[str(agencies[0].id)]["operational_passenger_count"] == 2
    assert counts[str(agencies[1].id)]["retained_group_count"] == 1 and counts[str(agencies[1].id)]["passport_submission_count"] == 0
    users = await service.directory(user_id=actor.id, kind="users")
    assert len(users["items"]) == 2 and "SECRET" not in json.dumps([directory, users])
    contacts = await service.directory(user_id=actor.id, kind="users", agency_id=agencies[0].id, include_contact_details=True)
    assert contacts["items"][0]["email"].startswith("SECRET_COORDINATOR")
    audit = (await session.execute(select(AuditLogModel).where(AuditLogModel.action == "mcp.directory.contact_read"))).scalar_one()
    assert audit.metadata_json["authorized_result_count"] == 1 and "SECRET" not in json.dumps(audit.metadata_json)


@pytest.mark.asyncio
async def test_bounded_keysets_namespace_binding_and_creation_cutoff(office_reads):
    session, actor, agencies, groups, _, service = office_reads
    stamp = datetime.now(UTC) - timedelta(minutes=1)
    session.add_all([RoomingHotelModel(id=uuid.UUID(f"eeeeeeee-eeee-eeee-eeee-{i+1:012x}"), group_id=groups[0].id,
        agency_id=agencies[0].id, hotel_name=f"Hotel{i}", created_at=stamp) for i in range(107)])
    await session.flush()
    args = dict(user_id=actor.id, group_id=groups[0].id, kind="hotels", page_size=11)
    first = page = await service.rooming(**args)
    newer = RoomingHotelModel(id=uuid.uuid4(), group_id=groups[0].id, agency_id=agencies[0].id, hotel_name="New after cutoff")
    session.add(newer)
    await session.flush()
    seen = [row["id"] for row in page["items"]]
    while page["has_more"]:
        page = await service.rooming(**args, cursor=page["next_cursor"])
        seen += [row["id"] for row in page["items"]]
    assert len(seen) == len(set(seen)) == 107 and str(newer.id) not in seen
    with pytest.raises(ValueError, match="cursor"):
        await service.rooming(**{**args, "kind": "rooms"}, cursor=first["next_cursor"])
    with pytest.raises(ValueError, match="cursor"):
        await service.tour(user_id=actor.id, group_id=groups[0].id, kind="activities", page_size=11, cursor=first["next_cursor"])


@pytest.mark.asyncio
async def test_deleted_group_opt_in_live_actor_and_invalid_selectors(office_reads):
    session, actor, _, groups, _, service = office_reads
    for value in (0, 101, True):
        with pytest.raises(ValueError, match="Page size"):
            await service.directory(user_id=actor.id, kind="users", page_size=value)
    with pytest.raises(ValueError, match="plan ID"):
        await service.menu(user_id=actor.id, kind="entries")
    with pytest.raises(ValueError, match="kind"):
        await service.tour(user_id=actor.id, group_id=groups[0].id, kind="../../files")
    groups[0].deleted_at, groups[0].status = datetime.now(UTC), "deleted"
    await session.flush()
    with pytest.raises(ValueError, match="scope"):
        await service.rooming(user_id=actor.id, group_id=groups[0].id, kind="hotels")
    assert (await service.rooming(user_id=actor.id, group_id=groups[0].id, kind="hotels", include_deleted=True))["items"] == []
    actor.deleted_at = datetime.now(UTC)
    await session.flush()
    with pytest.raises(MCPAuthError):
        await service.menu(user_id=actor.id, kind="plans")


@pytest.mark.asyncio
async def test_inconsistent_cross_agency_links_do_not_enter_group_projections(office_reads):
    session, actor, agencies, groups, coordinators, service = office_reads
    local = (await add_passengers(session, groups[0]))[0]
    foreign = (await add_passengers(session, groups[1]))[0]
    hotels = [RoomingHotelModel(id=uuid.uuid4(), group_id=group.id, agency_id=group.agency_id, hotel_name="Same hotel") for group in groups]
    session.add_all(hotels)
    await session.flush()
    rooms = [RoomingRoomModel(id=uuid.uuid4(), hotel_id=hotel.id, room_number="101") for hotel in hotels]
    session.add_all(rooms)
    await session.flush()
    session.add_all([
        RoomingAssignmentModel(id=uuid.uuid4(), hotel_id=hotels[0].id, room_id=rooms[1].id, passenger_id=local.id),
        RoomingCheckinModel(id=uuid.uuid4(), agency_id=agencies[0].id, hotel_id=hotels[0].id, room_id=rooms[0].id, passenger_id=foreign.id),
        CoordinatorAssignmentModel(id=uuid.uuid4(), group_id=groups[0].id, agency_id=agencies[0].id,
            coordinator_user_id=coordinators[0].id, passenger_id=foreign.id),
    ])
    await session.flush()
    args = dict(user_id=actor.id, group_id=groups[0].id)
    assert (await service.rooming(**args, kind="allocations"))["items"] == []
    assert (await service.rooming(**args, kind="checkins"))["items"] == []
    assert (await service.tour(**args, kind="passenger_assignments"))["items"] == []
    with pytest.raises(ValueError, match="Hotel"):
        await service.rooming(**args, kind="rooms", hotel_id=hotels[1].id)
