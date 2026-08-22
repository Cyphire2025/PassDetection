from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.platform_policies import PlatformPolicies
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    PassportSubmissionModel,
    PlatformSettingModel,
    StorageCleanupJobModel,
)
from app.infrastructure.platform_lifecycle import apply_platform_lifecycle_policies


@pytest.mark.asyncio
async def test_lifecycle_archives_and_purges_only_closed_expired_data(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(tz=UTC)
    agency_id = uuid.uuid4()
    expired_group_id = uuid.uuid4()
    active_group_id = uuid.uuid4()
    expired_submission_id = uuid.uuid4()
    active_submission_id = uuid.uuid4()
    db_session.add_all(
        [
            AgencyModel(
                id=agency_id,
                name="Lifecycle Agency",
                email=f"{agency_id}@example.com",
            ),
            PlatformSettingModel(
                key="global",
                value=PlatformPolicies(
                    auto_archive_closed_groups_days=10,
                    passport_data_retention_days=30,
                    audit_log_retention_days=20,
                ).as_dict(),
            ),
            ClientGroupModel(
                id=expired_group_id,
                name="Expired closed group",
                token=f"expired-{uuid.uuid4()}",
                agency_id=agency_id,
                status="closed",
                created_by_user_id=None,
                created_at=now - timedelta(days=100),
                closed_at=now - timedelta(days=40),
            ),
            ClientGroupModel(
                id=active_group_id,
                name="Old active group",
                token=f"active-{uuid.uuid4()}",
                agency_id=agency_id,
                status="active",
                created_by_user_id=None,
                created_at=now - timedelta(days=100),
            ),
            PassportSubmissionModel(
                id=expired_submission_id,
                group_id=expired_group_id,
                agency_id=agency_id,
                client_name="Expired Passenger",
                image_s3_key=(
                    f"{agency_id}/{expired_group_id}/{expired_submission_id}.jpg"
                ),
            ),
            PassportSubmissionModel(
                id=active_submission_id,
                group_id=active_group_id,
                agency_id=agency_id,
                client_name="Active Passenger",
                image_s3_key=(
                    f"{agency_id}/{active_group_id}/{active_submission_id}.jpg"
                ),
            ),
            AuditLogModel(
                id=uuid.uuid4(),
                action="expired_event",
                entity_type="test",
                created_at=now - timedelta(days=21),
            ),
            AuditLogModel(
                id=uuid.uuid4(),
                action="recent_event",
                entity_type="test",
                created_at=now - timedelta(days=1),
            ),
        ]
    )
    await db_session.flush()

    result = await apply_platform_lifecycle_policies(db_session, now=now)

    assert result.archived_groups == 1
    assert result.scheduled_passport_purge_dates == 1
    assert result.deleted_passports == 1
    assert result.deleted_audit_logs == 1
    assert result.storage_cleanup_jobs == 1
    assert result.storage_objects_scheduled == 1
    assert await db_session.get(PassportSubmissionModel, expired_submission_id) is None
    assert await db_session.get(PassportSubmissionModel, active_submission_id) is not None
    expired_group = await db_session.get(ClientGroupModel, expired_group_id)
    assert expired_group is not None and expired_group.status == "archived"
    audit_actions = set(
        (
            await db_session.execute(select(AuditLogModel.action))
        ).scalars().all()
    )
    assert "expired_event" not in audit_actions
    assert "recent_event" in audit_actions
    assert "platform_lifecycle_policies_applied" in audit_actions
    assert (
        await db_session.scalar(select(func.count()).select_from(StorageCleanupJobModel))
    ) == 1


@pytest.mark.asyncio
async def test_lifecycle_is_idempotent_after_the_first_retention_page(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        PlatformSettingModel(key="global", value=PlatformPolicies().as_dict())
    )
    await db_session.flush()

    first = await apply_platform_lifecycle_policies(db_session)
    second = await apply_platform_lifecycle_policies(db_session)

    assert first.as_dict() == {
        "archived_groups": 0,
        "scheduled_passport_purge_dates": 0,
        "deleted_passports": 0,
        "deleted_notifications": 0,
        "deleted_audit_logs": 0,
        "storage_cleanup_jobs": 0,
        "storage_objects_scheduled": 0,
    }
    assert second == first


@pytest.mark.asyncio
async def test_lifecycle_reschedules_policy_dates_and_never_crosses_legal_hold(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(tz=UTC)
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    submission_id = uuid.uuid4()
    db_session.add_all(
        [
            AgencyModel(
                id=agency_id,
                name="Legal Hold Agency",
                email=f"{agency_id}@example.com",
            ),
            PlatformSettingModel(
                key="global",
                value=PlatformPolicies(passport_data_retention_days=30).as_dict(),
            ),
            ClientGroupModel(
                id=group_id,
                name="Held group",
                token=f"held-{uuid.uuid4()}",
                agency_id=agency_id,
                status="closed",
                created_by_user_id=None,
                created_at=now - timedelta(days=100),
                closed_at=now - timedelta(days=40),
                passport_purge_at=now + timedelta(days=325),
                passport_retention_days_applied=365,
                passport_legal_hold=True,
                passport_legal_hold_reason="Active litigation hold",
                passport_legal_hold_set_at=now - timedelta(days=2),
            ),
            PassportSubmissionModel(
                id=submission_id,
                group_id=group_id,
                agency_id=agency_id,
                client_name="Held Passenger",
                image_s3_key=f"{agency_id}/{group_id}/{submission_id}.jpg",
            ),
            AuditLogModel(
                id=uuid.uuid4(),
                action="held_group_history",
                entity_type="client_group",
                entity_id=str(group_id),
                agency_id=agency_id,
                created_at=now - timedelta(days=400),
            ),
        ]
    )
    await db_session.flush()

    held_result = await apply_platform_lifecycle_policies(db_session, now=now)

    group = await db_session.get(ClientGroupModel, group_id)
    assert group is not None
    assert held_result.scheduled_passport_purge_dates == 1
    assert group.passport_retention_days_applied == 30
    assert group.passport_purge_at == group.closed_at + timedelta(days=30)
    assert await db_session.get(PassportSubmissionModel, submission_id) is not None
    assert "held_group_history" in set(
        (await db_session.execute(select(AuditLogModel.action))).scalars()
    )

    group.passport_legal_hold = False
    group.passport_legal_hold_reason = None
    group.passport_legal_hold_set_at = None
    group.passport_legal_hold_set_by_user_id = None
    await db_session.flush()

    released_result = await apply_platform_lifecycle_policies(db_session, now=now)

    assert released_result.deleted_passports == 1
    assert await db_session.get(PassportSubmissionModel, submission_id) is None
    assert "held_group_history" not in set(
        (await db_session.execute(select(AuditLogModel.action))).scalars()
    )
