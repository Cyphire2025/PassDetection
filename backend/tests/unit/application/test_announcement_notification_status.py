from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import UTC, datetime

import pytest
from sqlalchemy import Column, DateTime, MetaData, String, Table, Uuid
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.application.mobile.announcement_notification_status import announcement_notification_status


@pytest.mark.asyncio
async def test_notification_status_counts_recipients_and_devices_separately_and_scopes_every_query() -> (
    None
):
    # Execute the real aggregate SQL against isolated minimal tables. This
    # intentionally uses two devices for one person and out-of-scope rows.
    metadata = MetaData()
    notifications = Table(
        "mobile_notifications",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("agency_id", Uuid),
        Column("group_id", Uuid),
        Column("gc_group_access_id", Uuid),
        Column("notification_type", String),
        Column("dedupe_key", String),
        Column("status", String),
        Column("failure_code", String),
        Column("read_at", DateTime),
    )
    deliveries = Table(
        "mobile_push_deliveries",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("agency_id", Uuid),
        Column("notification_id", Uuid),
        Column("status", String),
        Column("last_error_code", String),
    )
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    agency, group, access, announcement = [uuid.uuid4() for _ in range(4)]
    ids = [uuid.uuid4() for _ in range(6)]
    base = {
        "agency_id": agency,
        "group_id": group,
        "gc_group_access_id": access,
        "notification_type": "group_announcement",
        "dedupe_key": f"announcement:{announcement}",
        "status": "queued",
        "failure_code": None,
        "read_at": None,
    }
    try:
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.execute(
                notifications.insert(),
                [
                    {**base, "id": ids[0], "status": "sent", "read_at": datetime.now(tz=UTC)},
                    {**base, "id": ids[1], "failure_code": "no_active_registration"},
                    {
                        **base,
                        "id": ids[2],
                        "status": "failed",
                        "failure_code": "secret-token-do-not-expose",
                    },
                    {**base, "id": ids[3], "agency_id": uuid.uuid4()},
                    {**base, "id": ids[4], "group_id": uuid.uuid4()},
                    {**base, "id": ids[5], "dedupe_key": f"announcement:{uuid.uuid4()}"},
                ],
            )
            await connection.execute(
                deliveries.insert(),
                [
                    {
                        "id": uuid.uuid4(),
                        "agency_id": agency,
                        "notification_id": ids[0],
                        "status": "delivered",
                        "last_error_code": None,
                    },
                    {
                        "id": uuid.uuid4(),
                        "agency_id": agency,
                        "notification_id": ids[0],
                        "status": "receipt_pending",
                        "last_error_code": None,
                    },
                    {
                        "id": uuid.uuid4(),
                        "agency_id": agency,
                        "notification_id": ids[2],
                        "status": "failed",
                        "last_error_code": "InvalidCredentials",
                    },
                    {
                        "id": uuid.uuid4(),
                        "agency_id": agency,
                        "notification_id": ids[3],
                        "status": "failed",
                        "last_error_code": None,
                    },
                    {
                        "id": uuid.uuid4(),
                        "agency_id": uuid.uuid4(),
                        "notification_id": ids[0],
                        "status": "failed",
                        "last_error_code": None,
                    },
                ],
            )
        async with AsyncSession(engine) as session:
            summary = await announcement_notification_status(
                session,
                agency_id=agency,
                group_id=group,
                access_id=access,
                announcement_id=announcement,
                provider_enabled=False,
            )
            assert summary.provider_enabled is False
            assert summary.recipient_counts.total == 3
            assert summary.recipient_counts.sent == 1
            assert summary.recipient_counts.read == 1
            assert summary.recipient_counts.no_active_registration == 1
            assert summary.device_delivery_counts.total == 3
            assert summary.device_delivery_counts.delivered == 1
            assert summary.device_delivery_counts.receipt_pending == 1
            assert summary.device_delivery_counts.failed == 1
            assert "secret-token" not in str(asdict(summary))
            assert {(item.scope, item.code) for item in summary.failures} == {
                ("recipient", "no_active_registration"),
                ("recipient", "other"),
                ("device", "InvalidCredentials"),
            }
            empty = await announcement_notification_status(
                session,
                agency_id=agency,
                group_id=group,
                access_id=uuid.uuid4(),
                announcement_id=announcement,
                provider_enabled=True,
            )
            assert empty.recipient_counts.total == empty.device_delivery_counts.total == 0
            assert empty.failures == []
    finally:
        await engine.dispose()
