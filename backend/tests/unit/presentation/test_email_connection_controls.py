"""Mailbox monitoring and AI consent controls through the public route aliases."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.email_models import EmailConnectionModel
from app.presentation.api.v1.routes import email_connection_ai_settings as ai
from app.presentation.api.v1.routes import email_connection_monitoring as monitoring
from app.presentation.api.v1.routes import email_integration_connections as api
from app.presentation.api.v1.schemas.email_integration_schemas import (
    EmailAiConnectionSettingsRequest,
)


@pytest.fixture
def mailbox(monkeypatch):
    actor = User.create(
        "owner@example.test", "unused", "Owner", UserRole.AGENCY_STAFF, agency_id=uuid.uuid4()
    )
    connection = EmailConnectionModel(
        id=uuid.uuid4(),
        agency_id=actor.agency_id,
        owner_user_id=actor.id,
        provider="gmail",
        provider_account_id="synthetic-account",
        email_address=actor.email,
        status="active",
        sync_state="running",
        sync_generation=8,
        sync_lease_token=uuid.uuid4(),
        sync_lease_expires_at=datetime.now(UTC),
        ai_processing_enabled=False,
    )
    settings = SimpleNamespace(
        email_integrations_enabled=True, email_sync_enabled=True, email_ai_runtime_ready=True
    )
    owned, audit = AsyncMock(return_value=connection), AsyncMock()
    for owner in (monitoring, ai):
        monkeypatch.setattr(owner, "get_settings", lambda: settings)
        monkeypatch.setattr(owner, "_owned_connection", owned)
        monkeypatch.setattr(owner, "AuditLogRepository", lambda _: SimpleNamespace(record=audit))
    session = Mock(commit=AsyncMock(), execute=AsyncMock())
    return actor, connection, settings, owned, audit, session


@pytest.mark.parametrize(
    ("action", "queued"),
    [("sync", True), ("sync", False), ("pause", False), ("resume", True), ("resume", False)],
)
async def test_monitoring_transitions_keep_fence_and_commit_before_queue(
    mailbox, monkeypatch, action: str, queued: bool
) -> None:
    actor, connection, _settings, owned, audit, session = mailbox
    if action == "resume":
        connection.status = "paused"
        connection.paused_at = datetime.now(UTC)
    events = []
    session.commit.side_effect = lambda: events.append("commit")

    def enqueue(value):
        assert value is connection and events == ["commit"]
        events.append("enqueue")
        return queued

    queue = Mock(side_effect=enqueue)
    monkeypatch.setattr(monitoring, "_enqueue_connection_sync", queue)
    result = await getattr(api, f"{action}_connection")(connection.id, actor, session)

    owned.assert_awaited_once_with(
        session,
        connection_id=connection.id,
        owner_user_id=actor.id,
        agency_id=actor.agency_id,
        for_update=True,
    )
    assert result.connection_id == connection.id
    if action == "pause":
        assert connection.status == "paused" and connection.sync_state == "idle"
        assert connection.sync_generation == 9 and connection.next_sync_at is None
        assert connection.sync_lease_token is None and connection.sync_lease_expires_at is None
        assert connection.paused_at is not None
        assert audit.await_args.kwargs["action"] == "email_connection_paused"
        session.commit.assert_not_awaited()  # request dependency commits this transition
        queue.assert_not_called()
    else:
        assert connection.status == "active" and connection.sync_state == "queued"
        assert connection.next_sync_at is not None
        assert connection.sync_generation == (9 if action == "resume" else 8)
        assert ("next" in result.message.lower()) is (not queued)
        if action == "resume":
            assert connection.paused_at is None
        audit.assert_not_awaited()
        assert events == ["commit", "enqueue"]


@pytest.mark.parametrize("action", ["sync", "resume"])
@pytest.mark.parametrize("disabled", ["email_integrations_enabled", "email_sync_enabled"])
async def test_disabled_monitoring_never_loads_or_mutates_a_mailbox(mailbox, action, disabled):
    actor, connection, settings, owned, audit, session = mailbox
    setattr(settings, disabled, False)
    with pytest.raises(HTTPException) as failure:
        await getattr(api, f"{action}_connection")(connection.id, actor, session)
    assert failure.value.status_code == 503
    owned.assert_not_awaited()
    audit.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.parametrize(
    ("action", "status"),
    [
        ("sync", "paused"),
        ("sync", "disconnected"),
        ("resume", "active"),
        ("resume", "disconnected"),
        ("pause", "disconnected"),
    ],
)
async def test_invalid_monitoring_transition_preserves_state(mailbox, action, status):
    actor, connection, _settings, _owned, audit, session = mailbox
    connection.status = status
    with pytest.raises(HTTPException) as failure:
        await getattr(api, f"{action}_connection")(connection.id, actor, session)
    assert failure.value.status_code == 409
    assert connection.status == status and connection.sync_generation == 8
    audit.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("already_enabled", [False, True])
async def test_ai_opt_in_preserves_existing_watermark_and_reports_effective_policy(
    mailbox, monkeypatch, already_enabled: bool
) -> None:
    actor, connection, _settings, owned, audit, session = mailbox
    old_watermark = datetime(2026, 1, 1, tzinfo=UTC) if already_enabled else None
    connection.ai_processing_enabled = already_enabled
    connection.ai_enabled_at = old_watermark
    policy = AsyncMock(return_value=True)
    monkeypatch.setattr(ai, "email_ai_policy_allows", policy)

    result = await api.update_connection_ai_settings(
        connection.id, EmailAiConnectionSettingsRequest(enabled=True), actor, session
    )

    assert result.enabled is True and result.effective_enabled is True
    assert result.message == "Travel email analysis is active for this account."
    assert connection.ai_enabled_at == (old_watermark or connection.updated_at)
    assert owned.await_args.kwargs["owner_user_id"] == actor.id
    policy.assert_awaited_once_with(
        session, agency_id=actor.agency_id, owner_user_id=actor.id, connection_id=connection.id
    )
    assert audit.await_args.kwargs["action"] == "email_ai.account_enabled"
    session.execute.assert_not_awaited()
    session.commit.assert_not_awaited()
