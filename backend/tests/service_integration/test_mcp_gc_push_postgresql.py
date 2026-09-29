"""Real PostgreSQL races in retained UUID schemas; providers remain synthetic."""

import asyncio
import os
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.mcp.gc_push_drafts import gc_push_draft_operation
from app.application.mcp.gc_push_intents import gc_push_operations
from app.application.mcp.gc_push_progress import refresh_push_progress
from app.application.mcp.operations import MCPOperationService
from app.application.mobile import mcp_push_guard
from app.application.mobile.authored_notification_service import send_notification
from app.application.mobile.notification_service import dispatch_mobile_push_batch
from app.core.security.mobile_push_crypto import mobile_push_fernet
from app.infrastructure.database.gc_mobile_models import MobilePushDeliveryModel
from app.infrastructure.database.gc_notification_models import (
    GCNotificationBatchModel,
    GCNotificationDraftModel,
)
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import UserModel, UserSecurityStateModel
from tests.authored_notification_fixtures import authored_audience, reviewed_draft
from tests.integration.test_mcp_operations import seed_identity
from tests.postgresql_schema import create_isolated_postgresql_tables
from tests.service_integration.test_mcp_concurrency_postgresql import mcp_sessions as mcp_sessions
from tests.unit.application.test_fcm_dispatch_intents import FcmProvider as BaseFcmProvider


class FcmProvider(BaseFcmProvider):
    async def send(self, messages):
        tickets = await super().send(messages)
        return [
            replace(ticket, provider_ticket_id=f"projects/test/messages/{uuid.uuid4()}")
            if ticket.accepted
            else ticket
            for ticket in tickets
        ]


pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"
    ),
]


@pytest.fixture
async def push_sessions(mcp_sessions, monkeypatch):
    parent_sessions, settings = mcp_sessions
    parent_engine = parent_sessions.kw["bind"]
    schema = f"fcm_dispatch_test_{uuid.uuid4().hex}"
    async with parent_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        parent_engine.url,
        poolclass=NullPool,
        connect_args={
            "server_settings": {
                "search_path": schema,
                "lock_timeout": "5000",
                "statement_timeout": "15000",
            }
        },
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await create_isolated_postgresql_tables(connection, schema)
        async with sessions() as session:
            session.add(MCPControlModel(id=1, enabled=True))
            user, grants, tokens = await seed_identity(session, settings)
            for grant in grants:
                grant.capabilities = ["mcp:read", "mcp:communicate", "mcp:change"]
            actor, accesses, _, _, registration = await authored_audience(session)
            registration.token_ciphertext = mobile_push_fernet().encrypt(b"synthetic-pg-push")
            draft, _, _ = await reviewed_draft(
                session, actor, group_ids=[a.group_id for a in accesses]
            )
            await session.commit()
        monkeypatch.setattr(mcp_push_guard, "get_settings", lambda: settings)
        yield sessions, settings, user.id, [g.id for g in grants], tokens, actor, draft.id
    finally:
        await engine.dispose()
        # Retained deliberately: this lane never deletes a database, schema or row.
        print(f"MCP_GC_PUSH_SCHEMA_RETAINED={schema}")


async def invoke(f, name, payload, *, connection=0, key=None):
    async with f[0]() as session:
        result = await MCPOperationService(
            session, f[1], (*gc_push_operations(f[1]), gc_push_draft_operation())
        ).execute(
            access_token=f[4][connection],
            operation_name=name,
            idempotency_key=key or f"pg-{name}-001",
            payload=payload,
        )
        await session.commit()
        return result


async def prepare(f, *, key=None, connection=0):
    return await invoke(
        f,
        "prepare_gc_push",
        {"agency_id": str(f[5].agency_id), "draft_id": str(f[6]), "expected_revision": 1},
        key=key,
        connection=connection,
    )


def confirmation(prepared):
    return {"plan_id": prepared["data"]["plan_id"], "plan_hash": prepared["data"]["plan_hash"]}


async def worker(f, provider, *, now=None, limit=20):
    async with f[0]() as session:
        result = await dispatch_mobile_push_batch(session, provider=provider, limit=limit, now=now)
        await session.commit()
        return result


