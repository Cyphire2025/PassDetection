"""Real media claim/authority barriers against isolated PostgreSQL, no Meta traffic."""

from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, func, select, update

from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.whatsapp_media_access import MCPWhatsAppMediaAccess
from app.application.mcp.whatsapp_media_uploads import MCPWhatsAppMediaUploads
from app.infrastructure.database.mcp_models import MCPGrantModel
from app.infrastructure.database.mcp_whatsapp_media_models import MCPWhatsAppHeaderMediaModel
from app.infrastructure.database.models import AgencyModel, WhatsAppBroadcastGroupModel
from app.infrastructure.security.upload_security import UploadSecurityService
from tests.integration.test_mcp_artifacts import Evidence, Scanner, Storage, chunks
from tests.integration.test_mcp_whatsapp_media import picture
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
async def media_sessions(operation_sessions, monkeypatch):
    sessions, settings, actor, grants, tokens = operation_sessions
    settings = settings.model_copy(
        update={
            "whatsapp_access_token": "synthetic-token",
            "whatsapp_phone_number_id": "synthetic-sender",
            "malware_quarantine_enabled": False,
        }
    )
    async with sessions() as session:
        await session.execute(
            update(MCPGrantModel)
            .where(MCPGrantModel.id.in_(grants))
            .values(
                capabilities=["mcp:upload", "mcp:communicate"],
                last_used_at=datetime.now(UTC),
            )
        )
        agency = AgencyModel(
            id=uuid.uuid4(), name="Media race", email=f"{uuid.uuid4()}@example.test"
        )
        session.add(agency)
        await session.flush()
        broadcast = WhatsAppBroadcastGroupModel(
            id=uuid.uuid4(),
            agency_id=agency.id,
            name="Media fixture",
            created_by_user_id=actor,
        )
        session.add(broadcast)
        await session.commit()
    storage, scanner, evidence = Storage(), Scanner(), Evidence()
    security = UploadSecurityService(
        settings=settings, scanner=scanner, session_factory=lambda: evidence, storage=storage
    )
    provider = AsyncMock(return_value="synthetic-provider-receipt")
    monkeypatch.setattr(
        "app.application.mcp.whatsapp_media_uploads.upload_whatsapp_image", provider
    )
    return SimpleNamespace(
        sessions=sessions,
        settings=settings,
        actor=actor,
        grants=grants,
        tokens=tokens,
        agency=agency.id,
        broadcast=broadcast.id,
        storage=storage,
        security=security,
        provider=provider,
    )


async def upload(f):
    async with f.sessions() as session:
        principal = await MCPAuthorizationService(session, f.settings).verify_access(f.tokens[0])
        content = picture()
        return await MCPWhatsAppMediaUploads(
            session, f.settings, storage=f.storage, security=f.security
        ).upload(
            principal,
            agency_id=f.agency,
            broadcast_id=f.broadcast,
            filename="header.png",
            media_type="image/png",
            expected_size=len(content),
            expected_sha256=hashlib.sha256(content).hexdigest(),
            idempotency_key="postgres-header-stable-intent",
            body=chunks(content),
        )


async def test_simultaneous_upload_retries_make_one_provider_call(media_sessions):
    f = media_sessions
    # Match the two-slot transfer bound; excess simultaneous transfers fail busy.
    results = await asyncio.wait_for(
        asyncio.gather(*(upload(f) for _ in range(2)), return_exceptions=True), 20
    )
    assert all(isinstance(result, dict) for result in results), results
    assert all(result["media_artifact_id"] == results[0]["media_artifact_id"] for result in results)
    assert all(result["status"] in {"uploading", "ready"} for result in results)
    assert (await upload(f))["status"] == "ready"
    assert f.provider.await_count == 1
    async with f.sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(MCPWhatsAppHeaderMediaModel)
                .where(
                    MCPWhatsAppHeaderMediaModel.user_id == f.actor,
                )
            )
            == 1
        )


async def test_live_attempt_blocks_expired_observation_until_provider_receipt_commits(
    media_sessions, monkeypatch
):
    f = media_sessions
    entered, release, observing = asyncio.Event(), asyncio.Event(), asyncio.Event()
    # The deliberately tiny deadline expires while the valid attempt owns its lock.
    monkeypatch.setattr(
        "app.application.mcp.whatsapp_media_uploads.ATTEMPT_LIFETIME", timedelta(microseconds=1)
    )

    async def provider(**_):
        entered.set()
        await asyncio.wait_for(release.wait(), 10)
        return "receipt-after-deadline"

    f.provider.side_effect = provider
    winner = asyncio.create_task(upload(f))
    await asyncio.wait_for(entered.wait(), 5)
    async with f.sessions() as session:
        row = await session.scalar(
            select(MCPWhatsAppHeaderMediaModel).where(
                MCPWhatsAppHeaderMediaModel.user_id == f.actor
            )
        )
        handle = MCPWhatsAppMediaAccess(session, f.settings).handle(row, f.grants[0])

    async def observe():
        async with f.sessions() as session:
            principal = await MCPAuthorizationService(session, f.settings).verify_access(
                f.tokens[0]
            )
            result = await MCPWhatsAppMediaAccess(session, f.settings).observe(principal, handle)
            await session.commit()
            return result

    engine = f.sessions.kw["bind"].sync_engine

    def waiting(_connection, _cursor, statement, *_):
        if "FROM mcp_grants" in statement and "FOR UPDATE" in statement:
            observing.set()

    event.listen(engine, "before_cursor_execute", waiting)
    observer = asyncio.create_task(observe())
    try:
        await asyncio.wait_for(observing.wait(), 5)
        assert not observer.done()
        release.set()
        result, observed = await asyncio.wait_for(asyncio.gather(winner, observer), 10)
        assert result["status"] == observed["status"] == "ready"
        assert f.provider.await_count == 1
    finally:
        release.set()
        event.remove(engine, "before_cursor_execute", waiting)
        await asyncio.gather(winner, observer, return_exceptions=True)


