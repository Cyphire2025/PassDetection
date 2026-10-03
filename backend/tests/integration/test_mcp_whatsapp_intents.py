"""Exact plan/confirm/cancel and real worker dispatch with isolated fake provider I/O."""

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
from sqlalchemy import func, select

from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.application.mcp.whatsapp_intents import whatsapp_intent_operations
from app.infrastructure.database.mcp_communication_models import (
    MCPWhatsAppOutboxModel,
    MCPWhatsAppPlanModel,
)
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.whatsapp import mcp_publication, worker_runtime
from app.infrastructure.whatsapp.mcp_dispatch import BLOCKED, authorize_mcp_batch_dispatch
from app.infrastructure.whatsapp.mcp_progress import refresh_mcp_dispatch_progress
from app.infrastructure.whatsapp.receipt_bindings import bind_source_provider_message
from app.infrastructure.whatsapp.receipt_inbox import VerifiedReceipt, persist_verified_receipts
from app.infrastructure.whatsapp.receipt_runtime import reconcile_pending_receipts
from app.presentation.mcp.invocation import MCPInputError
from app.presentation.mcp.whatsapp_intent_tools import (
    register_whatsapp_intent_tools,
    reminder_snapshot,
)
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture
from tests.unit.presentation.test_whatsapp_repeatable_reminders import broadcast as broadcast


@pytest.fixture
async def intent_fixture(operations_fixture, broadcast, monkeypatch):
    session, original, user, grants, tokens = operations_fixture
    for grant in grants:
        grant.capabilities = ["mcp:read", "mcp:communicate"]
    await session.flush()
    settings = original.model_copy(
        update={
            "whatsapp_access_token": "synthetic-provider-token",
            "whatsapp_phone_number_id": "synthetic-phone",
            "whatsapp_reminder_template_name": "reminder_v1",
        }
    )
    monkeypatch.setattr(worker_runtime, "get_settings", lambda: settings)
    monkeypatch.setattr(mcp_publication, "get_settings", lambda: settings)

    @asynccontextmanager
    async def sessions():
        yield session

    monkeypatch.setattr(worker_runtime, "AsyncSessionFactory", sessions)
    monkeypatch.setattr(mcp_publication, "AsyncSessionFactory", sessions)
    provider = AsyncMock(side_effect=lambda **_kwargs: f"wamid.{uuid.uuid4()}")
    monkeypatch.setattr(worker_runtime, "send_whatsapp_template", provider)
    service = MCPOperationService(
        session, settings, whatsapp_intent_operations(reminder_snapshot, settings)
    )
    return operations_fixture, broadcast, settings, service, provider


async def invoke(fixture, name, payload, *, key=None, connection=0):
    return await fixture[3].execute(
        access_token=fixture[0][4][connection],
        operation_name=name,
        idempotency_key=key or f"fixture-{name}-001",
        payload=payload,
    )


