"""Execute the operator queue census without reading notification content."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from scripts.diagnose_mobile_notifications import queued_notification_inventory


@pytest.mark.asyncio
async def test_queue_census_separates_due_future_expired_read_and_other_types():
    metadata = MetaData()
    notifications = Table(
        "mobile_notifications", metadata,
        Column("id", Integer, primary_key=True),
        Column("notification_type", String),
        Column("status", String),
        Column("available_at", DateTime),
        Column("expires_at", DateTime),
        Column("read_at", DateTime),
        Column("body", String),
    )
    now = datetime.now(UTC)
    base = {
        "notification_type": "group_announcement", "status": "queued",
        "available_at": now - timedelta(hours=1), "expires_at": None,
        "read_at": None, "body": "Private content must not enter the census",
    }
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.execute(notifications.insert(), [
                {**base, "id": 1, "read_at": now},
                {**base, "id": 2, "available_at": now + timedelta(hours=1)},
                {**base, "id": 3, "expires_at": now - timedelta(minutes=1)},
                {**base, "id": 4, "status": "cancelled"},
                {**base, "id": 5, "notification_type": "trip_countdown"},
                {**base, "id": 6, "status": "sent"},
            ])
        async with AsyncSession(engine) as session:
            rows = await queued_notification_inventory(session)
        assert len(rows) == 2
        announcement, countdown = rows
        assert announcement["notification_type"] == "group_announcement"
        assert announcement["queued"] == 3
        assert announcement["due_now"] == 1
        assert announcement["scheduled_for_later"] == 1
        assert announcement["expired"] == 1
        assert announcement["already_read_in_app"] == 1
        assert announcement["oldest_available_at"] is not None
        assert countdown["notification_type"] == "trip_countdown"
        assert countdown["queued"] == countdown["due_now"] == 1
        assert "Private content" not in str(rows)
    finally:
        await engine.dispose()
