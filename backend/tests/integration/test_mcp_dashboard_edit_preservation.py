"""Partial MCP edits preserve canonical settings; explicit false/null stay intentional."""

import json
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken
from sqlalchemy import func, select

from app.application.mcp.operations import (
    MCPDatabaseContext,
    MCPOperationError,
    MCPOperationService,
)
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.menu_models import MealPlanEntryModel, MealPlanModel, MenuDishModel
from app.infrastructure.database.models import (
    AuditLogModel,
    PassportSubmissionModel,
    RoomingHotelModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.presentation.api.v1.routes import rooming
from app.presentation.api.v1.schemas.rooming_schemas import UpdateHotelVipRequest
from app.presentation.mcp.broadcast_write_tools import broadcast_write_operation
from app.presentation.mcp.dashboard_edit_tools import register_dashboard_edit_tools
from app.presentation.mcp.dashboard_write_support import (
    MAX_RESULT_BYTES,
    audit_request,
    configuration_revision,
    scoped_actor,
)
from tests.integration.test_mcp_dashboard_edits import edits as edits
from tests.integration.test_mcp_dashboard_edits import execute


async def test_sdk_group_rename_preserves_trip_collection_and_unrequested_airports(
    edits, monkeypatch
):
    session, settings, actor, grants, tokens, agency, _, group = edits
    group.base_city_enabled = group.staff_code_enabled = True
    group.nearest_international_airport_enabled = True
    group.departure_cities, group.notes = ["Delhi"], "Retained office note"
    await session.flush()
    dates = (group.travel_date, group.return_date)
    app, server = FastAPI(), MCPServer("Partial group settings")

    @asynccontextmanager
    async def sessions():
        yield session

    app.state.mcp_session_factory, app.state.mcp_operations = sessions, {}
    register_dashboard_edit_tools(server, app, settings)
    monkeypatch.setattr(
        "app.presentation.mcp.invocation.get_access_token",
        lambda: AccessToken(
            token=tokens[0],
            client_id=grants[0].client_id,
            scopes=["mcp:change"],
            subject=str(actor.id),
        ),
    )
    change = {
        "agency_id": str(agency.id),
        "group_id": str(group.id),
        "name": "Chosen renamed trip",
        "expected_configuration_revision": configuration_revision(group),
        "collection_settings_confirmed": True,
    }
    response = (
        await server.call_tool(
            "configure_group_link",
            {"change": change, "idempotency_key": "partial-group-rename-001"},
        )
    ).structured_content
    assert "receipt" in response
    assert (group.travel_date, group.return_date) == dates and group.destination == "Tokyo"
    assert (
        group.base_city_enabled
        and group.staff_code_enabled
        and group.nearest_international_airport_enabled
    )
    assert group.departure_cities == ["Delhi"] and group.notes == "Retained office note"
    assert "NEVER_RETURN_UPLOAD_CREDENTIAL" not in json.dumps(response)
    await execute(
        edits,
        "configure_group_link",
        {
            **change,
            "departure_cities": ["Mumbai"],
            "expected_configuration_revision": configuration_revision(group),
        },
        key="partial-airport-edit-001",
    )
    assert group.departure_cities == ["Mumbai"] and group.nearest_international_airport_enabled
    await execute(
        edits,
        "configure_group_link",
        {
            **change,
            "destination": None,
            "base_city_enabled": False,
            "nearest_international_airport_enabled": False,
            "expected_configuration_revision": configuration_revision(group),
        },
        key="explicit-group-clears-001",
    )
    assert group.destination is None and group.base_city_enabled is False
    assert group.staff_code_enabled is True and group.departure_cities == []


async def test_merged_group_dates_are_canonically_validated_before_any_edit(edits):
    session, _, _, _, _, agency, _, group = edits
    payload = {
        "agency_id": str(agency.id),
        "group_id": str(group.id),
        "name": "Must not rename",
        "travel_date": (group.return_date + timedelta(days=1)).isoformat(),
        "expected_configuration_revision": configuration_revision(group),
        "collection_settings_confirmed": True,
    }
    with pytest.raises(MCPOperationError, match="invalid_dashboard_edit"):
        await execute(edits, "configure_group_link", payload)
    assert group.name == "Synthetic group"
    assert await session.scalar(select(func.count()).select_from(MCPOperationModel)) == 0


async def test_dish_rename_retains_inactive_status_and_notes_until_explicit_change(edits):
    session, _, _, _, _, agency, category, _ = edits
    dish = MenuDishModel(
        id=uuid.uuid4(),
        category_id=category.id,
        name="Prior dish",
        normalized_name="prior dish",
        notes="Retained allergy note",
        is_active=False,
    )
    session.add(dish)
    await session.flush()
    payload = {
        "agency_id": str(agency.id),
        "dish_id": str(dish.id),
        "name": "Renamed dish",
        "expected_updated_at": dish.updated_at.isoformat(),
        "expected_category_updated_at": category.updated_at.isoformat(),
    }
    await execute(edits, "update_menu_dish", payload)
    assert dish.notes == "Retained allergy note" and dish.is_active is False
    await execute(
        edits,
        "update_menu_dish",
        {
            **payload,
            "notes": None,
            "is_active": True,
            "expected_updated_at": dish.updated_at.isoformat(),
            "expected_category_updated_at": category.updated_at.isoformat(),
        },
        key="explicit-dish-change-001",
    )
    assert dish.notes is None and dish.is_active is True
    history = (
        await session.scalars(
            select(AuditLogModel).where(AuditLogModel.action == "mcp.dashboard_edit")
        )
    ).all()
    assert history[0].metadata_json["retained_before"]["target"]["is_active"] is False


async def test_plan_and_hotel_rename_preserve_existing_dates_and_city(edits):
    session, _, actor, _, _, agency, category, group = edits
    plan = MealPlanModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        name="Prior plan",
        trip_days=2,
        start_date=group.travel_date,
        generation_seed=1,
        created_by_user_id=actor.id,
    )
    hotel = RoomingHotelModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        group_id=group.id,
        hotel_name="Prior hotel",
        city="Tokyo",
        check_in_date=group.travel_date,
        check_out_date=group.return_date,
    )
    session.add_all([plan, hotel])
    await session.flush()
    session.add_all(
        [
            MealPlanEntryModel(
                id=uuid.uuid4(),
                plan_id=plan.id,
                day_number=day,
                meal_type=meal,
                category_id=category.id,
                category_name=category.name,
                dish_name=f"Retained {day} {meal} snapshot",
            )
            for day in (1, 2)
            for meal in ("lunch", "dinner")
        ]
    )
    await session.flush()
    await execute(
        edits,
        "update_meal_plan",
        {
            "agency_id": str(agency.id),
            "plan_id": str(plan.id),
            "name": "Renamed plan",
            "expected_updated_at": plan.updated_at.isoformat(),
        },
    )
    assert plan.start_date == group.travel_date
    await execute(
        edits,
        "configure_rooming_hotel",
        {
            "agency_id": str(agency.id),
            "group_id": str(group.id),
            "hotel_id": str(hotel.id),
            "hotel_name": "Renamed hotel",
            "expected_updated_at": hotel.updated_at.isoformat(),
        },
    )
    assert (
        hotel.city == "Tokyo"
        and hotel.check_in_date == group.travel_date
        and hotel.check_out_date == group.return_date
    )


