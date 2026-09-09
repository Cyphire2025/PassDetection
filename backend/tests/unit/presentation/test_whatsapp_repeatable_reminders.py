"""Repeatable reminder intent with real isolated delivery state and worker claims."""

from __future__ import annotations

import sys
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.whatsapp import worker_runtime
from app.presentation.api.v1.routes import whatsapp_scope, whatsapp_send
from app.presentation.api.v1.routes.whatsapp_composer import preview_broadcast_message
from app.presentation.api.v1.routes.whatsapp_delivery_support import (
    _provider_status_state_predicates,
)
from app.presentation.api.v1.routes.whatsapp_roster_support import _recipient_delivery_counts
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppPreviewRequest,
    WhatsAppSendRequest,
)


class SQLiteDeliveryClaim:
    """Translate only the PostgreSQL named-conflict target for isolated SQLite."""

    def __init__(self, model):
        self.statement = sqlite_insert(model)

    def values(self, values):
        self.statement = self.statement.values(values)
        return self

    def on_conflict_do_update(self, *, constraint, set_, where):
        assert constraint == "uq_whatsapp_recipient_message_state"
        return self.statement.on_conflict_do_update(
            index_elements=["recipient_id", "message_type"], set_=set_, where=where
        )


@pytest.fixture
async def broadcast(db_session, monkeypatch, test_settings):
    # SQLite otherwise expands the PostgreSQL-only partial index to all logs.
    await db_session.execute(text("DROP INDEX uq_whatsapp_active_explicit_resend"))
    await db_session.execute(
        text(
            "CREATE UNIQUE INDEX uq_whatsapp_active_explicit_resend "
            "ON whatsapp_message_logs (recipient_id, message_type) "
            "WHERE is_explicit_resend = true "
            "AND status IN ('queued', 'processing', 'delivery_unknown')"
        )
    )
    settings = test_settings.model_copy(
        update={
            "whatsapp_access_token": "isolated-test-token",
            "whatsapp_phone_number_id": "isolated-phone-id",
            "whatsapp_reminder_template_name": "reminder_v1",
        }
    )
    monkeypatch.setattr(whatsapp_send, "get_settings", lambda: settings)
    monkeypatch.setattr(whatsapp_scope, "get_settings", lambda: settings)
    monkeypatch.setattr(whatsapp_send, "pg_insert", SQLiteDeliveryClaim)
    publication = AsyncMock()
    monkeypatch.setattr(whatsapp_send, "publish_whatsapp_task", publication)
    monkeypatch.setitem(
        sys.modules,
        "app.infrastructure.whatsapp.tasks",
        SimpleNamespace(process_whatsapp_broadcast=object()),
    )
    group = WhatsAppBroadcastGroupModel(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        name="Reminder test group",
        recipient_opt_in_confirmed_at=datetime.now(tz=UTC),
    )
    db_session.add(group)
    recipients = []
    statuses = [
        "submitted",
        "sent",
        "delivered",
        "read",
        "failed",
        "delivery_unknown",
        "queued",
        "processing",
        None,
    ]
    for index, state_status in enumerate(statuses):
        recipient = WhatsAppBroadcastRecipientModel(
            id=uuid.uuid4(),
            broadcast_group_id=group.id,
            agency_id=group.agency_id,
            name=f"Recipient {index}",
            phone_number=f"+9198765432{index:02}",
            normalized_phone_number=f"+9198765432{index:02}",
        )
        db_session.add(recipient)
        recipients.append(recipient)
        for message_type, previous_status in (
            ("welcome", "delivered"),
            ("passport_link", "read"),
            ("reminder", state_status),
        ):
            if previous_status is None:
                continue
            db_session.add(
                WhatsAppRecipientMessageStateModel(
                    id=uuid.uuid4(),
                    broadcast_group_id=group.id,
                    agency_id=group.agency_id,
                    recipient_id=recipient.id,
                    message_type=message_type,
                    status=previous_status,
                    batch_id=uuid.uuid4(),
                    submitted_at=datetime.now(tz=UTC),
                    provider_status_at=datetime.now(tz=UTC),
                )
            )
    db_session.add(
        WhatsAppBroadcastRecipientModel(
            id=uuid.uuid4(),
            broadcast_group_id=group.id,
            agency_id=group.agency_id,
            name="Removed recipient",
            phone_number="+919876543299",
            normalized_phone_number="+919876543299",
            removed_at=datetime.now(tz=UTC),
        )
    )
    await db_session.commit()
    return SimpleNamespace(
        group=group,
        recipients=recipients,
        publication=publication,
        user=SimpleNamespace(role=UserRole.SUPER_ADMIN, agency_id=None),
    )


