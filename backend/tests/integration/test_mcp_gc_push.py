"""Actual exact push transactions and native workers with synthetic providers."""

import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken
from sqlalchemy import func, select, text

from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.gc_push_intents import gc_push_operations
from app.application.mcp.gc_push_progress import refresh_push_progress
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.application.mobile import fcm_dispatch_intents, mcp_push_guard
from app.application.mobile.notification_service import dispatch_mobile_push_batch
from app.core.security.mobile_push_crypto import mobile_push_fernet
from app.infrastructure.database.gc_mobile_models import (
    MobileDeviceSessionModel,
    MobileNotificationModel,
    MobilePushDeliveryModel,
)
from app.infrastructure.database.gc_notification_models import GCNotificationBatchModel
from app.infrastructure.database.mcp_gc_push_models import MCPGCPushOriginModel, MCPGCPushPlanModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.presentation.mcp.gc_push_tools import register_gc_push_tools
from tests.authored_notification_fixtures import authored_audience, reviewed_draft
from tests.gc_app_workflow_fixtures import workflow_passenger
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture
from tests.unit.application.test_fcm_dispatch_intents import FcmProvider, _additional_device

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def push_fixture(operations_fixture, monkeypatch):
    session, settings, user, grants, tokens = operations_fixture
    actor, accesses, submissions, claims, registration = await authored_audience(session)
    registration.token_ciphertext = mobile_push_fernet().encrypt(b"synthetic-native-token")
    for grant in grants:
        grant.capabilities = ["mcp:read", "mcp:communicate"]
    draft, _, _ = await reviewed_draft(session, actor, group_ids=[a.group_id for a in accesses])
    await session.commit()
    await session.execute(text("BEGIN"))
    monkeypatch.setattr(mcp_push_guard, "get_settings", lambda: settings)
    service = MCPOperationService(session, settings, gc_push_operations(settings))
    return operations_fixture, actor, accesses, registration, draft, service


async def prepare(fixture, key="prepare-gc-push-001"):
    return await fixture[5].execute(
        access_token=fixture[0][4][0],
        operation_name="prepare_gc_push",
        idempotency_key=key,
        payload={
            "agency_id": str(fixture[1].agency_id),
            "draft_id": str(fixture[4].id),
            "expected_revision": fixture[4].revision,
        },
    )


async def confirm(fixture, prepared, *, connection=0, key="confirm-gc-push-001", plan_hash=None):
    return await fixture[5].execute(
        access_token=fixture[0][4][connection],
        operation_name="confirm_gc_push",
        idempotency_key=key,
        payload={
            "plan_id": prepared["data"]["plan_id"],
            "plan_hash": plan_hash or prepared["data"]["plan_hash"],
        },
    )


async def count(session, model):
    return await session.scalar(select(func.count()).select_from(model))


async def test_preparation_exact_bounded_preview_has_no_outbox_or_token_material(push_fixture):
    fixture = push_fixture
    result = await prepare(fixture)
    preview = result["data"]["preview"]
    assert preview["recipient_count"] == 2 and preview["eligible_device_count"] == 1
    assert preview["no_active_registration_count"] == 1
    assert preview["title"] == "Meet at reception"
    assert "synthetic-native-token" not in json.dumps(result)
    assert "token_lookup_hash" not in json.dumps(result)
    assert await count(fixture[0][0], MobileNotificationModel) == 0
    assert await count(fixture[0][0], MCPGCPushOriginModel) == 0


