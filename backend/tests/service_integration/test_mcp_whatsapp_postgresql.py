"""Actual PostgreSQL reminder confirmation and dispatch authority races."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, event, func, select, update

from app.application.mcp.operations import MCPOperationService
from app.application.mcp.whatsapp_intents import whatsapp_intent_operations
from app.infrastructure.database.mcp_communication_models import (
    MCPWhatsAppOutboxModel,
    MCPWhatsAppPlanModel,
)
from app.infrastructure.database.mcp_models import MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AgencyModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
    WhatsAppPhoneWelcomeModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.whatsapp import worker_runtime
from app.infrastructure.whatsapp.mcp_progress import refresh_mcp_dispatch_progress
from app.presentation.api.v1.routes import whatsapp_scope, whatsapp_send
from app.presentation.mcp.whatsapp_intent_tools import reminder_snapshot
from tests.service_integration.test_mcp_concurrency_postgresql import mcp_sessions as mcp_sessions
from tests.service_integration.test_mcp_operations_postgresql import (
    operation_sessions as operation_sessions,
)

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"
    ),
]


@pytest.fixture
async def intent_sessions(operation_sessions, monkeypatch):
    sessions, base, _, grants, tokens = operation_sessions
    settings = base.model_copy(
        update={
            "whatsapp_access_token": "synthetic",
            "whatsapp_phone_number_id": "synthetic-phone",
            "whatsapp_reminder_template_name": "reminder_v1",
        }
    )
    async with sessions() as session:
        await session.execute(
            update(MCPGrantModel)
            .where(MCPGrantModel.id.in_(grants))
            .values(capabilities=["mcp:read", "mcp:communicate"])
        )
        agency = AgencyModel(
            id=uuid.uuid4(), name="Reminder fixture", email=f"{uuid.uuid4()}@example.test"
        )
        session.add(agency)
        await session.flush()
        broadcast = WhatsAppBroadcastGroupModel(
            id=uuid.uuid4(),
            agency_id=agency.id,
            name="Exact PG reminder",
            recipient_opt_in_confirmed_at=datetime.now(UTC),
        )
        session.add(broadcast)
        await session.flush()
        for index in range(3):
            phone = f"+91987654320{index}"
            recipient_id = uuid.uuid4()
            session.add(
                WhatsAppBroadcastRecipientModel(
                    id=recipient_id,
                    agency_id=agency.id,
                    broadcast_group_id=broadcast.id,
                    name=f"Synthetic {index}",
                    phone_number=phone,
                    normalized_phone_number=phone,
                )
            )
            session.add(
                WhatsAppPhoneWelcomeModel(
                    agency_id=agency.id,
                    normalized_phone_number=phone,
                    status="delivered",
                    attempt_id=uuid.uuid4(),
                    attempt_kind="broadcast",
                )
            )
            await session.flush()
            session.add(
                WhatsAppRecipientMessageStateModel(
                    id=uuid.uuid4(),
                    agency_id=agency.id,
                    broadcast_group_id=broadcast.id,
                    recipient_id=recipient_id,
                    message_type="welcome",
                    status="delivered",
                )
            )
        await session.commit()
    monkeypatch.setattr(whatsapp_send, "get_settings", lambda: settings)
    monkeypatch.setattr(whatsapp_scope, "get_settings", lambda: settings)
    monkeypatch.setattr(worker_runtime, "get_settings", lambda: settings)
    monkeypatch.setattr(worker_runtime, "AsyncSessionFactory", sessions)
    provider = AsyncMock(side_effect=lambda **_kwargs: f"wamid.synthetic.{uuid.uuid4()}")
    monkeypatch.setattr(worker_runtime, "send_whatsapp_template", provider)
    return sessions, settings, grants, tokens, broadcast.id, provider


async def invoke(fixture, name, payload, *, connection=0, key=None):
    async with fixture[0]() as session:
        try:
            result = await MCPOperationService(
                session, fixture[1], whatsapp_intent_operations(reminder_snapshot, fixture[1])
            ).execute(
                access_token=fixture[3][connection],
                operation_name=name,
                idempotency_key=key or f"pg-{name}-001",
                payload=payload,
            )
            await session.commit()
            return result
        except BaseException:
            await session.rollback()
            raise


async def prepare(fixture):
    return await invoke(
        fixture,
        "prepare_whatsapp_reminder",
        {
            "broadcast_id": str(fixture[4]),
            "message_content": "Please review the application reminder.",
            "recipient_ids": None,
            "audience": "all",
            "audience_client_group_id": None,
        },
    )


async def confirm(fixture, prepared, *, connection=0, key=None):
    return await invoke(
        fixture,
        "confirm_whatsapp_reminder",
        {"plan_id": prepared["data"]["plan_id"], "plan_hash": prepared["data"]["plan_hash"], "user_confirmed": True},
        connection=connection,
        key=key,
    )


async def test_concurrent_confirmation_across_connections_queues_one_exact_batch(intent_sessions):
    fixture = intent_sessions
    prepared = await prepare(fixture)
    results = await asyncio.wait_for(
        asyncio.gather(*(confirm(fixture, prepared, connection=index % 2) for index in range(6))),
        15,
    )
    assert all(result == results[0] for result in results)
    async with fixture[0]() as session:
        batch = uuid.UUID(results[0]["data"]["batch_id"])
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WhatsAppMessageLogModel)
                .where(WhatsAppMessageLogModel.batch_id == batch)
            )
            == 3
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(MCPWhatsAppOutboxModel)
                .where(MCPWhatsAppOutboxModel.batch_id == batch)
            )
            == 1
        )
    fixture[5].assert_not_awaited()


async def test_distinct_confirmation_keys_cannot_duplicate_one_plan(intent_sessions):
    fixture = intent_sessions
    prepared = await prepare(fixture)
    results = await asyncio.wait_for(
        asyncio.gather(
            confirm(fixture, prepared, connection=0, key="pg-confirm-intention-one"),
            confirm(fixture, prepared, connection=1, key="pg-confirm-intention-two"),
        ),
        15,
    )
    assert results[0]["data"]["batch_id"] == results[1]["data"]["batch_id"]


async def test_original_revocation_before_dispatch_prevents_all_provider_calls(intent_sessions):
    fixture = intent_sessions
    prepared = await prepare(fixture)
    result = await confirm(fixture, prepared, connection=1)
    async with fixture[0]() as session:
        await session.execute(
            update(MCPGrantModel)
            .where(MCPGrantModel.id == fixture[2][0])
            .values(revoked_at=datetime.now(UTC))
        )
        await session.commit()
    await worker_runtime.run_whatsapp_broadcast(
        **{**prepared["data"]["preview"]["worker_payload"], "batch_id": result["data"]["batch_id"]}
    )
    fixture[5].assert_not_awaited()
    async with fixture[0]() as session:
        states = list(
            (
                await session.scalars(
                    select(WhatsAppMessageLogModel.status).where(
                        WhatsAppMessageLogModel.batch_id == uuid.UUID(result["data"]["batch_id"])
                    )
                )
            ).all()
        )
        assert states == ["failed"] * 3


async def test_retained_outbox_origin_blocks_dispatch_after_manual_plan_removal(intent_sessions):
    fixture = intent_sessions
    prepared = await prepare(fixture)
    result = await confirm(fixture, prepared)
    async with fixture[0]() as session:
        await session.execute(
            delete(MCPWhatsAppPlanModel).where(
                MCPWhatsAppPlanModel.id == uuid.UUID(prepared["data"]["plan_id"])
            )
        )
        await session.commit()
        outbox = await session.scalar(
            select(MCPWhatsAppOutboxModel).where(
                MCPWhatsAppOutboxModel.batch_id == uuid.UUID(result["data"]["batch_id"])
            )
        )
        assert outbox is not None and outbox.plan_id is None
    await worker_runtime.run_whatsapp_broadcast(
        **{**prepared["data"]["preview"]["worker_payload"], "batch_id": result["data"]["batch_id"]}
    )
    fixture[5].assert_not_awaited()


@pytest.mark.parametrize("barrier", ["revocation", "cancellation"])
async def test_dispatch_winner_holds_authority_until_attempt_finishes(intent_sessions, barrier):
    fixture = intent_sessions
    prepared = await prepare(fixture)
    result = await confirm(fixture, prepared, connection=1)
    entered, release, waiting = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def provider(**_kwargs):
        entered.set()
        await asyncio.wait_for(release.wait(), 10)
        return f"wamid.synthetic.{uuid.uuid4()}"

    fixture[5].side_effect = provider
    worker = asyncio.create_task(
        worker_runtime.run_whatsapp_broadcast(
            **{
                **prepared["data"]["preview"]["worker_payload"],
                "batch_id": result["data"]["batch_id"],
            }
        )
    )
    await asyncio.wait_for(entered.wait(), 5)
    engine = fixture[0].kw["bind"].sync_engine

    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        if (
            barrier == "revocation"
            and statement.startswith("UPDATE mcp_grants")
            or barrier == "cancellation"
            and "FROM mcp_whatsapp_plans" in statement
            and "FOR UPDATE" in statement
        ):
            waiting.set()

    async def stop():
        if barrier == "cancellation":
            return await invoke(
                fixture,
                "cancel_whatsapp_intent",
                {"plan_id": prepared["data"]["plan_id"]},
                connection=1,
            )
        async with fixture[0]() as session:
            await session.execute(
                update(MCPGrantModel)
                .where(MCPGrantModel.id == fixture[2][0])
                .values(revoked_at=datetime.now(UTC))
            )
            await session.commit()

    event.listen(engine, "before_cursor_execute", observe)
    stopper = asyncio.create_task(stop())
    try:
        await asyncio.wait_for(waiting.wait(), 5)
        assert not stopper.done()
        release.set()
        await asyncio.wait_for(asyncio.gather(worker, stopper), 15)
    finally:
        release.set()
        event.remove(engine, "before_cursor_execute", observe)
        for task in (worker, stopper):
            if not task.done():
                task.cancel()
        await asyncio.gather(worker, stopper, return_exceptions=True)
    assert fixture[5].await_count == 1
    async with fixture[0]() as session:
        statuses = list(
            (
                await session.scalars(
                    select(WhatsAppMessageLogModel.status).where(
                        WhatsAppMessageLogModel.batch_id == uuid.UUID(result["data"]["batch_id"])
                    )
                )
            ).all()
        )
        assert statuses.count("submitted") == 1 and statuses.count("failed") == 2
        plan = await session.get(MCPWhatsAppPlanModel, uuid.UUID(prepared["data"]["plan_id"]))
        if barrier == "cancellation":
            assert plan.status == "cancelled"


async def test_terminal_observation_skips_busy_operation_and_inspection_catches_up(
    intent_sessions, monkeypatch
):
    from fastapi import FastAPI
    from mcp.server import MCPServer
    from mcp.server.auth.provider import AccessToken

    from app.presentation.mcp.whatsapp_intent_tools import register_whatsapp_intent_tools

    f = intent_sessions
    prepared = await prepare(f)
    confirmed = await confirm(f, prepared, connection=1)
    plan_id, batch_id = (
        uuid.UUID(prepared["data"]["plan_id"]),
        uuid.UUID(confirmed["data"]["batch_id"]),
    )
    async with f[0]() as session:
        operation = await session.scalar(
            select(MCPOperationModel).where(MCPOperationModel.workflow_id == batch_id)
        )
        identifier, initial_result = operation.id, operation.initial_result
        grant = await session.get(MCPGrantModel, f[2][1])
        subject, client_id = str(grant.user_id), grant.client_id
    op_locked, plan_locked, observation_done = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def operation_holder():
        async with f[0]() as session:
            await session.scalar(
                select(MCPOperationModel)
                .where(MCPOperationModel.id == identifier)
                .with_for_update()
            )
            op_locked.set()
            await asyncio.wait_for(plan_locked.wait(), 5)
            # This uses the mutation ordering operation -> plan while the observer
            # has plan -> operation. Observation must not wait for the latter.
            await session.scalar(
                select(MCPWhatsAppPlanModel)
                .where(MCPWhatsAppPlanModel.id == plan_id)
                .with_for_update()
            )
            await session.commit()

    async def terminal_observer():
        await asyncio.wait_for(op_locked.wait(), 5)
        async with f[0]() as session:
            plan = await session.scalar(
                select(MCPWhatsAppPlanModel)
                .where(MCPWhatsAppPlanModel.id == plan_id)
                .with_for_update()
            )
            plan_locked.set()
            await session.execute(
                update(WhatsAppMessageLogModel)
                .where(WhatsAppMessageLogModel.batch_id == batch_id)
                .values(status="submitted")
            )
            plan.status = "completed"
            await session.execute(
                update(MCPWhatsAppOutboxModel)
                .where(MCPWhatsAppOutboxModel.batch_id == batch_id)
                .values(status="completed")
            )
            await refresh_mcp_dispatch_progress(session, batch_id=batch_id)
            await session.commit()
            observation_done.set()

    await asyncio.wait_for(asyncio.gather(operation_holder(), terminal_observer()), 10)
    assert observation_done.is_set()
    async with f[0]() as session:
        operation = await session.get(MCPOperationModel, identifier)
        assert operation.status == "queued" and operation.initial_result == initial_result
    app, server = FastAPI(), MCPServer("Observation recovery test")
    app.state.mcp_session_factory, app.state.mcp_operations = f[0], {}
    register_whatsapp_intent_tools(app, server, f[1])
    monkeypatch.setattr(
        "app.presentation.mcp.invocation.get_access_token",
        lambda: AccessToken(
            token=f[3][1],
            client_id=client_id,
            scopes=["mcp:read", "mcp:communicate"],
            subject=subject,
            resource=f[1].mcp.resource,
            claims={"grant_id": str(f[2][1])},
        ),
    )
    result = await server.call_tool("inspect_whatsapp_intent", {"plan_id": str(plan_id)})
    assert result.structured_content["receipts"]["status_counts"]["submitted"] == 3
    async with f[0]() as session:
        operation = await session.get(MCPOperationModel, identifier)
        assert (
            operation.status == "succeeded"
            and operation.stage == "dispatch_complete"
            and operation.progress == 1
        )
        assert operation.initial_result == initial_result
