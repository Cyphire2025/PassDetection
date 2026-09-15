from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import UTC, datetime

import pytest
from sqlalchemy import Column, DateTime, MetaData, String, Table, Uuid
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.application.mobile.announcement_notification_status import announcement_notification_status


def _status_tables() -> tuple[MetaData, Table, Table]:
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
    return metadata, notifications, deliveries


@pytest.mark.asyncio
async def test_notification_status_counts_recipients_and_devices_separately_and_scopes_every_query() -> (
    None
):
    # Execute the real aggregate SQL against isolated minimal tables. This
    # intentionally uses two devices for one person and out-of-scope rows.
    metadata, notifications, deliveries = _status_tables()
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


@pytest.mark.asyncio
async def test_fcm_acceptance_unknown_and_provider_receipts_remain_distinct_and_scoped() -> None:
    metadata, notifications, deliveries = _status_tables()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    agency, group, access, announcement = [uuid.uuid4() for _ in range(4)]
    ids = [uuid.uuid4() for _ in range(10)]
    base = {
        "agency_id": agency,
        "group_id": group,
        "gc_group_access_id": access,
        "notification_type": "group_announcement",
        "dedupe_key": f"announcement:{announcement}",
        "read_at": None,
    }
    states = [
        ("sent", None),
        ("sent", None),
        ("failed", "provider_outcome_unknown"),
        ("failed", "provider_outcome_unknown"),
        ("failed", "fcm_authentication_failed"),
        ("failed", "secret-provider-detail"),
        ("queued", "fcm_connection_unavailable"),
        ("cancelled", "announcement_unpublished"),
    ]
    recipients = [
        {
            **base,
            "id": ids[index],
            "status": state,
            "failure_code": code,
            "read_at": datetime.now(tz=UTC) if index in {1, 3} else None,
        }
        for index, (state, code) in enumerate(states)
    ]
    recipients.extend(
        [
            {
                **base,
                "id": ids[8],
                "status": "failed",
                "failure_code": "provider_outcome_unknown",
                "gc_group_access_id": uuid.uuid4(),
            },
            {
                **base,
                "id": ids[9],
                "status": "failed",
                "failure_code": "provider_outcome_unknown",
                "notification_type": "trip_reminder",
            },
        ]
    )
    device_states = [
        (0, "provider_accepted", None),
        (0, "provider_accepted", None),
        (0, "unknown", "provider_outcome_unknown"),
        (2, "unknown", "provider_outcome_unknown"),
        (3, "unknown", "provider_outcome_unknown"),
        (1, "delivered", None),
        (6, "retry", "fcm_connection_unavailable"),
        (4, "failed", "fcm_authentication_failed"),
        (7, "cancelled", "announcement_unpublished"),
        (8, "provider_accepted", None),
        (9, "unknown", "provider_outcome_unknown"),
    ]
    try:
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.execute(notifications.insert(), recipients)
            await connection.execute(
                deliveries.insert(),
                [
                    {
                        "id": uuid.uuid4(),
                        "agency_id": agency,
                        "notification_id": ids[index],
                        "status": state,
                        "last_error_code": code,
                    }
                    for index, state, code in device_states
                ],
            )
        async with AsyncSession(engine) as session:
            summary = await announcement_notification_status(
                session,
                agency_id=agency,
                group_id=group,
                access_id=access,
                announcement_id=announcement,
                provider_enabled=True,
            )
            assert asdict(summary.recipient_counts) == {
                "total": 8,
                "queued": 1,
                "sent": 2,
                "failed": 2,
                "cancelled": 1,
                "read": 2,
                "no_active_registration": 0,
                "unknown": 2,
            }
            assert asdict(summary.device_delivery_counts) == {
                "total": 9,
                "submitting": 0,
                "retry": 1,
                "receipt_pending": 0,
                "delivered": 1,
                "failed": 1,
                "cancelled": 1,
                "provider_accepted": 2,
                "unknown": 3,
            }
            failures = {(item.scope, item.code): item.count for item in summary.failures}
            assert failures[("recipient", "provider_outcome_unknown")] == 2
            assert failures[("device", "provider_outcome_unknown")] == 3
            assert failures[("recipient", "other")] == 1
            assert "secret-provider-detail" not in str(asdict(summary))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_fcm_failure_codes_are_bounded_and_arbitrary_provider_details_are_redacted() -> None:
    codes = [
        "provider_outcome_unknown",
        "fcm_connection_unavailable",
        "fcm_quota_exceeded",
        "fcm_unavailable",
        "DeviceNotRegistered",
        "fcm_sender_id_mismatch",
        "fcm_authentication_failed",
        "fcm_invalid_argument",
        "fcm_provider_rejected",
        "fcm_credentials_missing",
        "fcm_credentials_invalid",
        "fcm_credentials_project_or_type_mismatch",
        "fcm_credentials_path_must_be_absolute",
        "fcm_credentials_unavailable",
    ]
    unsafe_codes = ["secret-token-example", "credentials:/private/file.json", "unknown-user-input"]
    metadata, notifications, deliveries = _status_tables()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    agency, group, access, announcement = [uuid.uuid4() for _ in range(4)]
    pairs = [(uuid.uuid4(), code) for code in codes + unsafe_codes]
    try:
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.execute(
                notifications.insert(),
                [
                    {
                        "id": identifier,
                        "agency_id": agency,
                        "group_id": group,
                        "gc_group_access_id": access,
                        "notification_type": "group_announcement",
                        "dedupe_key": f"announcement:{announcement}",
                        "status": "failed",
                        "failure_code": code,
                        "read_at": None,
                    }
                    for identifier, code in pairs
                ],
            )
            await connection.execute(
                deliveries.insert(),
                [
                    {
                        "id": uuid.uuid4(),
                        "agency_id": agency,
                        "notification_id": identifier,
                        "status": "failed",
                        "last_error_code": code,
                    }
                    for identifier, code in pairs
                ],
            )
        async with AsyncSession(engine) as session:
            summary = await announcement_notification_status(
                session,
                agency_id=agency,
                group_id=group,
                access_id=access,
                announcement_id=announcement,
                provider_enabled=True,
            )
            failures = {(item.scope, item.code): item.count for item in summary.failures}
            assert failures == {
                **{(scope, code): 1 for scope in ("recipient", "device") for code in codes},
                ("recipient", "other"): 3,
                ("device", "other"): 3,
            }
            assert all(code not in str(asdict(summary)) for code in unsafe_codes)
    finally:
        await engine.dispose()