async def test_confirm_cross_connection_replay_one_batch_and_receipt_stays_queued_after_acceptance(
    push_fixture,
):
    f = push_fixture
    prepared = await prepare(f)
    queued = await confirm(f, prepared, connection=1)
    await f[0][0].commit()
    provider = FcmProvider()
    assert await dispatch_mobile_push_batch(f[0][0], provider=provider, limit=20) == 1
    await f[0][0].commit()
    replay = await confirm(f, prepared)
    assert replay == queued
    assert await count(f[0][0], GCNotificationBatchModel) == 1
    receipts = await refresh_push_progress(f[0][0], uuid.UUID(queued["data"]["batch_id"]))
    assert receipts["device_delivery_counts"]["provider_accepted"] == 1
    assert receipts["device_delivery_counts"]["delivered"] == 0
    assert receipts["stage"] == "dispatch_complete"
    assert (
        await f[0][0].get(MCPOperationModel, uuid.UUID(queued["operation_id"]))
    ).initial_result == queued
    await dispatch_mobile_push_batch(f[0][0], provider=provider, limit=20)
    assert sum(map(len, provider.calls)) == 1


@pytest.mark.parametrize(
    "change", ["content", "revision", "group", "device", "token", "membership"]
)
async def test_drift_rolls_back_whole_confirmation_preserving_prepared_plan(push_fixture, change):
    f = push_fixture
    prepared = await prepare(f)
    if change == "content":
        f[4].body = "Changed after review"
    elif change == "revision":
        f[4].revision += 1
    elif change == "group":
        f[4].group_ids = [str(f[2][0].group_id)]
    elif change == "device":
        await _additional_device(f[0][0], f[3], datetime.now(UTC))
    elif change == "token":
        f[3].token_lookup_hash = "c" * 64
    else:
        f[2][0].passenger_access_enabled = False
    await f[0][0].flush()
    with pytest.raises(MCPOperationError):
        await confirm(f, prepared)
    assert await count(f[0][0], GCNotificationBatchModel) == 0
    assert await count(f[0][0], MobileNotificationModel) == 0
    plan = await f[0][0].get(MCPGCPushPlanModel, uuid.UUID(prepared["data"]["plan_id"]))
    assert plan.status == "prepared"


@pytest.mark.parametrize("change", ["revoked", "narrowed", "orphan", "draft_missing"])
async def test_denied_origin_blocks_unsent_dispatch_without_removing_history(push_fixture, change):
    f = push_fixture
    prepared = await prepare(f)
    queued = await confirm(f, prepared)
    plan = await f[0][0].get(MCPGCPushPlanModel, uuid.UUID(prepared["data"]["plan_id"]))
    if change == "revoked":
        f[0][3][0].revoked_at = datetime.now(UTC)
    elif change == "narrowed":
        f[0][3][0].capabilities = ["mcp:read"]
    elif change == "orphan":
        for origin in await f[0][0].scalars(select(MCPGCPushOriginModel)):
            origin.plan_id = None
    else:
        plan.draft_id = None
    await f[0][0].commit()
    provider = FcmProvider()
    await dispatch_mobile_push_batch(f[0][0], provider=provider, limit=20)
    await f[0][0].commit()
    assert not provider.calls
    assert await count(f[0][0], MobileNotificationModel) == 2
    assert await count(f[0][0], MCPGCPushOriginModel) == 2
    assert await count(f[0][0], GCNotificationBatchModel) == 1
    receipts = await refresh_push_progress(f[0][0], uuid.UUID(queued["data"]["batch_id"]))
    assert receipts["device_delivery_counts"]["failed"] == 1


async def test_unknown_attempt_is_retained_and_never_retried_after_revocation(push_fixture):
    f = push_fixture
    prepared = await prepare(f)
    queued = await confirm(f, prepared)
    await f[0][0].commit()
    provider = FcmProvider(unknown=True)
    await dispatch_mobile_push_batch(f[0][0], provider=provider, limit=20)
    f[0][3][0].revoked_at = datetime.now(UTC)
    await f[0][0].commit()
    await dispatch_mobile_push_batch(
        f[0][0], provider=provider, limit=20, now=datetime.now(UTC) + timedelta(minutes=20)
    )
    assert sum(map(len, provider.calls)) == 1
    receipts = await refresh_push_progress(f[0][0], uuid.UUID(queued["data"]["batch_id"]))
    assert receipts["status"] == "unknown" and receipts["device_delivery_counts"]["unknown"] == 1
    assert (
        await f[0][0].get(MCPOperationModel, uuid.UUID(queued["operation_id"]))
    ).initial_result == queued