async def test_rooming_selection_receipt_retains_current_revision_fence(edits):
    session, _, _, _, _, agency, _, group = edits
    hotel = RoomingHotelModel(
        id=uuid.uuid4(), agency_id=agency.id, group_id=group.id, hotel_name="Selected hotel"
    )
    passenger = PassportSubmissionModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        group_id=group.id,
        client_name="Selected passenger",
        status="confirmed",
        image_s3_key="Retained image",
    )
    session.add_all([hotel, passenger])
    await session.flush()
    request = {
        "agency_id": str(agency.id),
        "group_id": str(group.id),
        "hotel_id": str(hotel.id),
        "passenger_ids": [str(passenger.id)],
        "expected_allocation_revisions": {str(hotel.id): 0},
        "allocation_changes_confirmed": True,
    }
    result = await execute(edits, "select_rooming_passengers", request)
    assert result["data"]["result"]["current_revisions"] == {str(hotel.id): 1}
    assert await execute(edits, "select_rooming_passengers", request, connection=1) == result
    with pytest.raises(MCPOperationError, match="workflow_revision_changed"):
        await execute(
            edits, "select_rooming_passengers", request, key="stale-allocation-new-key-001"
        )
    assert await session.scalar(select(func.count()).select_from(MCPOperationModel)) == 1
    canonical_audit = await session.scalar(
        select(AuditLogModel).where(AuditLogModel.action == "rooming.hotel_passengers_selected")
    )
    assert canonical_audit.metadata_json["allocation_revisions"] == {str(hotel.id): 1}

    # The unchanged website handler also persists its canonical VIP revision
    # evidence as JSON and retains a verifiable audit chain.
    service = MCPOperationService(session, edits[1], [])
    principal = await service._authorize(edits[4][0])
    actor = await scoped_actor(MCPDatabaseContext(session, principal, uuid.UUID(int=0)), agency.id)
    vip = await rooming.update_hotel_vip_status(
        hotel.id,
        UpdateHotelVipRequest(
            passenger_ids=[passenger.id], is_vip=True, expected_allocation_revisions={hotel.id: 1}
        ),
        audit_request(),
        actor,
        session,
    )
    assert vip.current_revisions == {hotel.id: 2}
    vip_audit = await session.scalar(
        select(AuditLogModel).where(AuditLogModel.action == "rooming.hotel_vip_updated")
    )
    assert vip_audit.metadata_json["allocation_revisions"] == {str(hotel.id): 2}
    from app.infrastructure.repositories.audit_log_repository import AuditLogRepository

    assert (await AuditLogRepository(session).verify_chain(agency.id)).valid