async def test_same_key_cross_connection_confirm_creates_one_native_batch(push_sessions):
    f = push_sessions
    prepared = await prepare(f)
    receipts = await asyncio.wait_for(
        asyncio.gather(
            *[
                invoke(f, "confirm_gc_push", confirmation(prepared), connection=i % 2)
                for i in range(6)
            ]
        ),
        20,
    )
    assert all(row == receipts[0] for row in receipts)
    async with f[0]() as session:
        assert await session.scalar(select(func.count()).select_from(GCNotificationBatchModel)) == 1
        assert await session.scalar(select(func.count()).select_from(MobilePushDeliveryModel)) == 1


async def test_original_grant_revocation_waits_for_live_provider_handoff(push_sessions):
    f = push_sessions
    prepared = await prepare(f)
    queued = await invoke(f, "confirm_gc_push", confirmation(prepared), connection=1)
    entered, release, revoke_started, revoked = (asyncio.Event() for _ in range(4))

    class HeldProvider(FcmProvider):
        async def send(self, messages):
            entered.set()
            await release.wait()
            return await super().send(messages)

    async def revoke():
        async with f[0]() as session:
            revoke_started.set()
            await session.execute(
                update(MCPGrantModel)
                .where(MCPGrantModel.id == f[3][0])
                .values(revoked_at=datetime.now(UTC))
            )
            await session.commit()
            revoked.set()

    provider = HeldProvider()
    task = asyncio.create_task(worker(f, provider))
    await asyncio.wait_for(entered.wait(), 5)
    revocation = asyncio.create_task(revoke())
    await revoke_started.wait()
    await asyncio.sleep(0.15)
    assert not revoked.is_set()
    release.set()
    await asyncio.wait_for(asyncio.gather(task, revocation), 10)
    assert sum(map(len, provider.calls)) == 1
    async with f[0]() as session:
        observation = await refresh_push_progress(session, uuid.UUID(queued["data"]["batch_id"]))
        assert observation["device_delivery_counts"]["provider_accepted"] == 1
        assert observation["device_delivery_counts"]["delivered"] == 0


async def test_revocation_winner_blocks_all_provider_calls(push_sessions):
    f = push_sessions
    prepared = await prepare(f)
    await invoke(f, "confirm_gc_push", confirmation(prepared))
    async with f[0]() as session:
        await session.execute(
            update(MCPGrantModel)
            .where(MCPGrantModel.id == f[3][0])
            .values(revoked_at=datetime.now(UTC))
        )
        await session.commit()
    provider = FcmProvider()
    await worker(f, provider)
    assert not provider.calls
    async with f[0]() as session:
        rows = list(await session.scalars(select(MobilePushDeliveryModel)))
        assert len(rows) == 1 and rows[0].status == "failed"


async def test_ordinary_plus_two_mcp_plans_dispatch_separate_origin_waves(push_sessions):
    f = push_sessions
    first = await prepare(f)
    await invoke(f, "confirm_gc_push", confirmation(first))
    second = await prepare(f, key="pg-prepare-distinct-002", connection=1)
    await invoke(
        f, "confirm_gc_push", confirmation(second), key="pg-confirm-distinct-002", connection=1
    )
    async with f[0]() as session:
        draft, _, request = await reviewed_draft(session, f[5])
        await send_notification(
            session, agency_id=f[5].agency_id, actor_id=f[5].id, draft_id=draft.id, body=request
        )
        await session.commit()
    provider = FcmProvider()
    await asyncio.wait_for(asyncio.gather(*(worker(f, provider, limit=1) for _ in range(3))), 15)
    for _ in range(3):
        await worker(f, provider, limit=1)
    assert sum(map(len, provider.calls)) == 3
    assert len({m.notification_id for wave in provider.calls for m in wave}) == 3


async def test_interrupted_attempt_recovers_unknown_without_second_provider_call(push_sessions):
    f = push_sessions
    prepared = await prepare(f)
    queued = await invoke(f, "confirm_gc_push", confirmation(prepared))
    provider = FcmProvider(interrupt=True)
    with pytest.raises(RuntimeError, match="worker interrupted"):
        await worker(f, provider)
    await worker(f, provider, now=datetime.now(UTC) + timedelta(minutes=16))
    assert sum(map(len, provider.calls)) == 1
    async with f[0]() as session:
        result = await refresh_push_progress(session, uuid.UUID(queued["data"]["batch_id"]))
        assert result["status"] == "unknown"
        assert (
            await session.get(MCPOperationModel, uuid.UUID(queued["operation_id"]))
        ).initial_result == queued


