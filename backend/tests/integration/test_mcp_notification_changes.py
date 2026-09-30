"""Durable acknowledgement preserves ownership, first timestamp and atomicity."""

import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text, update

from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.notification_changes import notification_acknowledgement_operation
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AuditLogModel,
    NotificationModel,
    PassportExportHistoryModel,
    UserModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture
from tests.mcp_notification_fixtures import seed_notifications

KEY = "personal-notification-key-001"


@pytest.fixture
async def notifications(operations_fixture):
    f = operations_fixture
    data = await seed_notifications(f[0], f[2].id)
    await f[0].commit()
    await f[0].execute(text("BEGIN"))
    return f, data


async def acknowledge(f, identifier, *, key=KEY, token_index=0, payload=None):
    definition = notification_acknowledgement_operation(f[1].app_secret_key)
    return await MCPOperationService(f[0], f[1], [definition]).execute(
        access_token=f[4][token_index], operation_name=definition.policy.name,
        idempotency_key=key, payload={"notification_id": str(identifier)} if payload is None else payload)


async def state(session, identifier):
    return (await session.execute(select(NotificationModel.is_read, NotificationModel.read_at)
        .where(NotificationModel.id == identifier))).one()


async def test_response_loss_replay_cross_grant_and_new_key_preserve_first_read(notifications):
    f, data = notifications
    identifier = data.rows[0].id
    first = await acknowledge(f, identifier)
    await f[0].commit()
    replay = await acknowledge(f, identifier, token_index=1)
    assert replay == first
    next_ack = await acknowledge(f, identifier, key=KEY + "-second")
    assert first["data"]["changed"] is True and next_ack["data"]["changed"] is False
    assert first["data"]["read_at"] == next_ack["data"]["read_at"]
    assert first["created_entities"] == [] and first["data"]["messages_queued"] == 0
    assert await f[0].scalar(select(func.count()).select_from(MCPOperationModel)) == 2
    audits = (await f[0].scalars(select(AuditLogModel).where(AuditLogModel.action == "notification.mcp_acknowledged"))).all()
    assert len(audits) == 2 and {row.metadata_json["changed"] for row in audits} == {True, False}
    assert "PRIVATE-NOTIFICATION-SENTINEL" not in json.dumps([row.metadata_json for row in audits])
    assert "synthetic@example.test" not in json.dumps(first)
    for model in (MCPArtifactModel, PassportExportHistoryModel, WhatsAppMessageLogModel):
        assert await f[0].scalar(select(func.count()).select_from(model)) == 0
    assert (await state(f[0], data.rows[2].id)).is_read is False


@pytest.mark.parametrize("already_read", [False, True])
async def test_existing_timestamp_never_overwritten(notifications, already_read):
    f, data = notifications
    original = datetime(2025, 1, 2, tzinfo=UTC)
    await f[0].execute(update(NotificationModel).where(NotificationModel.id == data.rows[0].id)
        .values(is_read=already_read, read_at=original))
    result = await acknowledge(f, data.rows[0].id)
    assert result["data"]["read_at"] == original.isoformat()
    assert result["data"]["changed"] is not already_read


@pytest.mark.parametrize("target", [3, 4, None])
async def test_other_user_shared_and_missing_are_indistinguishable(notifications, target):
    f, data = notifications
    identifier = data.rows[target].id if target is not None else uuid.uuid4()
    with pytest.raises(MCPOperationError, match="notification_unavailable"):
        await acknowledge(f, identifier)
    assert await f[0].scalar(select(func.count()).select_from(MCPOperationModel)) == 0


@pytest.mark.parametrize("payload", [{}, {"notification_id": "bad"}, {"notification_id": 42},
    {"notification_id": str(uuid.uuid4()), "agency_id": str(uuid.uuid4())},
    {"notification_id": str(uuid.uuid4()), "user_id": str(uuid.uuid4())}])
async def test_mutation_payload_has_no_scope_override(notifications, payload):
    f, data = notifications
    with pytest.raises(MCPOperationError, match="invalid_notification_acknowledgement"):
        await acknowledge(f, data.rows[0].id, payload=payload)
    assert await f[0].scalar(select(func.count()).select_from(MCPOperationModel)) == 0


async def test_same_key_different_target_conflicts_without_second_change(notifications):
    f, data = notifications
    await acknowledge(f, data.rows[0].id)
    with pytest.raises(MCPOperationError, match="idempotency_conflict"):
        await acknowledge(f, data.rows[2].id)
    assert (await state(f[0], data.rows[2].id)).is_read is False


async def test_audit_failure_rolls_back_read_and_operation_then_same_key_recovers(notifications, monkeypatch):
    f, data = notifications
    original = AuditLogRepository.record
    async def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")
    monkeypatch.setattr(AuditLogRepository, "record", fail)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        await acknowledge(f, data.rows[0].id)
    assert (await state(f[0], data.rows[0].id)) == (False, None)
    assert await f[0].scalar(select(func.count()).select_from(MCPOperationModel)) == 0
    monkeypatch.setattr(AuditLogRepository, "record", original)
    result = await acknowledge(f, data.rows[0].id)
    assert result["data"]["changed"] is True


@pytest.mark.parametrize("restriction", ["revoked", "deployment", "role", "security"])
async def test_current_authority_is_rechecked_before_receipt_replay(notifications, restriction):
    f, data = notifications
    await acknowledge(f, data.rows[0].id)
    await f[0].commit()
    if restriction == "revoked":
        f[3][0].revoked_at = datetime.now(UTC)
    elif restriction == "deployment":
        f[1].mcp.enabled_capabilities = ["mcp:read", "mcp:export"]
    elif restriction == "role":
        await f[0].execute(update(UserModel).where(UserModel.id == f[2].id).values(role="agency_staff"))
    else:
        from app.infrastructure.database.models import UserSecurityStateModel
        await f[0].execute(update(UserSecurityStateModel).where(UserSecurityStateModel.user_id == f[2].id).values(session_version=2))
    await f[0].commit()
    with pytest.raises(MCPAuthError):
        await acknowledge(f, data.rows[0].id)
    assert await f[0].scalar(select(func.count()).select_from(MCPOperationModel)) == 1


async def test_replay_rechecks_saved_recipient_and_never_reacknowledges(notifications):
    f, data = notifications
    await acknowledge(f, data.rows[0].id)
    await f[0].commit()
    await f[0].execute(update(NotificationModel).where(NotificationModel.id == data.rows[0].id).values(user_id=data.other.id))
    await f[0].commit()
    with pytest.raises(MCPOperationError, match="notification_unavailable"):
        await acknowledge(f, data.rows[0].id)
