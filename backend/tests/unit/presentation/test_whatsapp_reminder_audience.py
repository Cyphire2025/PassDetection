from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.domain.entities.entities import UserRole
from app.presentation.api.v1.routes import whatsapp_reminder_audience


def _session_with_linked_ids(*linked_ids: uuid.UUID) -> AsyncMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(linked_ids)
    session = AsyncMock()
    session.execute.return_value = result
    return session


@pytest.mark.asyncio
async def test_not_submitted_audience_uses_exact_match_statuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload_group_id = uuid.uuid4()
    broadcast = SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4())
    recipients = [SimpleNamespace(id=uuid.uuid4()) for _ in range(3)]
    session = _session_with_linked_ids(upload_group_id)
    loader = AsyncMock(
        return_value=(
            {},
            [],
            [],
            [
                SimpleNamespace(
                    status="not_submitted",
                    recipient_ids=(recipients[0].id,),
                ),
                SimpleNamespace(
                    status="submitted",
                    recipient_ids=(recipients[1].id,),
                ),
                SimpleNamespace(
                    status="needs_review",
                    recipient_ids=(recipients[2].id,),
                ),
            ],
        )
    )
    monkeypatch.setattr(
        whatsapp_reminder_audience,
        "load_unresolved_passport_whatsapp_match_context",
        loader,
    )

    resolved = await whatsapp_reminder_audience.resolve_reminder_audience(
        session,
        broadcast_group=broadcast,
        recipients=recipients,
        audience="not_submitted",
        audience_client_group_id=None,
        current_user=SimpleNamespace(role=UserRole.AGENCY_ADMIN),
    )

    assert [recipient.id for recipient in resolved.recipients] == [recipients[0].id]
    assert resolved.client_group_id == upload_group_id
    assert resolved.excluded_submitted_count == 1
    assert resolved.excluded_needs_review_count == 1
    loader.assert_awaited_once_with(
        session,
        group_id=upload_group_id,
        agency_id=broadcast.agency_id,
    )


@pytest.mark.asyncio
async def test_not_submitted_audience_requires_group_choice_when_multiple_linked() -> None:
    broadcast = SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4())
    session = _session_with_linked_ids(uuid.uuid4(), uuid.uuid4())

    with pytest.raises(HTTPException) as exc_info:
        await whatsapp_reminder_audience.resolve_reminder_audience(
            session,
            broadcast_group=broadcast,
            recipients=[SimpleNamespace(id=uuid.uuid4())],
            audience="not_submitted",
            audience_client_group_id=None,
            current_user=SimpleNamespace(role=UserRole.AGENCY_ADMIN),
        )

    assert exc_info.value.status_code == 409
    assert "Choose which linked upload group" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_not_submitted_audience_rejects_empty_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload_group_id = uuid.uuid4()
    broadcast = SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4())
    recipient = SimpleNamespace(id=uuid.uuid4())
    session = _session_with_linked_ids(upload_group_id)
    monkeypatch.setattr(
        whatsapp_reminder_audience,
        "load_unresolved_passport_whatsapp_match_context",
        AsyncMock(
            return_value=(
                {},
                [],
                [],
                [SimpleNamespace(status="submitted", recipient_ids=(recipient.id,))],
            )
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await whatsapp_reminder_audience.resolve_reminder_audience(
            session,
            broadcast_group=broadcast,
            recipients=[recipient],
            audience="not_submitted",
            audience_client_group_id=upload_group_id,
            current_user=SimpleNamespace(role=UserRole.AGENCY_ADMIN),
        )

    assert exc_info.value.status_code == 409
    assert "Everyone" in str(exc_info.value.detail)