async def test_terminal_observation_skips_operation_lock_then_inspection_catches_up(push_sessions):
    f = push_sessions
    prepared = await prepare(f)
    queued = await invoke(f, "confirm_gc_push", confirmation(prepared))
    async with f[0]() as held:
        operation = await held.scalar(
            select(MCPOperationModel)
            .where(MCPOperationModel.id == uuid.UUID(queued["operation_id"]))
            .with_for_update()
        )
        await asyncio.wait_for(worker(f, FcmProvider()), 5)
        assert operation.status == "queued"
        await held.rollback()
    async with f[0]() as session:
        result = await refresh_push_progress(session, uuid.UUID(queued["data"]["batch_id"]))
        operation = await session.get(MCPOperationModel, uuid.UUID(queued["operation_id"]))
        assert result["stage"] == operation.stage == "dispatch_complete"
        assert operation.initial_result == queued
        await session.commit()


@pytest.mark.parametrize("authority_change", ["control", "role", "security"])
async def test_authority_control_and_identity_updates_wait_for_live_handoff(
    push_sessions, authority_change
):
    f = push_sessions
    prepared = await prepare(f)
    await invoke(f, "confirm_gc_push", confirmation(prepared))
    entered, release, started, changed = (asyncio.Event() for _ in range(4))

    class HeldProvider(FcmProvider):
        async def send(self, messages):
            entered.set()
            await release.wait()
            return await super().send(messages)

    async def change_authority():
        async with f[0]() as session:
            started.set()
            if authority_change == "control":
                await session.execute(
                    update(MCPControlModel).where(MCPControlModel.id == 1).values(enabled=False)
                )
            elif authority_change == "role":
                await session.execute(
                    update(UserModel).where(UserModel.id == f[2]).values(role="agency_admin")
                )
            else:
                await session.execute(
                    update(UserSecurityStateModel)
                    .where(UserSecurityStateModel.user_id == f[2])
                    .values(session_version=2)
                )
            await session.commit()
            changed.set()

    provider = HeldProvider()
    sending = asyncio.create_task(worker(f, provider))
    await asyncio.wait_for(entered.wait(), 5)
    changing = asyncio.create_task(change_authority())
    await started.wait()
    await asyncio.sleep(0.15)
    assert not changed.is_set()
    release.set()
    await asyncio.wait_for(asyncio.gather(sending, changing), 10)
    assert sum(map(len, provider.calls)) == 1


async def test_failed_confirmation_transaction_retains_no_queue_and_can_retry(push_sessions):
    f = push_sessions
    prepared = await prepare(f)
    async with f[0]() as session:
        result = await MCPOperationService(session, f[1], gc_push_operations(f[1])).execute(
            access_token=f[4][0],
            operation_name="confirm_gc_push",
            idempotency_key="pg-confirm-gc-rollback-001",
            payload=confirmation(prepared),
        )
        assert result["status"] == "queued"
        await session.rollback()
    async with f[0]() as session:
        assert await session.scalar(select(func.count()).select_from(GCNotificationBatchModel)) == 0
        assert await session.scalar(select(func.count()).select_from(MobilePushDeliveryModel)) == 0
    queued = await invoke(
        f, "confirm_gc_push", confirmation(prepared), key="pg-confirm-gc-rollback-001"
    )
    assert queued["status"] == "queued"


async def test_concurrent_new_draft_creation_is_append_only_across_grants(push_sessions):
    f = push_sessions
    async with f[0]() as session:
        old = await session.get(GCNotificationDraftModel, f[6])
        group_ids, old_body = old.group_ids, old.body
    value = {
        "agency_id": str(f[5].agency_id),
        "title": "New authored draft",
        "body": "Exact new content",
        "group_ids": group_ids,
    }
    receipts = await asyncio.wait_for(
        asyncio.gather(
            *[invoke(f, "create_gc_push_draft", value, connection=index % 2) for index in range(6)]
        ),
        15,
    )
    assert all(receipt == receipts[0] for receipt in receipts)
    async with f[0]() as session:
        assert await session.scalar(select(func.count()).select_from(GCNotificationDraftModel)) == 2
        assert (await session.get(GCNotificationDraftModel, f[6])).body == old_body
        assert await session.scalar(select(func.count()).select_from(GCNotificationBatchModel)) == 0
