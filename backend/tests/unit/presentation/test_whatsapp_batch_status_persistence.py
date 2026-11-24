"""Actual database timestamps keep detailed batch progress readable."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.whatsapp_batch_status import get_broadcast_batch_status, router
from app.presentation.dependencies.auth import get_current_active_user


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored_status", "minutes_old", "expected_status", "queued", "uncertain"),
    [
        ("queued", 1, "queued", 1, 0),
        ("queued", 60, "stalled", 0, 1),
        ("processing", 1, "processing", 1, 0),
        ("processing", 60, "stalled", 0, 1),
        ("delivered", 60, "delivered", 0, 0),
        ("failed", 60, "failed", 0, 0),
    ],
)
async def test_actual_persisted_batch_status_keeps_age_counts_and_tenant_scope(
    db_session: AsyncSession,
    stored_status: str,
    minutes_old: int,
    expected_status: str,
    queued: int,
    uncertain: int,
) -> None:
    agency_id, group_id, recipient_id, batch_id = (uuid.uuid4() for _ in range(4))
    actor = User(
        id=uuid.uuid4(),
        email="staff@example.test",
        hashed_password="unused",
        full_name="Staff",
        role=UserRole.AGENCY_STAFF,
        agency_id=agency_id,
    )
    db_session.add(AgencyModel(id=agency_id, name="Agency", email="agency@example.test"))
    await db_session.flush()
    db_session.add(WhatsAppBroadcastGroupModel(id=group_id, agency_id=agency_id, name="List"))
    await db_session.flush()
    db_session.add(
        WhatsAppBroadcastRecipientModel(
            id=recipient_id,
            agency_id=agency_id,
            broadcast_group_id=group_id,
            phone_number="9876543210",
            normalized_phone_number="+919876543210",
        )
    )
    await db_session.flush()
    db_session.add(
        WhatsAppMessageLogModel(
            agency_id=agency_id,
            broadcast_group_id=group_id,
            recipient_id=recipient_id,
            batch_id=batch_id,
            message_type="reminder",
            status=stored_status,
            status_updated_at=datetime.now(UTC) - timedelta(minutes=minutes_old),
        )
    )
    await db_session.commit()
    db_session.expunge_all()
    app = FastAPI()
    app.include_router(router, prefix="/whatsapp")
    app.dependency_overrides[get_current_active_user] = lambda: actor
    app.dependency_overrides[get_db_session] = lambda: db_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        detail = await client.get(f"/whatsapp/batches/{batch_id}")
        assert detail.status_code == 200, detail.text
        data = detail.json()
        assert [item["status"] for item in data["results"]] == [expected_status]
        assert data["queued"] == queued
        assert data["delivery_unknown"] == uncertain
        assert data["sent"] == int(stored_status == "delivered")
        assert data["failed"] == int(stored_status == "failed")
        compact = await client.get(f"/whatsapp/batches/{batch_id}/summary")
        assert compact.status_code == 200, compact.text
        assert {
            key: compact.json()[key] for key in ("queued", "sent", "failed", "delivery_unknown")
        } == {key: data[key] for key in ("queued", "sent", "failed", "delivery_unknown")}
        actor.agency_id = uuid.uuid4()
        assert (await client.get(f"/whatsapp/batches/{batch_id}")).status_code == 404
        assert (await client.get(f"/whatsapp/batches/{batch_id}/summary")).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("minutes_old", "hours_offset", "expected_status"), [(60, 5.5, "stalled"), (1, -4, "queued")]
)
async def test_aware_database_timestamps_keep_their_actual_instant(
    minutes_old: int,
    hours_offset: float,
    expected_status: str,
) -> None:
    row = SimpleNamespace(
        recipient_id=uuid.uuid4(),
        normalized_phone_number="+919876543210",
        status="queued",
        status_updated_at=(datetime.now(UTC) - timedelta(minutes=minutes_old)).astimezone(
            timezone(timedelta(hours=hours_offset))
        ),
        provider_message_id=None,
        error_message=None,
    )
    result = MagicMock()
    result.all.return_value = [row]
    session = AsyncMock()
    session.execute.return_value = result
    response = await get_broadcast_batch_status(
        uuid.uuid4(),
        current_user=SimpleNamespace(role=UserRole.SUPER_ADMIN, agency_id=None),
        session=session,
    )
    assert response.results[0].status == expected_status
