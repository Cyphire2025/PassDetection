"""Additive menu/hotel creation, immutable retries and current receipt access."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken
from sqlalchemy import delete, func, select

from app.application.mcp.office_changes import OFFICE_CREATION_KINDS
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.menu_models import (
    MealPlanEntryModel,
    MealPlanModel,
    MenuCategoryModel,
    MenuDishModel,
)
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    RoomingAssignmentModel,
    RoomingHotelModel,
    RoomingHotelPassengerModel,
    RoomingRoomModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.mcp.invocation import MCPInputError
from app.presentation.mcp.office_change_tools import (
    office_creation_definition,
    register_office_change_tools,
)
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture


@pytest.fixture
async def office_changes(operations_fixture):
    session, settings, actor, grants, tokens = operations_fixture
    agencies = [
        AgencyModel(id=uuid.uuid4(), name="Tenant", email=f"office-{index}@example.test")
        for index in range(2)
    ]
    session.add_all(agencies)
    await session.flush()
    group = ClientGroupModel(
        id=uuid.uuid4(),
        agency_id=agencies[0].id,
        name="Empty import-only group",
        token="SECRET_UPLOAD",
        import_only=True,
    )
    category = MenuCategoryModel(
        id=uuid.uuid4(),
        agency_id=agencies[0].id,
        name="Original category",
        normalized_name="original category",
        sort_order=0,
        created_by_user_id=actor.id,
    )
    session.add_all([group, category])
    await session.flush()
    dishes = [
        MenuDishModel(
            id=uuid.uuid4(),
            category_id=category.id,
            name=f"Dish {index}",
            normalized_name=f"dish {index}",
            sort_order=index,
            is_active=True,
            created_by_user_id=actor.id,
        )
        for index in range(4)
    ]
    session.add_all(dishes)
    await session.flush()
    scope = {"agency_id": str(agencies[0].id)}
    payloads = {
        "create_menu_category": {**scope, "name": "  New   category "},
        "create_menu_dish": {
            **scope,
            "category_id": str(category.id),
            "name": "New dish",
            "notes": "  Reviewed   note ",
            "expected_category_updated_at": category.updated_at.isoformat(),
        },
        "create_meal_plan": {
            **scope,
            "name": "New trip plan",
            "trip_days": 2,
            "category_ids": [str(category.id)],
            "expected_category_revisions": {str(category.id): category.updated_at.isoformat()},
        },
        "create_rooming_hotel": {
            **scope,
            "group_id": str(group.id),
            "hotel_name": "New stay",
            "city": "Tokyo",
            "check_in_date": "2026-10-01",
            "check_out_date": "2026-10-03",
        },
    }
    service = MCPOperationService(
        session, settings, [office_creation_definition(kind) for kind in OFFICE_CREATION_KINDS]
    )
    return operations_fixture, agencies, group, category, payloads, service


async def execute(fixture, kind, *, payload=None, key="office-creation-request-001", connection=0):
    return await fixture[5].execute(
        access_token=fixture[0][4][connection],
        operation_name=kind,
        idempotency_key=key,
        payload=fixture[4][kind] if payload is None else payload,
    )


@pytest.mark.parametrize("kind", OFFICE_CREATION_KINDS)
async def test_additive_creation_is_idempotent_across_connections_and_current_receipt_is_safe(
    office_changes, kind
):
    fixture = office_changes
    session = fixture[0][0]
    receipt = await execute(fixture, kind)
    assert await execute(fixture, kind, connection=1) == receipt
    observed = await fixture[5].inspect(
        access_token=fixture[0][4][1], operation_id=uuid.UUID(receipt["operation_id"])
    )
    assert (
        observed["created_entities"] == receipt["created_entities"]
        and observed["status"] == "succeeded"
    )
    assert await session.scalar(select(func.count()).select_from(MCPOperationModel)) == 1
    audit = await session.get(AuditLogModel, uuid.UUID(receipt["data"]["business_audit_id"]))
    assert audit.metadata_json["mcp_operation_id"] == receipt["operation_id"]
    assert "SECRET_UPLOAD" not in json.dumps(receipt)
    assert fixture[3].name == "Original category"
    assert await session.scalar(select(func.count()).select_from(RoomingRoomModel)) == 0
    assert await session.scalar(select(func.count()).select_from(RoomingHotelPassengerModel)) == 0
    assert await session.scalar(select(func.count()).select_from(RoomingAssignmentModel)) == 0
    if kind == "create_menu_category":
        row = await session.get(MenuCategoryModel, uuid.UUID(receipt["data"]["category_id"]))
        assert row.name == "New category" and row.sort_order == 1
        row.name = "Later staff edit"
        await session.flush()
        assert await execute(fixture, kind) == receipt and row.name == "Later staff edit"
    elif kind == "create_menu_dish":
        row = await session.get(MenuDishModel, uuid.UUID(receipt["data"]["dish_id"]))
        assert row.notes == "Reviewed note" and row.sort_order == 4
        assert (
            receipt["data"]["category_updated_at"]
            != fixture[4][kind]["expected_category_updated_at"]
        )
    elif kind == "create_meal_plan":
        entries = list((await session.scalars(select(MealPlanEntryModel))).all())
        assert len(entries) == 4 and len({entry.dish_id for entry in entries}) == 4
        original = [(entry.id, entry.dish_name) for entry in entries]
        second = await execute(fixture, kind, key="explicit-new-plan-request-002")
        assert second["data"]["plan_id"] != receipt["data"]["plan_id"]
        assert [(entry.id, entry.dish_name) for entry in entries] == original
        assert await session.scalar(select(func.count()).select_from(MealPlanEntryModel)) == 8
    else:
        hotel = await session.get(RoomingHotelModel, uuid.UUID(receipt["data"]["hotel_id"]))
        assert hotel.group_id == fixture[2].id and hotel.allocation_revision == 0
        assert receipt["created_entities"][0]["path"] == f"/rooming/{hotel.group_id}"


@pytest.mark.parametrize("kind", OFFICE_CREATION_KINDS)
async def test_changed_retry_payload_conflicts_without_new_entities(office_changes, kind):
    receipt = await execute(office_changes, kind)
    payload = {
        **office_changes[4][kind],
        "name" if kind != "create_rooming_hotel" else "hotel_name": "Different",
    }
    with pytest.raises(MCPOperationError, match="idempotency_conflict"):
        await execute(office_changes, kind, payload=payload)
    assert await execute(office_changes, kind) == receipt


@pytest.mark.parametrize("kind", OFFICE_CREATION_KINDS)
async def test_current_receipt_access_denies_removed_or_moved_entities(office_changes, kind):
    fixture = office_changes
    session = fixture[0][0]
    receipt = await execute(fixture, kind)
    if kind == "create_menu_category":
        row = await session.get(MenuCategoryModel, uuid.UUID(receipt["data"]["category_id"]))
        row.agency_id = fixture[1][1].id
    elif kind == "create_menu_dish":
        await session.execute(
            delete(MenuDishModel).where(MenuDishModel.id == uuid.UUID(receipt["data"]["dish_id"]))
        )
    elif kind == "create_meal_plan":
        row = await session.get(MealPlanModel, uuid.UUID(receipt["data"]["plan_id"]))
        row.agency_id = None
    else:
        fixture[2].status = "deleted"
    await session.flush()
    with pytest.raises(MCPOperationError, match="office_(receipt|group)_unavailable"):
        await execute(fixture, kind, connection=1)
    with pytest.raises(MCPOperationError, match="office_(receipt|group)_unavailable"):
        await fixture[5].inspect(
            access_token=fixture[0][4][1], operation_id=uuid.UUID(receipt["operation_id"])
        )


@pytest.mark.parametrize("kind", OFFICE_CREATION_KINDS)
async def test_inactive_agency_denies_creation_and_replay(office_changes, kind):
    fixture = office_changes
    await execute(fixture, kind)
    fixture[1][0].is_active = False
    await fixture[0][0].flush()
    for key in ("office-creation-request-001", "new-creation-request-002"):
        with pytest.raises(MCPOperationError, match="office_agency_unavailable"):
            await execute(fixture, kind, key=key)


@pytest.mark.parametrize("kind", ["create_menu_dish", "create_meal_plan", "create_rooming_hotel"])
async def test_cross_agency_parent_cannot_be_used(office_changes, kind):
    payload = {**office_changes[4][kind], "agency_id": str(office_changes[1][1].id)}
    with pytest.raises((MCPInputError, MCPOperationError)):
        await execute(office_changes, kind, payload=payload)
    assert (
        await office_changes[0][0].scalar(select(func.count()).select_from(MCPOperationModel)) == 0
    )


@pytest.mark.parametrize("kind", ["create_menu_dish", "create_meal_plan"])
async def test_stale_revision_cannot_write(office_changes, kind):
    fixture = office_changes
    fixture[3].updated_at = datetime.now(UTC) + timedelta(seconds=1)
    await fixture[0][0].flush()
    with pytest.raises(MCPInputError, match="category revision conflicts"):
        await execute(fixture, kind)
    assert await fixture[0][0].scalar(select(func.count()).select_from(MCPOperationModel)) == 0


async def test_platform_scope_is_explicit_separate_and_duplicate_names_are_not_upserts(
    office_changes,
):
    fixture = office_changes
    agency_receipt = await execute(fixture, "create_menu_category")
    platform = {**fixture[4]["create_menu_category"], "agency_id": None}
    platform_receipt = await execute(
        fixture, "create_menu_category", payload=platform, key="platform-category-request-001"
    )
    assert platform_receipt["data"]["agency_id"] is None
    assert platform_receipt["data"]["category_id"] != agency_receipt["data"]["category_id"]
    with pytest.raises(MCPInputError, match="conflicts"):
        await execute(fixture, "create_menu_category", key="explicit-duplicate-category")
    assert await fixture[0][0].scalar(select(func.count()).select_from(MenuCategoryModel)) == 3


@pytest.mark.parametrize(
    "kind,change",
    [
        ("create_menu_category", {"replace_existing": True}),
        ("create_menu_category", {"name": " "}),
        ("create_menu_dish", {"is_active": False}),
        ("create_menu_dish", {"name": ""}),
        ("create_meal_plan", {"category_ids": []}),
        ("create_meal_plan", {"expected_category_revisions": {}}),
        ("create_meal_plan", {"trip_days": True}),
        ("create_meal_plan", {"plan_id": str(uuid.uuid4())}),
        ("create_rooming_hotel", {"agency_id": None}),
        ("create_rooming_hotel", {"hotel_name": " "}),
        ("create_rooming_hotel", {"check_out_date": "2026-09-01"}),
        ("create_rooming_hotel", {"rooms": []}),
    ],
)
async def test_invalid_or_unsupported_input_never_writes(office_changes, kind, change):
    with pytest.raises(MCPInputError, match="documented creation fields"):
        await execute(office_changes, kind, payload={**office_changes[4][kind], **change})
    assert (
        await office_changes[0][0].scalar(select(func.count()).select_from(MCPOperationModel)) == 0
    )


async def test_insufficient_dishes_and_extra_revision_never_replace_an_existing_plan(
    office_changes,
):
    fixture = office_changes
    await execute(fixture, "create_meal_plan")
    payload = {**fixture[4]["create_meal_plan"], "trip_days": 3}
    with pytest.raises(MCPInputError, match="two distinct active dishes"):
        await execute(
            fixture, "create_meal_plan", payload=payload, key="insufficient-dishes-request"
        )
    assert await fixture[0][0].scalar(select(func.count()).select_from(MealPlanEntryModel)) == 4
    payload = {
        **fixture[4]["create_meal_plan"],
        "expected_category_revisions": {
            **fixture[4]["create_meal_plan"]["expected_category_revisions"],
            str(uuid.uuid4()): datetime.now(UTC).isoformat(),
        },
    }
    with pytest.raises(MCPInputError, match="conflicts"):
        await execute(
            fixture, "create_meal_plan", payload=payload, key="extra-revision-request-001"
        )


@pytest.mark.parametrize("kind", OFFICE_CREATION_KINDS)
async def test_business_audit_failure_rolls_back_creation_and_operation_receipt(
    office_changes, kind, monkeypatch
):
    fixture = office_changes
    session = fixture[0][0]
    before = await session.scalar(select(func.count()).select_from(MenuDishModel))
    monkeypatch.setattr(
        AuditLogRepository, "record", AsyncMock(side_effect=RuntimeError("fixture audit failure"))
    )
    with pytest.raises(RuntimeError, match="fixture audit failure"):
        await execute(fixture, kind)
    assert await session.scalar(select(func.count()).select_from(MCPOperationModel)) == 0
    assert await session.scalar(select(func.count()).select_from(MealPlanModel)) == 0
    assert await session.scalar(select(func.count()).select_from(RoomingHotelModel)) == 0
    assert await session.scalar(select(func.count()).select_from(MenuCategoryModel)) == 1
    assert await session.scalar(select(func.count()).select_from(MenuDishModel)) == before


async def test_sdk_dispatch_commits_all_four_tools_and_retry_audits(office_changes, monkeypatch):
    fixture = office_changes
    session, settings, actor, grants, tokens = fixture[0]
    await session.commit()
    app, server = FastAPI(), MCPServer("Additive office fixture")

    @asynccontextmanager
    async def sessions():
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise

    app.state.mcp_session_factory, app.state.mcp_operations = sessions, {}
    register_office_change_tools(server, app, settings)
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
    assert {tool.name for tool in tools} == set(OFFICE_CREATION_KINDS)
    assert all(
        tool.meta["capability"] == "mcp:change" and tool.annotations.idempotent_hint
        for tool in tools
    )
    # The plan uses the freshly inspected pre-dish revision; the later dish
    # intentionally advances it, while retry must return the original receipt.
    for kind, field in [
        ("create_menu_category", "category"),
        ("create_meal_plan", "plan"),
        ("create_menu_dish", "dish"),
        ("create_rooming_hotel", "hotel"),
    ]:
        args = {field: fixture[4][kind], "idempotency_key": "sdk-office-creation-001"}
        first = (await server.call_tool(kind, args)).structured_content
        second = (await server.call_tool(kind, args)).structured_content
        assert first["receipt"] == second["receipt"] and first["audit_id"] != second["audit_id"]
        assert not session.in_transaction()
    assert await session.scalar(select(func.count()).select_from(MCPOperationModel)) == 4