async def test_new_device_after_confirmation_is_not_added_to_exact_send(push_fixture):
    f = push_fixture
    prepared = await prepare(f)
    await confirm(f, prepared)
    added = await _additional_device(f[0][0], f[3], datetime.now(UTC))
    await f[0][0].commit()
    provider = FcmProvider()
    await dispatch_mobile_push_batch(f[0][0], provider=provider, limit=20)
    assert sum(map(len, provider.calls)) == 1
    assert str(added.id) not in {m.registration_id for wave in provider.calls for m in wave}
    assert await count(f[0][0], MobilePushDeliveryModel) == 1


async def test_replay_needs_current_communicate_capability(push_fixture):
    f = push_fixture
    prepared = await prepare(f)
    await confirm(f, prepared)
    f[0][3][1].capabilities = ["mcp:read"]
    await f[0][0].flush()
    with pytest.raises(MCPAuthError):
        await confirm(f, prepared, connection=1)


@pytest.mark.parametrize("condition", ["wrong_hash", "expired"])
async def test_exact_hash_and_unexpired_saved_plan_required(push_fixture, condition):
    f = push_fixture
    prepared = await prepare(f)
    plan = await f[0][0].get(MCPGCPushPlanModel, uuid.UUID(prepared["data"]["plan_id"]))
    if condition == "expired":
        plan.prepared_at = datetime.now(UTC) - timedelta(minutes=20)
        plan.expires_at = datetime.now(UTC) - timedelta(minutes=10)
        await f[0][0].flush()
    with pytest.raises(MCPOperationError) as error:
        await confirm(f, prepared, plan_hash="a" * 64 if condition == "wrong_hash" else None)
    assert error.value.code == (
        "gc_push_plan_hash_mismatch"
        if condition == "wrong_hash"
        else "gc_push_plan_expired_or_closed"
    )
    assert await count(f[0][0], GCNotificationBatchModel) == 0


async def test_oversized_people_audience_rejected_without_silent_truncation(push_fixture):
    f = push_fixture
    for index in range(99):
        await workflow_passenger(f[0][0], f[2][0], phone=f"+91987000{index:04d}")
    await f[0][0].flush()
    with pytest.raises(MCPOperationError, match="gc_push_audience_unavailable"):
        await prepare(f)
    assert await count(f[0][0], MCPGCPushPlanModel) == 0
    assert await count(f[0][0], MobileNotificationModel) == 0


async def test_grant_expiring_during_lock_wait_is_checked_at_final_handoff(
    push_fixture, monkeypatch
):
    f = push_fixture
    prepared = await prepare(f)
    await confirm(f, prepared)
    await f[0][0].commit()
    original = fcm_dispatch_intents.lock_original_authority

    async def expired_after_lock(session, notifications):
        denied = await original(session, notifications)
        assert not denied
        grant = await session.get(type(f[0][3][0]), f[0][3][0].id)
        grant.expires_at = datetime.now(UTC)
        await session.flush()
        return denied

    monkeypatch.setattr(fcm_dispatch_intents, "lock_original_authority", expired_after_lock)
    provider = FcmProvider()
    await dispatch_mobile_push_batch(f[0][0], provider=provider, limit=20)
    assert not provider.calls
    assert (await f[0][0].scalar(select(MobilePushDeliveryModel))).status == "failed"


