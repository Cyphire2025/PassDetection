"""Canonical hotel XLSX parity, no physical events, and durable export recovery."""

import asyncio
import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import func, select

from app.application.mcp.artifacts import ArtifactError
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.application.mcp.rooming_exports import (
    MCPRoomingExportService,
    RoomingExportRequest,
    rooming_export_operation,
)
from app.application.use_cases.passports.prepare_group_excel import _canonical
from app.application.use_cases.rooming.auto_allocator import (
    RoomingAllocationCandidate,
    build_room_plan,
    room_plan_fingerprint,
)
from app.application.use_cases.rooming.prepare_excel import (
    PreparedRoomingExcel,
    RoomingPreparationError,
)
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    PassportExportHistoryModel,
    PassportSubmissionModel,
    RoomingAssignmentModel,
    RoomingCheckinModel,
    RoomingHotelModel,
    RoomingHotelPassengerModel,
    RoomingPassengerPreferenceModel,
    RoomingRoomModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes import rooming as web
from tests.integration.test_mcp_artifacts import artifacts as artifacts
from tests.integration.test_mcp_exports import downloaded, person, values


async def seed(f):
    f.group.staff_code_enabled = True
    hotel = RoomingHotelModel(
        id=uuid.uuid4(),
        agency_id=f.agency.id,
        group_id=f.group.id,
        hotel_name="Synthetic Hotel",
        city="Pune",
        allocation_revision=1,
    )
    passengers = [person(f, 1), person(f, 2)]
    for i, row in enumerate(passengers):
        row.confirmed_fields = {**row.confirmed_fields, "sex": "F"}
        row.staff_metadata = {"staff_code": str(i + 1), "zone_name": "West"}
    f.session.add_all([hotel, *passengers])
    await f.session.flush()
    candidates = [
        RoomingAllocationCandidate(
            passenger_id=row.id,
            gender="female",
            is_vip=i == 0,
            priority_values=(),
            stable_order=(row.created_at, row.family_member_index or 0, row.client_name.casefold()),
        )
        for i, row in enumerate(passengers)
    ]
    plan = build_room_plan(candidates, priority_count=0)
    hotel.allocation_fingerprint = room_plan_fingerprint(plan, [], candidates=candidates)
    hotel.allocation_updated_at = datetime.now(UTC) + timedelta(seconds=1)
    rooms, assignments = [], []
    for index, planned in enumerate(plan):
        room = RoomingRoomModel(
            id=uuid.uuid4(),
            hotel_id=hotel.id,
            room_number=str(101 + index),
            room_type=planned.room_type,
            allocation_tag=planned.allocation_tag,
            capacity=1 if planned.room_type == "single" else 2,
            sort_order=index,
        )
        f.session.add(room)
        await f.session.flush()
        rooms.append(room)
        for position, identifier in enumerate(planned.passenger_ids):
            assignment = RoomingAssignmentModel(
                id=uuid.uuid4(),
                hotel_id=hotel.id,
                room_id=room.id,
                passenger_id=identifier,
                position=position,
            )
            assignments.append(assignment)
            f.session.add(assignment)
    f.session.add_all(
        [
            RoomingHotelPassengerModel(
                id=uuid.uuid4(),
                agency_id=f.agency.id,
                group_id=f.group.id,
                hotel_id=hotel.id,
                passenger_id=row.id,
                is_vip=i == 0,
            )
            for i, row in enumerate(passengers)
        ]
    )
    f.session.add(
        RoomingPassengerPreferenceModel(
            id=uuid.uuid4(),
            hotel_id=hotel.id,
            passenger_id=passengers[0].id,
            allocation_tag="female",
            special_requests=["vip"],
        )
    )
    checkin = RoomingCheckinModel(
        id=uuid.uuid4(),
        agency_id=f.agency.id,
        hotel_id=hotel.id,
        room_id=rooms[0].id,
        passenger_id=passengers[0].id,
        checked_in=True,
        checked_in_at=datetime.now(UTC),
        key_issued=True,
        key_issued_at=datetime.now(UTC),
        welcome_letter_issued=False,
        remarks="Existing arrival evidence",
    )
    f.session.add(checkin)
    await f.session.commit()
    f.hotel, f.passengers, f.rooms, f.assignments, f.checkin = (
        hotel,
        passengers,
        rooms,
        assignments,
        checkin,
    )
    return f


def service(f):
    return MCPRoomingExportService(
        f.session, f.settings, web.rooming_excel_support(), artifacts=f.service
    )