async def test_revocation_waits_for_provider_receipt_without_discarding_known_result(
    media_sessions,
):
    f = media_sessions
    entered, release, revoking = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def provider(**_):
        entered.set()
        await asyncio.wait_for(release.wait(), 10)
        return "retained-before-revocation"

    f.provider.side_effect = provider
    winner = asyncio.create_task(upload(f))
    await asyncio.wait_for(entered.wait(), 5)

    async def revoke():
        async with f.sessions() as session:
            await session.execute(
                update(MCPGrantModel)
                .where(MCPGrantModel.id == f.grants[0])
                .values(revoked_at=datetime.now(UTC))
            )
            await session.commit()

    engine = f.sessions.kw["bind"].sync_engine

    def waiting(_connection, _cursor, statement, *_):
        if statement.startswith("UPDATE mcp_grants"):
            revoking.set()

    event.listen(engine, "before_cursor_execute", waiting)
    revocation = asyncio.create_task(revoke())
    try:
        await asyncio.wait_for(revoking.wait(), 5)
        assert not revocation.done()
        release.set()
        result, _ = await asyncio.wait_for(asyncio.gather(winner, revocation), 10)
        assert result["status"] == "ready"
        async with f.sessions() as session:
            row = await session.get(
                MCPWhatsAppHeaderMediaModel, uuid.UUID(result["media_artifact_id"])
            )
            assert row.provider_media_id == "retained-before-revocation"
            principal = await MCPAuthorizationService(session, f.settings).verify_access(
                f.tokens[1]
            )
            recovered = await MCPWhatsAppMediaAccess(session, f.settings).recover(principal, row.id)
            await session.commit()
            assert recovered["status"] == "ready"
        assert f.provider.await_count == 1
    finally:
        release.set()
        event.remove(engine, "before_cursor_execute", waiting)
        await asyncio.gather(winner, revocation, return_exceptions=True)


async def test_scanned_owned_image_exact_welcome_plan_and_worker_send_use_one_receipt(
    media_sessions, monkeypatch
):
    from app.application.mcp.operations import MCPOperationService
    from app.infrastructure.database.mcp_communication_models import MCPWhatsAppPlanModel
    from app.infrastructure.database.models import (
        WhatsAppBroadcastRecipientModel,
        WhatsAppMessageLogModel,
    )
    from app.infrastructure.whatsapp import template_settings, worker_runtime
    from app.presentation.api.v1.routes import whatsapp_send
    from app.presentation.mcp.whatsapp_message_tools import message_operations

    f = media_sessions
    f.settings.whatsapp_welcome_template_name = "welcome_v1"
    monkeypatch.setattr(whatsapp_send, "get_settings", lambda: f.settings)
    monkeypatch.setattr(template_settings, "get_settings", lambda: f.settings)
    monkeypatch.setattr(worker_runtime, "get_settings", lambda: f.settings)
    monkeypatch.setattr(worker_runtime, "AsyncSessionFactory", f.sessions)
    message_provider = AsyncMock(return_value=f"wamid.welcome.{uuid.uuid4()}")
    monkeypatch.setattr(worker_runtime, "send_whatsapp_template", message_provider)
    async with f.sessions() as session:
        broadcast = await session.get(WhatsAppBroadcastGroupModel, f.broadcast)
        broadcast.recipient_opt_in_confirmed_at = datetime.now(UTC)
        recipient = WhatsAppBroadcastRecipientModel(
            id=uuid.uuid4(),
            agency_id=f.agency,
            broadcast_group_id=f.broadcast,
            name="Exact imported recipient",
            phone_number="+919123456781",
            normalized_phone_number="+919123456781",
        )
        session.add(recipient)
        await session.commit()
        recipient_id = recipient.id
    media = await upload(f)
    async with f.sessions() as session:
        service = MCPOperationService(session, f.settings, message_operations(f.settings))
        prepared = await service.execute(
            access_token=f.tokens[0],
            operation_name="prepare_whatsapp_message",
            idempotency_key="pg-exact-welcome-plan",
            payload={
                "broadcast_id": str(f.broadcast),
                "message_type": "welcome",
                "message_content": "The exact introductory message.",
                "media_handle": media["media_handle"],
                "recipient_ids": [str(recipient_id)],
            },
        )
        await session.commit()
        confirmed = await service.execute(
            access_token=f.tokens[1],
            operation_name="confirm_whatsapp_message",
            idempotency_key="pg-exact-welcome-confirm",
            payload={
                "plan_id": prepared["data"]["plan_id"],
                "plan_hash": prepared["data"]["plan_hash"],
                "user_confirmed": True,
            },
        )
        await session.commit()
        plan = await session.get(MCPWhatsAppPlanModel, uuid.UUID(prepared["data"]["plan_id"]))
        payload = {**plan.snapshot["worker_payload"], "batch_id": confirmed["data"]["batch_id"]}
    await worker_runtime.run_whatsapp_broadcast(**payload)
    await worker_runtime.run_whatsapp_broadcast(**payload)
    assert f.provider.await_count == 1 and message_provider.await_count == 1
    assert message_provider.await_args.kwargs["header_parameters"] == ["synthetic-provider-receipt"]
    async with f.sessions() as session:
        log = await session.scalar(
            select(WhatsAppMessageLogModel).where(
                WhatsAppMessageLogModel.batch_id == uuid.UUID(confirmed["data"]["batch_id"])
            )
        )
        assert log.status == "submitted"
