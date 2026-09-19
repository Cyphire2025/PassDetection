"""Exercise archive lifecycle, agency scope and durable send protection."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    UserModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.whatsapp.worker_runtime import _load_sendable_recipient
from app.presentation.api.v1.routes import whatsapp
from app.presentation.dependencies.auth import get_current_active_user


async def _fixture(session: AsyncSession):
    agency_id, other_agency_id, actor_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    actor = User(
        id=actor_id,
        agency_id=agency_id,
        email="staff@example.test",
        full_name="Staff",
        hashed_password="unused",
        role=UserRole.AGENCY_STAFF,
    )
    group = WhatsAppBroadcastGroupModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        name="Completed tour",
        organizing_company_name="Agency",
        recipient_opt_in_confirmed_at=datetime.now(tz=UTC),
    )
    other = WhatsAppBroadcastGroupModel(
        id=uuid.uuid4(),
        agency_id=other_agency_id,
        name="Other agency",
        organizing_company_name="Other",
    )
    recipient = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(),
        broadcast_group_id=group.id,
        agency_id=agency_id,
        name="Traveller",
        phone_number="9876543210",
        normalized_phone_number="+919876543210",
    )
    log = WhatsAppMessageLogModel(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        broadcast_group_id=group.id,
        recipient_id=recipient.id,
        agency_id=agency_id,
        message_type="welcome",
        status="delivered",
    )
    session.add_all(
        [
            AgencyModel(id=agency_id, name="Agency", email="agency@example.test"),
            AgencyModel(id=other_agency_id, name="Other", email="other@example.test"),
            UserModel(
                id=actor.id,
                agency_id=agency_id,
                email=actor.email,
                full_name=actor.full_name,
                hashed_password="unused",
                role=actor.role.value,
            ),
            group,
            other,
            recipient,
            log,
        ]
    )
    await session.commit()
    app = FastAPI()
    app.include_router(whatsapp.router, prefix="/whatsapp")
    app.dependency_overrides[get_current_active_user] = lambda: actor
    app.dependency_overrides[get_db_session] = lambda: session
    return (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test"),
        group,
        other,
        recipient,
        log,
    )


@pytest.mark.asyncio
async def test_archive_restore_preserves_contacts_history_and_is_idempotent(db_session):
    client, group, other, recipient, log = await _fixture(db_session)
    async with client:
        path = f"/whatsapp/groups/{group.id}"
        assert [row["id"] for row in (await client.get("/whatsapp/groups")).json()] == [
            str(group.id)
        ]
        response = await client.post(f"{path}/archive")
        assert response.status_code == 200, response.text
        archived = response.json()
        assert archived["is_archived"] is True
        assert archived["archived_at"]
        assert archived["recipient_count"] == 1
        repeated = (await client.post(f"{path}/archive")).json()["archived_at"]
        # SQLite's datetime adapter drops tzinfo; PostgreSQL retains it.
        assert repeated.rstrip("Z") == archived["archived_at"].rstrip("Z")
        assert (await client.get("/whatsapp/groups")).json() == []
        assert [
            row["id"] for row in (await client.get("/whatsapp/groups?archived=true")).json()
        ] == [str(group.id)]
        assert (await client.get(path)).json()["recipients"][0]["id"] == str(recipient.id)
        assert (
            await db_session.execute(
                select(WhatsAppMessageLogModel).where(WhatsAppMessageLogModel.id == log.id)
            )
        ).scalar_one().status == "delivered"
        assert (await client.post(f"/whatsapp/groups/{other.id}/archive")).status_code == 404
        assert (await client.post(f"/whatsapp/groups/{other.id}/restore")).status_code == 404
        restored = await client.post(f"{path}/restore")
        assert restored.status_code == 200, restored.text
        assert restored.json()["archived_at"] is None
        assert restored.json()["is_archived"] is False
        assert (await client.post(f"{path}/restore")).status_code == 200
        assert (await client.get("/whatsapp/groups?archived=true")).json() == []
        assert (await client.patch(path, data={"name": "Next trip"})).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery_status", ["queued", "processing", "delivery_unknown"])
async def test_archive_waits_for_active_delivery(db_session, delivery_status):
    client, group, _, _, log = await _fixture(db_session)
    log.status = delivery_status
    await db_session.flush()
    async with client:
        response = await client.post(f"/whatsapp/groups/{group.id}/archive")
        assert response.status_code == 409
        assert "before archiving" in response.json()["detail"]
        assert group.archived_at is None
        assert log.status == delivery_status


@pytest.mark.asyncio
async def test_archive_also_checks_delivery_state_without_a_pending_log(db_session):
    client, group, _, recipient, _ = await _fixture(db_session)
    db_session.add(
        WhatsAppRecipientMessageStateModel(
            id=uuid.uuid4(),
            agency_id=group.agency_id,
            broadcast_group_id=group.id,
            recipient_id=recipient.id,
            message_type="welcome",
            status="queued",
        )
    )
    await db_session.flush()
    async with client:
        assert (await client.post(f"/whatsapp/groups/{group.id}/archive")).status_code == 409
        assert group.archived_at is None


@pytest.mark.asyncio
async def test_archived_lists_reject_send_resend_and_roster_edits(db_session):
    client, group, _, recipient, _ = await _fixture(db_session)
    async with client:
        path = f"/whatsapp/groups/{group.id}"
        assert (await client.post(f"{path}/archive")).status_code == 200
        await db_session.commit()
        responses = [
            await client.post(f"{path}/send", json={"message_type": "welcome"}),
            await client.post(
                f"{path}/recipients/{recipient.id}/resend", json={"message_type": "welcome"}
            ),
            await client.post(
                f"{path}/recipients/resend",
                json={
                    "request_id": str(uuid.uuid4()),
                    "message_type": "welcome",
                    "recipient_ids": [str(recipient.id)],
                },
            ),
            await client.patch(path, data={"name": "Cannot change"}),
            await client.patch(
                f"{path}/recipients/{recipient.id}", json={"phone_number": "9876543211"}
            ),
            await client.delete(f"{path}/recipients/{recipient.id}"),
            await client.post(
                f"{path}/recipients",
                data={
                    "contacts_json": json.dumps([{"name": "New", "phone_number": "9876543212"}]),
                    "recipient_opt_in_confirmed": "true",
                },
            ),
        ]
        for response in responses:
            assert response.status_code == 409, response.text
            assert "Restore" in response.json()["detail"]


@pytest.mark.asyncio
async def test_worker_rechecks_archive_before_loading_or_sending_recipient():
    result = SimpleNamespace(
        scalar_one_or_none=lambda: SimpleNamespace(archived_at=datetime.now(tz=UTC))
    )
    session = SimpleNamespace(execute=AsyncMock(return_value=result))
    recipient, reason = await _load_sendable_recipient(
        session,
        log=SimpleNamespace(broadcast_group_id=uuid.uuid4()),
        expected_batch_id=uuid.uuid4(),
    )
    assert recipient is None
    assert "archived" in reason
    assert session.execute.await_count == 1
