"""Isolated PostgreSQL races for additive office creation; no schema cleanup."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import func, select

from app.application.mcp.office_changes import OFFICE_CREATION_KINDS
from app.application.mcp.operations import MCPOperationService
from app.infrastructure.database.menu_models import (
    MealPlanEntryModel,
    MenuCategoryModel,
    MenuDishModel,
)
from app.infrastructure.database.models import AgencyModel, AuditLogModel, ClientGroupModel
from app.presentation.mcp.invocation import MCPInputError
from app.presentation.mcp.office_change_tools import office_creation_definition
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
async def office_sessions(operation_sessions):
    sessions, settings, actor_id, _, tokens = operation_sessions
    async with sessions() as session:
        agency = AgencyModel(
            id=uuid.uuid4(), name="Synthetic office", email=f"{uuid.uuid4()}@example.test"
        )
        session.add(agency)
        await session.flush()
        group = ClientGroupModel(
            id=uuid.uuid4(),
            agency_id=agency.id,
            name="Synthetic empty group",
            token=uuid.uuid4().hex,
            import_only=True,
        )
        category = MenuCategoryModel(
            id=uuid.uuid4(),
            agency_id=agency.id,
            name="Original",
            normalized_name="original",
            sort_order=0,
            created_by_user_id=actor_id,
        )
        session.add_all([group, category])
        await session.flush()
        session.add_all(
            [
                MenuDishModel(
                    id=uuid.uuid4(),
                    category_id=category.id,
                    name=f"Dish{index}",
                    normalized_name=f"dish{index}",
                    sort_order=index,
                    is_active=True,
                    created_by_user_id=actor_id,
                )
                for index in range(4)
            ]
        )
        await session.flush()
        scope = {"agency_id": str(agency.id)}
        payloads = {
            "create_menu_category": {**scope, "name": "New category"},
            "create_menu_dish": {
                **scope,
                "category_id": str(category.id),
                "name": "New dish",
                "expected_category_updated_at": category.updated_at.isoformat(),
            },
            "create_meal_plan": {
                **scope,
                "name": "New plan",
                "trip_days": 2,
                "category_ids": [str(category.id)],
                "expected_category_revisions": {str(category.id): category.updated_at.isoformat()},
            },
            "create_rooming_hotel": {**scope, "group_id": str(group.id), "hotel_name": "New hotel"},
        }
        await session.commit()
    return sessions, settings, tokens, payloads, category.id


async def invoke(
    fixture, kind, *, connection=0, key="pg-office-creation-request-001", payload=None
):
    sessions, settings, tokens, payloads, _ = fixture
    async with sessions() as session:
        service = MCPOperationService(session, settings, [office_creation_definition(kind)])
        try:
            result = await service.execute(
                access_token=tokens[connection],
                operation_name=kind,
                idempotency_key=key,
                payload=payloads[kind] if payload is None else payload,
            )
            await session.commit()
            return result
        except BaseException:
            await session.rollback()
            raise


@pytest.mark.parametrize("kind", OFFICE_CREATION_KINDS)
async def test_concurrent_same_intent_creates_one_entity_and_one_business_audit(
    office_sessions, kind
):
    fixture = office_sessions
    receipts = await asyncio.wait_for(
        asyncio.gather(*(invoke(fixture, kind, connection=index % 2) for index in range(6))), 20
    )
    assert all(receipt == receipts[0] for receipt in receipts)
    entity_id = receipts[0]["created_entities"][0]["entity_id"]
    async with fixture[0]() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditLogModel)
                .where(AuditLogModel.entity_id == entity_id)
            )
            == 1
        )
        if kind == "create_meal_plan":
            entries = list(
                (
                    await session.scalars(
                        select(MealPlanEntryModel).where(
                            MealPlanEntryModel.plan_id == uuid.UUID(entity_id)
                        )
                    )
                ).all()
            )
            assert len(entries) == 4 and len({entry.dish_id for entry in entries}) == 4


async def test_two_new_dishes_with_same_parent_revision_have_one_winner(office_sessions):
    fixture = office_sessions
    results = await asyncio.wait_for(
        asyncio.gather(
            invoke(fixture, "create_menu_dish", connection=0, key="pg-first-dish-intent-001"),
            invoke(
                fixture,
                "create_menu_dish",
                connection=1,
                key="pg-second-dish-intent-002",
                payload={**fixture[3]["create_menu_dish"], "name": "Different dish"},
            ),
            return_exceptions=True,
        ),
        20,
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    assert (
        sum(
            isinstance(result, MCPInputError) and result.code == "office_creation_conflict"
            for result in results
        )
        == 1
    )
    async with fixture[0]() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(MenuDishModel)
                .where(MenuDishModel.category_id == fixture[4])
            )
            == 5
        )


async def test_distinct_plan_intents_preserve_both_plans_and_their_entries(office_sessions):
    fixture = office_sessions
    receipts = await asyncio.wait_for(
        asyncio.gather(
            invoke(fixture, "create_meal_plan", connection=0, key="pg-first-plan-intent-001"),
            invoke(fixture, "create_meal_plan", connection=1, key="pg-second-plan-intent-002"),
        ),
        20,
    )
    ids = {uuid.UUID(receipt["data"]["plan_id"]) for receipt in receipts}
    assert len(ids) == 2
    async with fixture[0]() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(MealPlanEntryModel)
                .where(MealPlanEntryModel.plan_id.in_(ids))
            )
            == 8
        )