async def queue(f, kind="rooming_list", key=None):
    request = RoomingExportRequest(
        agency_id=f.agency.id, group_id=f.group.id, hotel_id=f.hotel.id, kind=kind
    )
    observed = await service(f).inspect(f.principal, request)
    definition = rooming_export_operation(f.settings, web.rooming_excel_support())
    payload = {
        "export": request.model_dump(mode="json"),
        "expected_revision": observed["expected_revision"],
    }
    key = key or uuid.uuid4().hex
    receipt = await MCPOperationService(f.session, f.settings, [definition]).execute(
        access_token=f.token,
        operation_name=definition.policy.name,
        idempotency_key=key,
        payload=payload,
    )
    await f.session.commit()
    return receipt, key, payload


async def generate(f, receipt, token=None):
    result = await service(f).generate(
        access_token=token or f.token, operation_id=uuid.UUID(receipt["operation_id"])
    )
    await f.session.commit()
    return result


async def business_snapshot(f):
    result = {}
    for model in (
        RoomingHotelModel,
        RoomingHotelPassengerModel,
        RoomingRoomModel,
        RoomingAssignmentModel,
        RoomingPassengerPreferenceModel,
        RoomingCheckinModel,
        PassportSubmissionModel,
    ):
        rows = (
            await f.session.scalars(
                select(model).order_by(model.id).execution_options(populate_existing=True)
            )
        ).all()
        result[model.__tablename__] = [
            {column.key: getattr(row, column.key) for column in model.__table__.columns}
            for row in rows
        ]
    return _canonical(result)


@pytest.mark.parametrize("kind", ["rooming_list", "checkins"])
async def test_real_workbook_web_parity_and_no_business_event_changes(artifacts, kind):
    f = await seed(artifacts)
    before = await business_snapshot(f)
    receipt, _, _ = await queue(f, kind)
    result = await generate(f, receipt)
    actor = await UserRepository(f.session).get_by_id(f.user.id)
    route = web.export_hotel_rooming_list if kind == "rooming_list" else web.export_hotel_checkins
    response = await route(
        f.hotel.id,
        Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1)}),
        current_user=actor,
        session=f.session,
    )
    await f.session.commit()
    expected = b"".join([part async for part in response.body_iterator])
    received = await downloaded(f, result)

    def workbook(data):
        return {
            sheet: [row for row in rows if not str(row[0]).startswith("Generated:")]
            for sheet, rows in values(data).items()
        }

    assert workbook(received) == workbook(expected)
    assert (
        "TEST1" in str(workbook(received))
        if kind == "rooming_list"
        else "Existing arrival evidence" in str(workbook(received))
    )
    assert await business_snapshot(f) == before
    for model in (PassportExportHistoryModel, WhatsAppMessageLogModel):
        assert await f.session.scalar(select(func.count()).select_from(model)) == 0
    row = await f.session.scalar(select(MCPArtifactModel))
    assert row.delivered_at is not None and row.export_history_id is None
    assert row.purpose == f"rooming_{'list' if kind == 'rooming_list' else 'checkins'}_excel"


async def test_response_loss_retry_new_connection_and_expiry_keep_one_artifact(artifacts):
    f = await seed(artifacts)
    receipt, key, payload = await queue(f)
    result = await generate(f, receipt)
    definition = rooming_export_operation(f.settings, web.rooming_excel_support())
    replay = await MCPOperationService(f.session, f.settings, [definition]).execute(
        access_token=f.token,
        operation_name=definition.policy.name,
        idempotency_key=key,
        payload=payload,
    )
    await f.session.commit()
    assert replay == receipt
    token, _ = await f.connect()
    recovered = await generate(f, receipt, token)
    assert recovered["artifact"]["sha256"] == result["artifact"]["sha256"]
    assert recovered["artifact"]["artifact_id"] != result["artifact"]["artifact_id"]
    row = await f.session.scalar(select(MCPArtifactModel))
    row.created_at, row.expires_at = (
        datetime.now(UTC) - timedelta(hours=2),
        datetime.now(UTC) - timedelta(hours=1),
    )
    await f.session.commit()
    with pytest.raises(ArtifactError):
        await generate(f, receipt)
    await f.session.rollback()
    assert len(f.storage.objects) == 1


