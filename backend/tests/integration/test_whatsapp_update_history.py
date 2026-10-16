"""Historical updates retain their exact content and durable retry identity."""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.infrastructure.database.models import WhatsAppMessageLogModel
from app.presentation.api.v1.routes.whatsapp_update_resend import (
    UpdateResendRequest,
    resend_saved_update,
)
from tests.integration.test_group_updates import group_update as group_update
from tests.integration.test_group_updates import preview, queue, request_for


async def test_update_history_retry_preserves_content_and_replays_after_lost_response(group_update):
    fixture = group_update
    data = await preview(fixture, submission_status="not_submitted")
    response = (await queue(fixture, request_for(data))).json()
    source = await fixture.session.scalar(
        select(WhatsAppMessageLogModel).where(
            WhatsAppMessageLogModel.batch_id == uuid.UUID(response["batches"][0]["batch_id"])
        )
    )
    source.status = "failed"
    await fixture.session.commit()
    request = UpdateResendRequest(source_message_log_id=source.id, request_id=uuid.uuid4())
    first = await resend_saved_update(
        fixture.broadcast.id,
        source.recipient_id,
        request,
        current_user=fixture.actor,
        session=fixture.session,
    )
    second = await resend_saved_update(
        fixture.broadcast.id,
        source.recipient_id,
        request,
        current_user=fixture.actor,
        session=fixture.session,
    )
    assert first.batch_id == second.batch_id
    rows = list(
        (
            await fixture.session.scalars(
                select(WhatsAppMessageLogModel).where(
                    WhatsAppMessageLogModel.batch_id == first.batch_id
                )
            )
        ).all()
    )
    assert len(rows) == 1
    assert rows[0].rendered_message == source.rendered_message
    assert rows[0].template_parameter_values == source.template_parameter_values
    assert rows[0].template_name == source.template_name
    assert rows[0].document_update_context["source_message_log_id"] == str(source.id)
    assert fixture.provider.await_count == 0


async def test_update_history_rejects_unknown_outcomes_and_foreign_source(group_update):
    fixture = group_update
    data = await preview(fixture, submission_status="not_submitted")
    response = (await queue(fixture, request_for(data))).json()
    source = await fixture.session.scalar(
        select(WhatsAppMessageLogModel).where(
            WhatsAppMessageLogModel.batch_id == uuid.UUID(response["batches"][0]["batch_id"])
        )
    )
    source.status = "delivery_unknown"
    await fixture.session.commit()
    request = UpdateResendRequest(source_message_log_id=source.id, request_id=uuid.uuid4())
    with pytest.raises(HTTPException) as error:
        await resend_saved_update(
            fixture.broadcast.id,
            source.recipient_id,
            request,
            current_user=fixture.actor,
            session=fixture.session,
        )
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        await resend_saved_update(
            fixture.broadcast.id,
            fixture.recipients[0].id,
            request,
            current_user=fixture.actor,
            session=fixture.session,
        )
    assert error.value.status_code == 404
    assert fixture.provider.await_count == 0