async def test_sdk_preparation_confirmation_and_receipt_read_use_real_wrappers(
    push_fixture, monkeypatch
):
    f = push_fixture
    session, settings, user, grants, tokens = f[0]
    await session.commit()
    app, server = FastAPI(), MCPServer("GC push fixture")

    @asynccontextmanager
    async def sessions():
        yield session

    app.state.mcp_session_factory, app.state.mcp_operations = sessions, {}
    register_gc_push_tools(app, server, settings)
    monkeypatch.setattr(
        "app.presentation.mcp.invocation.get_access_token",
        lambda: AccessToken(
            token=tokens[0],
            client_id=grants[0].client_id,
            scopes=["mcp:read", "mcp:communicate"],
            subject=str(user.id),
            resource=settings.mcp.resource,
            claims={"grant_id": str(grants[0].id)},
        ),
    )
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert set(tools) == {
        "create_gc_push_draft",
        "prepare_gc_push",
        "confirm_gc_push",
        "inspect_gc_push",
    }
    assert tools["confirm_gc_push"].meta == {"capability": "mcp:communicate"}
    prepared = (
        await server.call_tool(
            "prepare_gc_push",
            {
                "draft": {
                    "agency_id": str(f[1].agency_id),
                    "draft_id": str(f[4].id),
                    "expected_revision": 1,
                },
                "idempotency_key": "sdk-prepare-gc-001",
            },
        )
    ).structured_content
    assert "receipt" in prepared, prepared
    plan = prepared["receipt"]["data"]
    confirmed = (
        await server.call_tool(
            "confirm_gc_push",
            {
                "plan_id": plan["plan_id"],
                "plan_hash": plan["plan_hash"],
                "idempotency_key": "sdk-confirm-gc-001",
            },
        )
    ).structured_content
    assert confirmed["receipt"]["status"] == "queued"
    inspected = (
        await server.call_tool("inspect_gc_push", {"plan_id": plan["plan_id"]})
    ).structured_content
    assert inspected["receipts"]["device_delivery_counts"]["retry"] == 1
    assert inspected["receipts"]["device_delivery_counts"]["delivered"] == 0
    assert inspected["preview"] == plan["preview"]
    assert inspected["audit_id"] and not session.in_transaction()


async def test_apns_exact_environment_uses_same_guard_and_retains_accepted_receipt(push_fixture):
    f = push_fixture
    device = await f[0][0].get(MobileDeviceSessionModel, f[3].session_id)
    device.platform = "ios"
    f[3].provider, f[3].platform, f[3].apns_environment = "apns", "ios", "development"
    await f[0][0].flush()
    prepared = await prepare(f)
    assert prepared["data"]["preview"]["devices"][0]["provider"] == "apns"
    queued = await confirm(f, prepared)
    await f[0][0].commit()
    provider = FcmProvider()
    provider.name = "apns"
    await dispatch_mobile_push_batch(f[0][0], provider=provider, limit=20)
    assert sum(map(len, provider.calls)) == 1
    assert provider.calls[0][0].apns_environment == "development"
    observation = await refresh_push_progress(f[0][0], uuid.UUID(queued["data"]["batch_id"]))
    assert observation["device_delivery_counts"]["provider_accepted"] == 1
    assert observation["device_delivery_counts"]["delivered"] == 0


@pytest.mark.parametrize("unknown", [False, True])
async def test_revocation_preserves_previous_accepted_or_unknown_sibling_attempt(
    push_fixture, unknown
):
    f = push_fixture
    await _additional_device(f[0][0], f[3], datetime.now(UTC))
    prepared = await prepare(f)
    queued = await confirm(f, prepared)
    await f[0][0].commit()
    provider = FcmProvider(unknown=unknown)
    await dispatch_mobile_push_batch(f[0][0], provider=provider, limit=1)
    f[0][3][0].revoked_at = datetime.now(UTC)
    await f[0][0].commit()
    await dispatch_mobile_push_batch(f[0][0], provider=provider, limit=20)
    assert sum(map(len, provider.calls)) == 1
    observation = await refresh_push_progress(f[0][0], uuid.UUID(queued["data"]["batch_id"]))
    counts = observation["device_delivery_counts"]
    assert counts["unknown" if unknown else "provider_accepted"] == 1
    assert counts["failed"] == 1 and counts["total"] == 2
    assert (
        await f[0][0].get(MCPOperationModel, uuid.UUID(queued["operation_id"]))
    ).initial_result == queued