@pytest.mark.parametrize("source", ["checkin", "room", "passport", "hotel"])
async def test_changed_render_sources_invalidate_queued_revision(artifacts, source):
    f = await seed(artifacts)
    receipt, _, _ = await queue(f, "checkins")
    if source == "checkin":
        f.checkin.welcome_letter_issued = True
    elif source == "room":
        f.rooms[0].room_number = "Changed"
    elif source == "passport":
        f.passengers[0].staff_metadata = {"zone_name": "Changed"}
    else:
        f.hotel.city = "Changed"
    await f.session.commit()
    with pytest.raises((MCPOperationError, HTTPException), match="export_revision_changed|changed"):
        await generate(f, receipt)
    await f.session.rollback()
    assert not f.storage.objects


@pytest.mark.parametrize(
    "invalid", ["missing_allocation", "stale_passenger", "wrong_fingerprint", "foreign_passenger"]
)
async def test_invalid_allocation_or_scope_is_rejected_without_repair(artifacts, invalid):
    f = await seed(artifacts)
    if invalid == "missing_allocation":
        f.hotel.allocation_fingerprint = None
    elif invalid == "stale_passenger":
        f.hotel.allocation_updated_at = datetime.now(UTC) - timedelta(days=1)
    elif invalid == "wrong_fingerprint":
        f.hotel.allocation_fingerprint = "a" * 64
    else:
        from app.infrastructure.database.models import ClientGroupModel

        other = ClientGroupModel(
            id=uuid.uuid4(), agency_id=f.agency.id, name="Other exact group", token=uuid.uuid4().hex
        )
        f.session.add(other)
        await f.session.flush()
        f.passengers[0].group_id = other.id
    await f.session.commit()
    before = await business_snapshot(f)
    with pytest.raises((ArtifactError, RoomingPreparationError, HTTPException)):
        await queue(f)
    await f.session.rollback()
    assert await business_snapshot(f) == before and not f.storage.objects


async def test_exact_group_agency_and_hotel_required_even_for_superadmin(artifacts):
    f = await seed(artifacts)
    base = {"agency_id": f.agency.id, "group_id": f.group.id, "hotel_id": f.hotel.id}
    for key in base:
        with pytest.raises(ArtifactError):
            await service(f).inspect(
                f.principal, RoomingExportRequest(**{**base, key: uuid.uuid4()})
            )
        await f.session.rollback()
    assert not f.storage.objects


async def test_db_only_prepare_source_bound_and_failed_storage_resume(artifacts, monkeypatch):
    from app.application.mcp import artifacts as artifacts_module
    from app.application.mcp import rooming_export_source

    f = await seed(artifacts)
    with monkeypatch.context() as scope:

        def forbidden(*args, **kwargs):
            raise AssertionError("DB callback cannot initialize storage or render")

        scope.setattr(artifacts_module, "MCPArtifactStorage", forbidden)
        scope.setattr(PreparedRoomingExcel, "render", forbidden)
        receipt, _, _ = await queue(f)
    with monkeypatch.context() as scope:
        scope.setattr(rooming_export_source, "MAX_ROOMING_ROWS", 1)
        with pytest.raises(ArtifactError, match="row limit"):
            await generate(f, receipt)
    await f.session.rollback()
    original = f.storage.put_transfer

    async def fail(*args, **kwargs):
        raise OSError("synthetic storage failure")

    f.storage.put_transfer = fail
    with pytest.raises(OSError):
        await generate(f, receipt)
    await f.session.rollback()
    row = await f.session.get(MCPOperationModel, uuid.UUID(receipt["operation_id"]))
    assert row.status == "queued"
    f.storage.put_transfer = original
    await generate(f, receipt)


async def test_cancellation_drains_native_worker_before_capacity_release(artifacts, monkeypatch):
    f = await seed(artifacts)
    receipt, _, _ = await queue(f)
    original = PreparedRoomingExcel.render_sync
    entered, release = threading.Event(), threading.Event()

    def slow(self):
        entered.set()
        assert release.wait(5)
        return original(self)

    monkeypatch.setattr(PreparedRoomingExcel, "render_sync", slow)
    task = asyncio.create_task(generate(f, receipt))
    assert await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    await asyncio.sleep(0.05)
    assert not task.done()
    with pytest.raises(ArtifactError, match="capacity is busy"):
        await generate(f, receipt)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await f.session.rollback()
    assert not f.storage.objects
    monkeypatch.setattr(PreparedRoomingExcel, "render_sync", original)
    await generate(f, receipt)