async def load_states(session):
    return list(
        (
            await session.execute(
                select(WhatsAppRecipientMessageStateModel).execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )


async def test_reminder_preview_includes_prior_outcomes_and_excludes_only_active_sends(
    db_session,
    broadcast,
):
    preview = await preview_broadcast_message(
        group_id=broadcast.group.id,
        body=WhatsAppPreviewRequest(message_type="reminder"),
        current_user=broadcast.user,
        session=db_session,
    )

    assert preview.recipient_count == 9  # Removed recipient is excluded.
    assert preview.eligible_recipient_count == 7
    assert preview.already_sent_count == 0
    assert preview.uncertain_recipient_count == 0
    assert preview.in_progress_count == 2
    assert preview.message_content


@pytest.mark.parametrize("message_type", ["welcome", "passport_link"])
async def test_reminder_policy_does_not_make_welcome_or_passport_messages_repeatable(
    db_session,
    broadcast,
    message_type,
):
    counts = await _recipient_delivery_counts(
        db_session,
        recipients=broadcast.recipients,
        message_type=message_type,
    )

    assert counts == (0, 9, 0, 0)


async def test_new_reminders_reach_all_eligible_recipients_with_fresh_reviewed_content(
    db_session,
    broadcast,
):
    batches = []
    for index in range(3):
        content = f"Reviewed reminder number {index + 1}."
        response = await whatsapp_send.send_broadcast_message(
            group_id=broadcast.group.id,
            body=WhatsAppSendRequest(message_type="reminder", message_content=content),
            current_user=broadcast.user,
            session=db_session,
        )
        assert response.queued == 7
        assert response.skipped_already_sent == response.skipped_delivery_unknown == 0
        assert response.skipped_in_progress == 2
        assert response.batch_id not in batches
        batches.append(response.batch_id)

        logs = list(
            (
                await db_session.execute(
                    select(WhatsAppMessageLogModel).where(
                        WhatsAppMessageLogModel.batch_id == response.batch_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(logs) == 7
        assert all(log.template_parameter_values == [content] for log in logs)
        states = await load_states(db_session)
        for state in states:
            if state.batch_id == response.batch_id:
                assert state.provider_status_at is None
                assert state.submitted_at is None
                state.status = "delivered"
                state.provider_status_at = datetime.now(tz=UTC)
                state.submitted_at = datetime.now(tz=UTC)
        for log in logs:
            log.status = "delivered"
        await db_session.commit()

    assert broadcast.publication.await_count == 3
    states = await load_states(db_session)
    assert {state.status for state in states if state.message_type == "welcome"} == {"delivered"}
    assert {state.status for state in states if state.message_type == "passport_link"} == {"read"}


async def test_repeated_worker_execution_does_not_send_same_reminder_batch_twice(
    db_session,
    broadcast,
    monkeypatch,
):
    response = await whatsapp_send.send_broadcast_message(
        group_id=broadcast.group.id,
        body=WhatsAppSendRequest(message_type="reminder", message_content="Reviewed reminder."),
        current_user=broadcast.user,
        session=db_session,
    )

    @asynccontextmanager
    async def session_factory():
        yield db_session

    send = AsyncMock(side_effect=[f"wamid.test-{index}" for index in range(7)])
    monkeypatch.setattr(worker_runtime, "AsyncSessionFactory", session_factory)
    monkeypatch.setattr(worker_runtime, "send_whatsapp_template", send)
    payload = dict(
        batch_id=str(response.batch_id),
        message_type="reminder",
        message_content="Reviewed reminder.",
        passport_link=None,
    )
    await worker_runtime.run_whatsapp_broadcast(**payload)
    await worker_runtime.run_whatsapp_broadcast(**payload)

    assert send.await_count == 7
    states = await load_states(db_session)
    assert {state.status for state in states if state.batch_id == response.batch_id} == {
        "submitted"
    }


async def test_second_send_while_reminder_is_active_does_not_enqueue_duplicates(
    db_session,
    broadcast,
):
    body = WhatsAppSendRequest(message_type="reminder", message_content="Reviewed reminder.")
    first = await whatsapp_send.send_broadcast_message(
        group_id=broadcast.group.id,
        body=body,
        current_user=broadcast.user,
        session=db_session,
    )
    duplicate = await whatsapp_send.send_broadcast_message(
        group_id=broadcast.group.id,
        body=body,
        current_user=broadcast.user,
        session=db_session,
    )

    assert first.queued == 7
    assert duplicate.queued == 0
    assert duplicate.batch_id is None
    assert duplicate.skipped_in_progress == 9
    broadcast.publication.assert_awaited_once()


@pytest.mark.parametrize("provider_status", ["submitted", "sent", "delivered", "read", "failed"])
async def test_old_reminder_receipt_cannot_consume_a_newer_reminder_claim(
    db_session,
    broadcast,
    provider_status,
):
    state = next(
        state for state in await load_states(db_session) if state.message_type == "reminder"
    )
    old_batch_id = state.batch_id
    state.batch_id = uuid.uuid4()
    state.status = "queued"
    await db_session.commit()
    log = SimpleNamespace(
        recipient_id=state.recipient_id, message_type="reminder", batch_id=old_batch_id
    )
    result = await db_session.execute(
        select(WhatsAppRecipientMessageStateModel).where(
            *_provider_status_state_predicates(log, provider_status=provider_status)
        )
    )

    assert result.scalar_one_or_none() is None


async def test_old_worker_acceptance_does_not_override_new_reminder_attempt(
    db_session,
    broadcast,
):
    state = next(
        state for state in await load_states(db_session) if state.message_type == "reminder"
    )
    old_batch_id = state.batch_id
    new_batch_id = uuid.uuid4()
    state.batch_id = new_batch_id
    state.status = "queued"
    state.submitted_at = None
    await db_session.commit()
    await worker_runtime._set_message_state(
        db_session,
        log=SimpleNamespace(recipient_id=state.recipient_id, message_type="reminder"),
        expected_batch_id=old_batch_id,
        state_status="submitted",
        submitted=True,
    )
    await db_session.commit()
    await db_session.refresh(state)

    assert state.batch_id == new_batch_id
    assert state.status == "queued"
    assert state.submitted_at is None


async def test_reminder_send_still_requires_group_opt_in(db_session, broadcast):
    broadcast.group.recipient_opt_in_confirmed_at = None
    await db_session.commit()
    with pytest.raises(HTTPException) as exc_info:
        await whatsapp_send.send_broadcast_message(
            group_id=broadcast.group.id,
            body=WhatsAppSendRequest(message_type="reminder"),
            current_user=broadcast.user,
            session=db_session,
        )

    assert exc_info.value.status_code == 400
    broadcast.publication.assert_not_awaited()


@pytest.mark.parametrize("resend_status", ["queued", "processing", "delivery_unknown", "delivered"])
async def test_active_explicit_reminder_blocks_fresh_send_but_past_attempts_do_not(
    db_session,
    broadcast,
    resend_status,
):
    recipient = broadcast.recipients[0]
    db_session.add(
        WhatsAppMessageLogModel(
            id=uuid.uuid4(),
            batch_id=uuid.uuid4(),
            broadcast_group_id=broadcast.group.id,
            recipient_id=recipient.id,
            agency_id=broadcast.group.agency_id,
            message_type="reminder",
            status=resend_status,
            template_name="reminder_v1",
            is_explicit_resend=True,
            header_parameter_values=[],
            template_parameter_values=["Prior explicit reminder."],
        )
    )
    await db_session.commit()
    preview = await preview_broadcast_message(
        group_id=broadcast.group.id,
        body=WhatsAppPreviewRequest(message_type="reminder", recipient_ids=[recipient.id]),
        current_user=broadcast.user,
        session=db_session,
    )
    response = await whatsapp_send.send_broadcast_message(
        group_id=broadcast.group.id,
        body=WhatsAppSendRequest(
            message_type="reminder",
            recipient_ids=[recipient.id],
            message_content="New reviewed reminder.",
        ),
        current_user=broadcast.user,
        session=db_session,
    )

    active = resend_status in {"queued", "processing"}
    assert preview.recipient_count == 1
    assert preview.eligible_recipient_count == response.queued == (0 if active else 1)
    assert preview.in_progress_count == response.skipped_in_progress == (1 if active else 0)
    assert preview.already_sent_count == response.skipped_already_sent == 0
    assert preview.uncertain_recipient_count == response.skipped_delivery_unknown == 0
    assert broadcast.publication.await_count == (0 if active else 1)