async def test_broadcast_history_byte_bound_refuses_before_contact_or_receipt_changes(edits):
    session, settings, actor, _, tokens, agency, _, _ = edits
    group = WhatsAppBroadcastGroupModel(
        id=uuid.uuid4(), agency_id=agency.id, name="Bounded history", created_by_user_id=actor.id
    )
    session.add(group)
    await session.flush()
    recipient = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        broadcast_group_id=group.id,
        name="Retained recipient",
        phone_number="+919999999901",
        normalized_phone_number="919999999901",
        imported_fields={"retained_source": "x" * MAX_RESULT_BYTES},
    )
    session.add(recipient)
    await session.flush()
    service = MCPOperationService(
        session, settings, [broadcast_write_operation("add_broadcast_contacts")]
    )
    with pytest.raises(MCPOperationError, match="broadcast_source_limit"):
        await service.execute(
            access_token=tokens[0],
            operation_name="add_broadcast_contacts",
            idempotency_key="bounded-contact-history-001",
            payload={
                "agency_id": str(agency.id),
                "broadcast_id": str(group.id),
                "expected_updated_at": group.updated_at.isoformat(),
                "contacts": [{"name": "New contact", "phone_number": "+919999999902"}],
                "recipient_opt_in_confirmed": True,
            },
        )
    assert (
        await session.scalar(select(func.count()).select_from(WhatsAppBroadcastRecipientModel)) == 1
    )
    assert await session.scalar(select(func.count()).select_from(MCPOperationModel)) == 0
    assert await session.scalar(select(func.count()).select_from(AuditLogModel)) == 0
