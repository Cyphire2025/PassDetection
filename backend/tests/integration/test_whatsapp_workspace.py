"""Workspace contracts use isolated relational fixtures and never call WhatsApp."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
)
from app.presentation.api.v1.routes.whatsapp_history import (
    get_broadcast_message,
    list_broadcast_messages,
    list_message_recipients,
)
from app.presentation.api.v1.routes.whatsapp_history_resend import (
    historical_resend_batch,
    replay_historical_resend,
)
from app.presentation.api.v1.routes.whatsapp_send_intents import canonical_send_body
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppResendRequest,
    WhatsAppSendRequest,
)


@pytest.fixture
async def workspace(db_session):
    # SQLite does not implement the production PostgreSQL partial-index predicate.
    await db_session.execute(text("DROP INDEX uq_whatsapp_active_explicit_resend"))
    agency = AgencyModel(id=uuid.uuid4(), name="Workspace fixture", email="workspace@example.test")
    db_session.add(agency)
    await db_session.flush()
    group = WhatsAppBroadcastGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Dubai trip")
    db_session.add(group)
    await db_session.flush()
    recipient = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(),
        broadcast_group_id=group.id,
        agency_id=agency.id,
        name="Fixture traveller",
        phone_number="+919800000001",
        normalized_phone_number="919800000001",
    )
    db_session.add(recipient)
    await db_session.flush()
    actor = User(
        id=uuid.uuid4(),
        email="staff@example.test",
        hashed_password="fixture",
        full_name="Staff",
        role=UserRole.AGENCY_ADMIN,
        agency_id=agency.id,
    )
    return db_session, group, recipient, actor


def saved_log(group, recipient, batch, *, status="read", content="Trip update", index=0, **fields):
    return WhatsAppMessageLogModel(
        id=uuid.uuid4(),
        batch_id=batch,
        broadcast_group_id=group.id,
        agency_id=group.agency_id,
        recipient_id=recipient.id,
        message_type="update",
        normalized_phone_number=recipient.normalized_phone_number,
        status=status,
        status_updated_at=datetime.now(UTC),
        rendered_message=content,
        template_name="trip_update_approved",
        template_parameter_values=[content],
        header_parameter_values=[],
        created_at=datetime.now(UTC) - timedelta(minutes=index),
        **fields,
    )


@pytest.mark.asyncio
async def test_each_send_is_distinct_and_editing_a_number_does_not_rewrite_history(workspace):
    session, group, recipient, actor = workspace
    first, second = uuid.uuid4(), uuid.uuid4()
    full_message = "First update " * 35
    old = saved_log(group, recipient, first, content=full_message, index=2)
    new = saved_log(group, recipient, second, status="failed", content="Second update")
    session.add_all([old, new])
    await session.flush()
    recipient.normalized_phone_number = "919800000099"
    await session.flush()
    page = await list_broadcast_messages(
        group.id, q="", message_type=None, offset=0, limit=25, current_user=actor, session=session
    )
    assert page.total == 2
    assert [entry.id for entry in page.items] == [second, first]
    assert page.items[0].counts.failed == 1
    message = await get_broadcast_message(group.id, first, current_user=actor, session=session)
    assert message.rendered_message == full_message
    assert len(message.message_preview) == 240
    report = await list_message_recipients(
        group.id,
        first,
        status_filter="all",
        q="",
        offset=0,
        limit=50,
        current_user=actor,
        session=session,
    )
    assert report.items[0].phone_number == "919800000001"
    assert report.items[0].current_phone_number == "919800000099"
    assert report.items[0].rendered_message == full_message
    assert report.items[0].can_resend


@pytest.mark.asyncio
async def test_history_search_keeps_whole_batch_counts_and_escapes_wildcards(workspace):
    session, group, recipient, actor = workspace
    other = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(),
        broadcast_group_id=group.id,
        agency_id=group.agency_id,
        name="Second traveller",
        phone_number="+919800000002",
        normalized_phone_number="919800000002",
    )
    session.add(other)
    await session.flush()
    batch = uuid.uuid4()
    session.add_all(
        [
            saved_log(group, recipient, batch, content="Personal fare 50%"),
            saved_log(group, other, batch, status="failed", content="Other personalised content"),
        ]
    )
    await session.flush()
    page = await list_broadcast_messages(
        group.id,
        q="50%",
        message_type=None,
        offset=0,
        limit=25,
        current_user=actor,
        session=session,
    )
    assert page.total == 1 and page.items[0].counts.all == 2 and page.items[0].counts.failed == 1
    empty = await list_broadcast_messages(
        group.id, q="_", message_type=None, offset=0, limit=25, current_user=actor, session=session
    )
    assert empty.total == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("stored_status", ["delivery_unknown", "processing", "failed"])
async def test_failed_filter_contains_unresolved_outcomes_without_allowing_unsafe_resend(
    workspace, stored_status
):
    session, group, recipient, actor = workspace
    batch = uuid.uuid4()
    log = saved_log(group, recipient, batch, status=stored_status)
    log.status_updated_at = datetime.now(UTC) - timedelta(hours=2)
    session.add(log)
    await session.flush()
    report = await list_message_recipients(
        group.id,
        batch,
        status_filter="failed",
        q="",
        offset=0,
        limit=50,
        current_user=actor,
        session=session,
    )
    assert report.total == 1 and report.counts.failed == 1
    assert report.items[0].can_resend is (stored_status == "failed")
    assert log.status == stored_status


@pytest.mark.asyncio
async def test_history_scope_rejects_another_agency_and_another_broadcast(workspace):
    session, group, recipient, actor = workspace
    actor.agency_id = uuid.uuid4()
    with pytest.raises(HTTPException) as denied:
        await get_broadcast_message(group.id, uuid.uuid4(), current_user=actor, session=session)
    assert denied.value.status_code == 404
    actor.agency_id = group.agency_id
    with pytest.raises(HTTPException) as missing:
        await get_broadcast_message(group.id, uuid.uuid4(), current_user=actor, session=session)
    assert missing.value.status_code == 404


@pytest.mark.asyncio
async def test_historical_resend_replays_the_same_durable_log(workspace):
    session, group, recipient, actor = workspace
    source = uuid.uuid4()
    body = WhatsAppResendRequest(
        message_type="reminder", source_message_log_id=source, request_id=uuid.uuid4()
    )
    batch = historical_resend_batch(
        body, user_id=actor.id, group_id=group.id, recipient_id=recipient.id
    )
    assert batch == historical_resend_batch(
        body, user_id=actor.id, group_id=group.id, recipient_id=recipient.id
    )
    session.add(saved_log(group, recipient, batch, status="queued"))
    await session.flush()
    response = await replay_historical_resend(
        session, batch_id=batch, group_id=group.id, recipient_id=recipient.id
    )
    assert response.batch_id == batch and response.queued == 1
    assert (
        await replay_historical_resend(
            session, batch_id=batch, group_id=uuid.uuid4(), recipient_id=recipient.id
        )
        is None
    )
    with pytest.raises(HTTPException):
        historical_resend_batch(
            body.model_copy(update={"message_content": "changed"}),
            user_id=actor.id,
            group_id=group.id,
            recipient_id=recipient.id,
        )


def test_new_form_defaults_do_not_change_retained_send_receipt_hashes():
    body = WhatsAppSendRequest(message_type="passport_link")
    canonical = canonical_send_body(body)
    assert not (
        {
            "update_submission",
            "update_distribution",
            "update_document_type",
            "include_previous_recipients",
        }
        & canonical.keys()
    )
    assert (
        canonical_send_body(body.model_copy(update={"include_previous_recipients": True}))[
            "include_previous_recipients"
        ]
        is True
    )
    with pytest.raises(ValidationError):
        WhatsAppSendRequest(message_type="welcome", include_previous_recipients=True)


@pytest.mark.asyncio
async def test_new_passport_link_can_include_previous_recipients_but_blocks_unconfirmed_attempts(
    workspace,
):
    from app.presentation.api.v1.routes.whatsapp_roster_support import _recipient_delivery_counts

    session, group, recipient, actor = workspace
    log = saved_log(group, recipient, uuid.uuid4())
    log.message_type = "passport_link"
    session.add(log)
    await session.flush()
    assert await _recipient_delivery_counts(
        session, recipients=[recipient], message_type="passport_link"
    ) == (0, 1, 0, 0)
    assert await _recipient_delivery_counts(
        session,
        recipients=[recipient],
        message_type="passport_link",
        include_previous_recipients=True,
    ) == (1, 0, 0, 0)
    log.status = "delivery_unknown"
    await session.flush()
    assert await _recipient_delivery_counts(
        session,
        recipients=[recipient],
        message_type="passport_link",
        include_previous_recipients=True,
    ) == (0, 0, 0, 1)