async def prepare(fixture):
    return await invoke(
        fixture,
        "prepare_whatsapp_reminder",
        {
            "broadcast_id": str(fixture[1].group.id),
            "message_content": "Please submit your remaining details today.",
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


@pytest.mark.parametrize("confirmation", [None, False, 0])
async def test_final_confirmation_is_required_before_queued_effects(intent_fixture, confirmation):
    prepared = await prepare(intent_fixture)
    payload = {"plan_id": prepared["data"]["plan_id"], "plan_hash": prepared["data"]["plan_hash"]}
    if confirmation is not None:
        payload["user_confirmed"] = confirmation
    with pytest.raises(MCPOperationError, match="invalid_whatsapp_plan"):
        await invoke(intent_fixture, "confirm_whatsapp_reminder", payload)
    session = intent_fixture[0][0]
    assert await session.scalar(select(func.count()).select_from(MCPWhatsAppOutboxModel)) == 0
    assert await session.scalar(select(func.count()).select_from(WhatsAppMessageLogModel)) == 0
    intent_fixture[4].assert_not_awaited()


async def count(session, model):
    return await session.scalar(select(func.count()).select_from(model))


async def test_preparation_has_exact_preview_but_no_delivery_side_effect(intent_fixture):
    fixture = intent_fixture
    before = {
        row.id: row.status
        for row in (await fixture[0][0].scalars(select(WhatsAppRecipientMessageStateModel))).all()
    }
    result = await prepare(fixture)
    assert result["data"]["status"] == "prepared" and result["data"]["confirmation_required"]
    preview = result["data"]["preview"]
    assert len(preview["recipients"]) == 6
    assert preview["counts"]["skipped_delivery_unknown"] == 1
    assert preview["counts"]["skipped_in_progress"] == 2
    assert all(
        "Please submit" in item["rendered_message"] and item["language"]
        for item in preview["recipients"]
    )
    assert await count(fixture[0][0], WhatsAppMessageLogModel) == 0
    assert await count(fixture[0][0], MCPWhatsAppOutboxModel) == 0
    after = {
        row.id: row.status
        for row in (
            await fixture[0][0].scalars(
                select(WhatsAppRecipientMessageStateModel).execution_options(populate_existing=True)
            )
        ).all()
    }
    assert after == before
    fixture[1].publication.assert_not_awaited()
    fixture[4].assert_not_awaited()


async def test_unrecognized_saved_outcome_is_suppressed_and_reported_as_unknown(intent_fixture):
    fixture = intent_fixture
    state = await fixture[0][0].scalar(
        select(WhatsAppRecipientMessageStateModel).where(
            WhatsAppRecipientMessageStateModel.recipient_id == fixture[1].recipients[0].id,
            WhatsAppRecipientMessageStateModel.message_type == "reminder",
        )
    )
    state.status = "unrecognized_provider_outcome"
    await fixture[0][0].flush()
    prepared = await prepare(fixture)
    assert len(prepared["data"]["preview"]["recipients"]) == 5
    assert prepared["data"]["preview"]["counts"]["skipped_delivery_unknown"] == 2
    await fixture[0][0].refresh(state)
    assert state.status == "unrecognized_provider_outcome"


async def test_confirmation_exact_replay_durable_queue_and_original_grant_binding(intent_fixture):
    fixture = intent_fixture
    prepared = await prepare(fixture)
    first = await confirm(fixture, prepared, connection=1)
    await fixture[0][0].commit()
    second = await confirm(fixture, prepared, connection=0)
    assert first == second
    plan = await fixture[0][0].scalar(select(MCPWhatsAppPlanModel))
    assert plan.original_grant_id == fixture[0][3][0].id
    assert plan.status == "queued" and plan.batch_id == uuid.UUID(first["data"]["batch_id"])
    assert await count(fixture[0][0], WhatsAppMessageLogModel) == 6
    assert await count(fixture[0][0], MCPWhatsAppOutboxModel) == 1
    fixture[1].publication.assert_not_awaited()
    fixture[4].assert_not_awaited()


@pytest.mark.parametrize("drift", ["phone", "name", "removed", "eligibility"])
async def test_confirmation_drift_rolls_back_all_claims_and_preserves_preview(
    intent_fixture, drift
):
    fixture = intent_fixture
    prepared = await prepare(fixture)
    first_recipient = fixture[1].recipients[0]
    if drift == "phone":
        first_recipient.normalized_phone_number = "+919811111111"
    elif drift == "name":
        fixture[1].group.name = "Changed broadcast name"
    elif drift == "removed":
        first_recipient.removed_at = datetime.now(UTC)
    else:
        row = await fixture[0][0].scalar(
            select(WhatsAppRecipientMessageStateModel).where(
                WhatsAppRecipientMessageStateModel.recipient_id == first_recipient.id,
                WhatsAppRecipientMessageStateModel.message_type == "reminder",
            )
        )
        row.status = "queued"
    await fixture[0][0].flush()
    with pytest.raises((MCPInputError, MCPOperationError)):
        await confirm(fixture, prepared)
    assert await count(fixture[0][0], WhatsAppMessageLogModel) == 0
    assert await count(fixture[0][0], MCPWhatsAppOutboxModel) == 0
    plan = await fixture[0][0].scalar(select(MCPWhatsAppPlanModel))
    assert plan.status == "prepared" and plan.snapshot_hash == prepared["data"]["plan_hash"]


@pytest.mark.parametrize("failure", ["hash", "expired", "original_revoked"])
async def test_wrong_hash_expiry_or_original_revocation_prevent_confirmation(
    intent_fixture, failure
):
    fixture = intent_fixture
    prepared = await prepare(fixture)
    if failure == "hash":
        prepared["data"]["plan_hash"] = "0" * 64
    elif failure == "expired":
        plan = await fixture[0][0].scalar(select(MCPWhatsAppPlanModel))
        plan.prepared_at = datetime.now(UTC) - timedelta(hours=2)
        plan.expires_at = datetime.now(UTC) - timedelta(hours=1)
    else:
        fixture[0][3][0].revoked_at = datetime.now(UTC)
    await fixture[0][0].flush()
    with pytest.raises((MCPOperationError, MCPAuthError)):
        await confirm(fixture, prepared, connection=1)
    assert await count(fixture[0][0], MCPWhatsAppOutboxModel) == 0


async def test_cancel_prepared_intent_keeps_snapshot_and_prevents_confirmation(intent_fixture):
    fixture = intent_fixture
    prepared = await prepare(fixture)
    await invoke(fixture, "cancel_whatsapp_intent", {"plan_id": prepared["data"]["plan_id"]})
    with pytest.raises(MCPOperationError):
        await confirm(fixture, prepared)
    plan = await fixture[0][0].scalar(select(MCPWhatsAppPlanModel))
    assert plan.status == "cancelled" and plan.snapshot == prepared["data"]["preview"]
    assert await count(fixture[0][0], WhatsAppMessageLogModel) == 0


async def test_cancel_queued_preserves_accepted_unknown_history_and_membership(intent_fixture):
    fixture = intent_fixture
    prepared = await prepare(fixture)
    await confirm(fixture, prepared)
    logs = list((await fixture[0][0].scalars(select(WhatsAppMessageLogModel))).all())
    logs[0].status, logs[1].status = "submitted", "delivery_unknown"
    await fixture[0][0].flush()
    await invoke(
        fixture, "cancel_whatsapp_intent", {"plan_id": prepared["data"]["plan_id"]}, connection=1
    )
    await fixture[0][0].refresh(logs[0])
    await fixture[0][0].refresh(logs[1])
    assert logs[0].status == "submitted" and logs[1].status == "delivery_unknown"
    assert await count(fixture[0][0], WhatsAppMessageLogModel) == 6
    assert all(recipient.removed_at is None for recipient in fixture[1].recipients)
    outbox = await fixture[0][0].scalar(select(MCPWhatsAppOutboxModel))
    assert outbox.status == "cancelled"


async def test_live_worker_uses_frozen_payload_once_and_receipts_stay_submitted(intent_fixture):
    fixture = intent_fixture
    prepared = await prepare(fixture)
    result = await confirm(fixture, prepared)
    assert result["status"] == "queued" and result["workflow_id"] == result["data"]["batch_id"]
    await fixture[0][0].commit()
    payload = {
        **prepared["data"]["preview"]["worker_payload"],
        "batch_id": result["data"]["batch_id"],
    }
    await worker_runtime.run_whatsapp_broadcast(**payload)
    assert fixture[4].await_count == 6
    logs = list(
        (
            await fixture[0][0].scalars(
                select(WhatsAppMessageLogModel).execution_options(populate_existing=True)
            )
        ).all()
    )
    assert {log.status for log in logs} == {"submitted"}
    assert all(log.provider_message_id for log in logs)
    observation = await fixture[0][0].get(MCPOperationModel, uuid.UUID(result["operation_id"]))
    assert observation.status == "succeeded" and observation.stage == "dispatch_complete"
    assert observation.progress == 1 and observation.initial_result == result
    assert await confirm(fixture, prepared) == result
    await worker_runtime.run_whatsapp_broadcast(**payload)
    assert fixture[4].await_count == 6


@pytest.mark.parametrize(
    "blocked", ["original_revoked", "cancelled", "orphaned", "payload_changed"]
)
async def test_worker_gate_blocks_before_provider_without_losing_records(intent_fixture, blocked):
    fixture = intent_fixture
    prepared = await prepare(fixture)
    await confirm(fixture, prepared, connection=1)
    session = fixture[0][0]
    plan = await session.scalar(select(MCPWhatsAppPlanModel))
    log = await session.scalar(select(WhatsAppMessageLogModel))
    if blocked == "original_revoked":
        fixture[0][3][0].revoked_at = datetime.now(UTC)
    elif blocked == "cancelled":
        plan.status = "cancelled"
    elif blocked == "orphaned":
        outbox = await session.scalar(select(MCPWhatsAppOutboxModel))
        outbox.plan_id = None
    else:
        log.template_parameter_values = ["tampered"]
    await session.flush()
    assert await authorize_mcp_batch_dispatch(session, log=log, settings=fixture[2]) == BLOCKED
    assert await count(session, WhatsAppMessageLogModel) == 6
    fixture[4].assert_not_awaited()


async def test_publication_recovers_same_batch_and_never_overwrites_cancelled_state(
    intent_fixture, monkeypatch
):
    fixture = intent_fixture
    prepared = await prepare(fixture)
    confirmed = await confirm(fixture, prepared)
    await fixture[0][0].commit()
    publisher = AsyncMock(side_effect=RuntimeError("synthetic lost broker acknowledgement"))
    monkeypatch.setattr(mcp_publication, "publish_whatsapp_task", publisher)
    assert await mcp_publication.run_mcp_whatsapp_publication() == 0
    outbox = await fixture[0][0].scalar(select(MCPWhatsAppOutboxModel))
    assert outbox.status == "pending" and outbox.publication_attempts == 1
    outbox.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    await fixture[0][0].commit()
    publisher.side_effect = None
    assert await mcp_publication.run_mcp_whatsapp_publication() == 1
    assert {call.kwargs["payload"]["batch_id"] for call in publisher.await_args_list} == {
        confirmed["data"]["batch_id"]
    }
    await invoke(fixture, "cancel_whatsapp_intent", {"plan_id": prepared["data"]["plan_id"]})
    await fixture[0][0].commit()
    assert await mcp_publication.run_mcp_whatsapp_publication() == 0
    await fixture[0][0].refresh(outbox)
    assert outbox.status == "cancelled"
    assert "synthetic-provider-token" not in json.dumps(prepared)


async def test_unknown_provider_outcome_is_never_automatically_resent(intent_fixture):
    fixture = intent_fixture
    prepared = await prepare(fixture)
    confirmed = await confirm(fixture, prepared)
    await fixture[0][0].commit()
    fixture[4].side_effect = RuntimeError("synthetic interrupted provider response")
    payload = {
        **prepared["data"]["preview"]["worker_payload"],
        "batch_id": confirmed["data"]["batch_id"],
    }
    await worker_runtime.run_whatsapp_broadcast(**payload)
    assert fixture[4].await_count == 6
    states = list((await fixture[0][0].scalars(select(WhatsAppMessageLogModel.status))).all())
    assert states == ["delivery_unknown"] * 6
    observation = await fixture[0][0].get(MCPOperationModel, uuid.UUID(confirmed["operation_id"]))
    assert observation.status == "unknown" and observation.stage == "dispatch_unknown"
    assert observation.initial_result == confirmed
    await worker_runtime.run_whatsapp_broadcast(**payload)
    assert fixture[4].await_count == 6
    assert await mcp_publication.run_mcp_whatsapp_publication() == 0
    assert fixture[4].await_count == 6


async def test_broker_acknowledgement_racing_cancellation_cannot_reopen_outbox(
    intent_fixture, monkeypatch
):
    fixture = intent_fixture
    prepared = await prepare(fixture)
    await confirm(fixture, prepared)
    await fixture[0][0].commit()

    async def publication(*_args, **_kwargs):
        await invoke(
            fixture,
            "cancel_whatsapp_intent",
            {"plan_id": prepared["data"]["plan_id"]},
            connection=1,
        )
        await fixture[0][0].commit()

    monkeypatch.setattr(mcp_publication, "publish_whatsapp_task", publication)
    await mcp_publication.run_mcp_whatsapp_publication()
    outbox = await fixture[0][0].scalar(select(MCPWhatsAppOutboxModel))
    plan = await fixture[0][0].scalar(select(MCPWhatsAppPlanModel))
    assert outbox.status == plan.status == "cancelled"


async def test_orphaned_intent_becomes_blocked_without_starving_publication_queue(intent_fixture):
    fixture = intent_fixture
    prepared = await prepare(fixture)
    await confirm(fixture, prepared)
    outbox = await fixture[0][0].scalar(select(MCPWhatsAppOutboxModel))
    outbox.plan_id = None
    await fixture[0][0].commit()
    assert await mcp_publication.run_mcp_whatsapp_publication() == 0
    await fixture[0][0].refresh(outbox)
    assert outbox.status == "blocked" and outbox.last_error_code == "origin_plan_missing"
    assert await mcp_publication.run_mcp_whatsapp_publication() == 0


async def test_processing_only_outbox_recovery_never_resubmits_uncertain_attempts(
    intent_fixture, monkeypatch
):
    fixture = intent_fixture
    prepared = await prepare(fixture)
    confirmed = await confirm(fixture, prepared)
    session = fixture[0][0]
    logs = list((await session.scalars(select(WhatsAppMessageLogModel))).all())
    for log in logs:
        log.status = "processing"
    await session.commit()
    broker = AsyncMock()
    monkeypatch.setattr(mcp_publication, "publish_whatsapp_task", broker)
    assert await mcp_publication.run_mcp_whatsapp_publication() == 1
    await worker_runtime.run_whatsapp_broadcast(**broker.await_args.kwargs["payload"])
    fixture[4].assert_not_awaited()
    states = list((await session.scalars(select(WhatsAppMessageLogModel.status))).all())
    assert states == ["delivery_unknown"] * len(logs)
    operation = await session.scalar(
        select(MCPOperationModel).where(
            MCPOperationModel.operation_name == "confirm_whatsapp_reminder"
        )
    )
    assert operation.status == "unknown" and operation.stage == "dispatch_unknown"
    assert operation.initial_result == confirmed
    outbox = await session.scalar(select(MCPWhatsAppOutboxModel))
    outbox.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    assert await mcp_publication.run_mcp_whatsapp_publication() == 0
    assert broker.await_count == 1
    await session.refresh(outbox)
    assert outbox.status == "completed"


async def test_sdk_plan_confirmation_and_fresh_inspection_are_audited_without_sending(
    intent_fixture, monkeypatch
):
    fixture = intent_fixture
    session, _, actor, grants, tokens = fixture[0]
    await session.commit()
    app = FastAPI()

    @asynccontextmanager
    async def sessions():
        yield session

    app.state.mcp_session_factory, app.state.mcp_operations = sessions, {}
    server = MCPServer("Reminder test server")
    register_whatsapp_intent_tools(app, server, fixture[2])
    monkeypatch.setattr(
        "app.presentation.mcp.invocation.get_access_token",
        lambda: AccessToken(
            token=tokens[0],
            client_id=grants[0].client_id,
            scopes=["mcp:read", "mcp:communicate"],
            subject=str(actor.id),
            resource=fixture[2].mcp.resource,
            claims={"grant_id": str(grants[0].id)},
        ),
    )
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert tools["confirm_whatsapp_reminder"].meta == {"capability": "mcp:communicate"}
    prepared = (
        await server.call_tool(
            "prepare_whatsapp_reminder",
            {
                "draft": {
                    "broadcast_id": str(fixture[1].group.id),
                    "message_content": "Please complete the details.",
                },
                "idempotency_key": "sdk-exact-reminder-001",
            },
        )
    ).structured_content
    assert "receipt" in prepared, prepared
    preview = prepared["receipt"]["data"]
    confirmed = (
        await server.call_tool(
            "confirm_whatsapp_reminder",
            {
                "plan_id": preview["plan_id"],
                "plan_hash": preview["plan_hash"],
                "user_confirmed": True,
                "idempotency_key": "sdk-confirm-reminder-001",
            },
        )
    ).structured_content
    assert confirmed["receipt"]["status"] == "queued"
    inspection = (
        await server.call_tool("inspect_whatsapp_intent", {"plan_id": preview["plan_id"]})
    ).structured_content
    assert "receipts" in inspection, inspection
    assert inspection["receipts"]["status_counts"]["queued"] == 6
    assert inspection["receipts"]["confirmed_delivery_count"] == 0
    assert inspection["preview"] == preview["preview"]
    assert inspection["audit_id"] and not session.in_transaction()
    fixture[4].assert_not_awaited()


@pytest.mark.parametrize("received_status", ["sent", "delivered"])
async def test_retained_unknown_receipts_resolve_operation_without_resending(
    intent_fixture, received_status
):
    fixture = intent_fixture
    prepared = await prepare(fixture)
    confirmed = await confirm(fixture, prepared)
    session = fixture[0][0]
    logs = list((await session.scalars(select(WhatsAppMessageLogModel))).all())
    events = []
    for log in logs:
        log.status, log.provider_message_id = "delivery_unknown", f"wamid.reconcile.{uuid.uuid4()}"
        await bind_source_provider_message(session, log, provider_phone_number_id="synthetic-phone")
        events.append(
            VerifiedReceipt(
                "synthetic-phone", log.provider_message_id, received_status, datetime.now(UTC), None
            )
        )
    await refresh_mcp_dispatch_progress(session, batch_id=uuid.UUID(confirmed["data"]["batch_id"]))
    await session.commit()
    operation = await session.get(MCPOperationModel, uuid.UUID(confirmed["operation_id"]))
    assert operation.status == "unknown"
    receipt_ids = await persist_verified_receipts(session, events)
    await session.commit()
    await reconcile_pending_receipts(session, receipt_ids=receipt_ids)
    await session.refresh(operation)
    assert operation.status == "succeeded" and operation.stage == "dispatch_complete"
    assert operation.initial_result == confirmed
    states = list((await session.scalars(select(WhatsAppMessageLogModel.status))).all())
    assert states == [received_status] * 6
    fixture[4].assert_not_awaited()


async def test_worker_crash_after_claim_resumes_remaining_work_without_resending_uncertain_attempt(
    intent_fixture, monkeypatch
):
    fixture = intent_fixture
    prepared = await prepare(fixture)
    confirmed = await confirm(fixture, prepared)
    await fixture[0][0].commit()
    payload = {
        **prepared["data"]["preview"]["worker_payload"],
        "batch_id": confirmed["data"]["batch_id"],
    }
    original = worker_runtime._load_sendable_recipient
    monkeypatch.setattr(
        worker_runtime,
        "_load_sendable_recipient",
        AsyncMock(side_effect=RuntimeError("synthetic worker interruption after claim")),
    )
    with pytest.raises(RuntimeError, match="synthetic worker interruption"):
        await worker_runtime.run_whatsapp_broadcast(**payload)
    fixture[4].assert_not_awaited()
    monkeypatch.setattr(worker_runtime, "_load_sendable_recipient", original)
    await worker_runtime.run_whatsapp_broadcast(**payload)
    states = list((await fixture[0][0].scalars(select(WhatsAppMessageLogModel.status))).all())
    assert states.count("delivery_unknown") == 1 and states.count("submitted") == 5
    assert fixture[4].await_count == 5
    observation = await fixture[0][0].get(MCPOperationModel, uuid.UUID(confirmed["operation_id"]))
    assert observation.status == "unknown" and observation.initial_result == confirmed
