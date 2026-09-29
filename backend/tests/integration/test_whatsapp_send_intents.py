"""Required HTTP send keys, immutable replies and real SQL outbox recovery."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.infrastructure.database.models import UserSecurityStateModel, WhatsAppMessageLogModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.database.whatsapp_send_intent_models import WhatsAppSendIntentModel
from app.infrastructure.repositories.user_repository import UserRepository
from app.infrastructure.whatsapp import web_publication, worker_runtime
from app.presentation.api.v1.routes.whatsapp_send import queue_broadcast_message, router
from app.presentation.api.v1.routes.whatsapp_send_intents import durable_send
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppSendRequest
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture
from tests.integration.test_mcp_whatsapp_intents import intent_fixture as intent_fixture
from tests.unit.presentation.test_whatsapp_repeatable_reminders import broadcast as broadcast


@pytest.fixture
async def web_fixture(intent_fixture, monkeypatch):
    original, broadcast, settings, _service, provider = intent_fixture
    session = original[0]
    current_user = await UserRepository(session).get_by_id(original[2].id)

    @asynccontextmanager
    async def sessions():
        yield session

    monkeypatch.setattr(web_publication, "AsyncSessionFactory", sessions)
    broker = AsyncMock()
    monkeypatch.setattr(web_publication, "publish_whatsapp_task", broker)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/whatsapp")

    async def database():
        yield session

    async def actor():
        return current_user

    app.dependency_overrides[get_db_session] = database
    route = next(
        item
        for item in app.routes
        if getattr(item, "path", None) == "/api/v1/whatsapp/groups/{group_id}/send"
    )
    role_dependency = next(
        item.call for item in route.dependant.dependencies if item.name == "current_user"
    )
    app.dependency_overrides[role_dependency] = actor
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://localhost:8000"
    ) as client:
        yield SimpleNamespace(
            session=session,
            broadcast=broadcast.group,
            user=current_user,
            actor=original[2],
            client=client,
            broker=broker,
            provider=provider,
            body={
                "message_type": "reminder",
                "message_content": "Website reviewed text",
                "recipient_ids": [str(broadcast.recipients[0].id)],
            },
        )


async def send(f, *, key="stable-website-send-001", body=None, headers=None):
    return await f.client.post(
        f"/api/v1/whatsapp/groups/{f.broadcast.id}/send",
        json=body or f.body,
        headers=headers if headers is not None else {"Idempotency-Key": key},
    )


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Idempotency-Key": "short"},
        [("Idempotency-Key", "stable-header-first"), ("Idempotency-Key", "stable-header-second")],
    ],
)
async def test_http_requires_exactly_one_valid_business_key(web_fixture, headers):
    f = web_fixture
    response = await send(f, headers=headers)
    assert response.status_code == 422, response.text
    assert await f.session.scalar(select(func.count()).select_from(WhatsAppSendIntentModel)) == 0
    assert await f.session.scalar(select(func.count()).select_from(WhatsAppMessageLogModel)) == 0
    f.broker.assert_not_awaited()


async def test_response_loss_replay_returns_original_batch_even_after_receipts_change(web_fixture):
    f = web_fixture
    first = await send(f)
    assert first.status_code == 200, first.text
    original = first.json()
    assert original["queued"] == 1 and original["sent"] == 0
    log = await f.session.scalar(select(WhatsAppMessageLogModel))
    log.status = "delivered"
    await f.session.commit()
    replay = await send(f)
    assert replay.status_code == 200 and replay.json() == original
    assert f.broker.await_count == 1
    assert await f.session.scalar(select(func.count()).select_from(WhatsAppSendIntentModel)) == 1
    assert await f.session.scalar(select(func.count()).select_from(WhatsAppMessageLogModel)) == 1
    conflict = await send(f, body={**f.body, "message_content": "Different deliberate send"})
    assert conflict.status_code == 409


@pytest.mark.parametrize("loss", ["role", "inactive", "security_version", "agency_scope"])
async def test_replay_revalidates_current_web_actor_before_exposing_saved_result(web_fixture, loss):
    f = web_fixture
    assert (await send(f)).status_code == 200
    if loss == "role":
        f.actor.role = "client_manager"
    if loss == "inactive":
        f.actor.is_active = False
    if loss == "security_version":
        security = await f.session.get(UserSecurityStateModel, f.user.id)
        security.session_version += 1
    if loss == "agency_scope":
        f.actor.role = "agency_admin"
        f.actor.agency_id = uuid.uuid4()
        # Use a real separate agency so failure is authorization, not a FK test.
        from app.infrastructure.database.models import AgencyModel

        f.session.add(
            AgencyModel(id=f.actor.agency_id, name="Other agency", email="other@example.test")
        )
    await f.session.commit()
    denied = await send(f)
    assert denied.status_code in {403, 404}
    assert "batch_id" not in denied.json()
    assert f.broker.await_count == 1


async def test_broker_uncertainty_keeps_same_batch_for_durable_republication(web_fixture):
    f = web_fixture
    f.broker.side_effect = RuntimeError("lost broker acknowledgement")
    response = await send(f)
    assert response.status_code == 200, response.text
    intent = await f.session.scalar(select(WhatsAppSendIntentModel))
    assert intent.publication_status == "pending"
    first_payload = f.broker.await_args.kwargs["payload"]
    f.broker.side_effect = None
    intent.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    await f.session.commit()
    assert await web_publication.run_whatsapp_send_publication() == 1
    assert f.broker.await_args.kwargs["payload"] == first_payload
    assert (await send(f)).json() == response.json()
    assert f.broker.await_count == 2
    f.provider.assert_not_awaited()


async def test_failure_after_queue_inserts_rolls_back_business_rows_and_receipt(web_fixture):
    f = web_fixture

    async def fail(*args, **kwargs):
        await queue_broadcast_message(*args, **kwargs)
        raise RuntimeError("fixture failure after writes")

    with pytest.raises(RuntimeError, match="fixture failure"):
        await durable_send(
            f.broadcast.id,
            WhatsAppSendRequest(**f.body),
            current_user=f.user,
            session=f.session,
            idempotency_key="rollback-website-intent",
            queue=fail,
        )
    await f.session.rollback()
    assert await f.session.scalar(select(func.count()).select_from(WhatsAppMessageLogModel)) == 0
    assert await f.session.scalar(select(func.count()).select_from(WhatsAppSendIntentModel)) == 0


async def test_processing_only_crash_recovery_observes_unknown_without_resending(web_fixture):
    f = web_fixture
    response = await send(f)
    assert response.status_code == 200
    intent = await f.session.scalar(select(WhatsAppSendIntentModel))
    log = await f.session.scalar(select(WhatsAppMessageLogModel))
    log.status = "processing"
    intent.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    await f.session.commit()
    assert await web_publication.run_whatsapp_send_publication() == 1
    payload = f.broker.await_args.kwargs["payload"]
    await worker_runtime.run_whatsapp_broadcast(**payload)
    await f.session.refresh(log)
    assert log.status == "delivery_unknown"
    f.provider.assert_not_awaited()
    await f.session.refresh(f.broadcast)
    assert (await send(f)).json() == response.json()


async def test_live_identity_refresh_preserves_restricted_superadmin_access_level(web_fixture):
    from fastapi import HTTPException

    from app.domain.entities.entities import UserRole
    from app.infrastructure.database.models import AgencyModel

    f = web_fixture
    other = AgencyModel(
        id=uuid.uuid4(), name="Restricted other agency", email="restricted@example.test"
    )
    f.session.add(other)
    await f.session.flush()
    restricted = replace(
        f.user,
        actual_role=UserRole.SUPER_ADMIN,
        actual_agency_id=None,
        role=UserRole.AGENCY_STAFF,
        agency_id=other.id,
    )
    with pytest.raises(HTTPException) as denied:
        await durable_send(
            f.broadcast.id,
            WhatsAppSendRequest(**f.body),
            current_user=restricted,
            session=f.session,
            idempotency_key="restricted-website-intent",
            queue=queue_broadcast_message,
        )
    assert denied.value.status_code == 404
    assert await f.session.scalar(select(func.count()).select_from(WhatsAppSendIntentModel)) == 0
