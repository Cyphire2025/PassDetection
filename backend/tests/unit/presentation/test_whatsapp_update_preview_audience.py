"""Exercise actual update-filter resolution before choosing a preview person."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.whatsapp.template_settings import (
    TEMPLATE_SETTINGS_MEMO,
    TemplateSettingsSnapshot,
)
from app.presentation.api.v1.routes import whatsapp_composer as route
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppPreviewRequest
from tests.whatsapp_filter_export_fixtures import NOW, persist_export_graph


async def test_valid_update_filter_with_no_matching_people_returns_conflict(
    db_session: AsyncSession,
) -> None:
    graph = await persist_export_graph(db_session)
    # There are two active recipients and linked trips, but no sent visa assignment.
    body = WhatsAppPreviewRequest(
        message_type="update",
        update_distribution="sent",
        update_document_type="visa",
        message_content="Synthetic travel update",
    )
    with pytest.raises(HTTPException) as error:
        await route.preview_broadcast_message(graph.broadcast.id, body, graph.actor, db_session)
    assert error.value.status_code == 409
    assert error.value.detail == "No recipients match the selected audience filters."
    assert not db_session.new and not db_session.dirty


@pytest.mark.parametrize("distribution", ["all", "pending"])
async def test_nonempty_update_filters_keep_the_current_authorized_preview(
    db_session: AsyncSession,
    distribution: str,
) -> None:
    graph = await persist_export_graph(db_session)
    db_session.info[TEMPLATE_SETTINGS_MEMO] = TemplateSettingsSnapshot(
        0, None, {"update": "synthetic_update"}
    )
    response = await route.preview_broadcast_message(
        graph.broadcast.id,
        WhatsAppPreviewRequest(
            message_type="update",
            update_distribution=distribution,
            recipient_id=graph.recipients[1].id,
            message_content="Synthetic travel update",
        ),
        graph.actor,
        db_session,
    )
    assert response.recipient_id == graph.recipients[1].id
    assert response.recipient_count == 2
    assert response.audience_recipient_count == 2
    assert set(response.audience_recipient_ids) == {item.id for item in graph.recipients}
    assert response.message_content == "Synthetic travel update"
    assert not db_session.new and not db_session.dirty


@pytest.mark.parametrize(
    ("scope", "expected_status"), [("empty_list", 400), ("missing_person", 404)]
)
async def test_existing_empty_list_and_selected_person_errors_keep_their_status(
    db_session: AsyncSession,
    scope: str,
    expected_status: int,
) -> None:
    graph = await persist_export_graph(db_session)
    if scope == "empty_list":
        for item in graph.recipients:
            item.removed_at = NOW
        await db_session.commit()
    body = WhatsAppPreviewRequest(message_type="update", recipient_id=uuid.uuid4())
    with pytest.raises(HTTPException) as error:
        await route.preview_broadcast_message(graph.broadcast.id, body, graph.actor, db_session)
    assert error.value.status_code == expected_status