def test_request_does_not_accept_all_hotels_or_event_mutations():
    base = {"agency_id": uuid.uuid4(), "group_id": uuid.uuid4(), "hotel_id": uuid.uuid4()}
    for extra in ({"kind": "all"}, {"check_in": True}, {"allocate": True}, {"hotel_ids": []}):
        with pytest.raises(ValidationError):
            RoomingExportRequest(**base, **extra)


@pytest.mark.parametrize("limit", ["MAX_SNAPSHOT_BYTES", "MAX_WORKBOOK_BYTES"])
async def test_snapshot_and_output_limits_leave_request_queued(artifacts, monkeypatch, limit):
    from app.application.mcp import rooming_exports

    f = await seed(artifacts)
    receipt, _, _ = await queue(f)
    monkeypatch.setattr(rooming_exports, limit, 1)
    with pytest.raises(ArtifactError, match="size limit"):
        await generate(f, receipt)
    await f.session.rollback()
    assert not f.storage.objects
    operation = await f.session.get(MCPOperationModel, uuid.UUID(receipt["operation_id"]))
    assert operation.status == "queued"


async def test_post_storage_checkin_revision_change_prevents_artifact_commit(artifacts):
    f = await seed(artifacts)
    receipt, _, _ = await queue(f, "checkins")
    original = f.storage.put_transfer

    async def changed(*args, **kwargs):
        await original(*args, **kwargs)
        f.checkin.remarks = "Changed while writing the private copy"
        await f.session.flush()

    f.storage.put_transfer = changed
    with pytest.raises(MCPOperationError, match="export_revision_changed"):
        await generate(f, receipt)
    await f.session.rollback()
    assert len(f.storage.objects) == 1
    assert await f.session.scalar(select(func.count()).select_from(MCPArtifactModel)) == 0


async def test_whatsapp_priority_and_contact_transport_inputs_are_in_revision(artifacts):
    from app.application.use_cases.rooming.auto_allocator import normalize_priority_value
    from app.infrastructure.database.models import (
        ClientGroupWhatsAppBroadcastLinkModel,
        WhatsAppBroadcastGroupModel,
        WhatsAppBroadcastRecipientModel,
    )

    f = await seed(artifacts)
    broadcast = WhatsAppBroadcastGroupModel(
        id=uuid.uuid4(), agency_id=f.agency.id, name="Rooming priorities"
    )
    f.session.add(broadcast)
    await f.session.flush()
    f.session.add(
        ClientGroupWhatsAppBroadcastLinkModel(
            id=uuid.uuid4(),
            agency_id=f.agency.id,
            client_group_id=f.group.id,
            broadcast_group_id=broadcast.id,
        )
    )
    recipients = []
    for i, passenger in enumerate(f.passengers):
        passenger.client_phone = f"+91900000000{i + 1}"
        row = WhatsAppBroadcastRecipientModel(
            id=uuid.uuid4(),
            agency_id=f.agency.id,
            broadcast_group_id=broadcast.id,
            name=passenger.client_name,
            phone_number=passenger.client_phone,
            normalized_phone_number=passenger.client_phone,
            imported_fields={
                "Zone": "West",
                "Transport": "Bus 1",
                "Email": f"fixture{i}@example.test",
            },
        )
        recipients.append(row)
        f.session.add(row)
    await f.session.flush()
    fields = [{"key": "whatsapp:zone", "label": "Zone"}]
    f.hotel.allocation_priority_fields = fields
    candidates = [
        RoomingAllocationCandidate(
            passenger_id=row.id,
            gender="female",
            is_vip=i == 0,
            priority_values=(normalize_priority_value("West"),),
            stable_order=(row.created_at, row.family_member_index or 0, row.client_name.casefold()),
        )
        for i, row in enumerate(f.passengers)
    ]
    plan = build_room_plan(candidates, priority_count=1)
    f.hotel.allocation_fingerprint = room_plan_fingerprint(plan, fields, candidates=candidates)
    f.hotel.allocation_updated_at = datetime.now(UTC) + timedelta(seconds=1)
    await f.session.commit()
    receipt, _, _ = await queue(f)
    ready = await generate(f, receipt)
    content = await downloaded(f, ready)
    assert "West" in str(values(content))
    next_receipt, _, _ = await queue(f)
    recipients[0].imported_fields = {**recipients[0].imported_fields, "Transport": "Changed bus"}
    await f.session.commit()
    with pytest.raises(MCPOperationError, match="export_revision_changed"):
        await generate(f, next_receipt)
    await f.session.rollback()
    assert len(f.storage.objects) == 1
