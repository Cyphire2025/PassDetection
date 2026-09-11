"""QR preview and mistaken send requests honor the phone welcome prerequisite."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.infrastructure.database.models import (
    PassengerQRTokenModel,
    PassengerQrWhatsAppDeliveryModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppPhoneWelcomeModel,
)
from app.presentation.api.v1.routes import tour_operations_qr_delivery as routes
from app.presentation.api.v1.schemas.tour_operations_schemas import SendQrBroadcastRequest
from tests.unit.infrastructure.test_private_delivery_policy import (
    PHONE,
    _seed_private_delivery_context,
)

OTHER_PHONE = "+919876543211"


@pytest.fixture
def qr_test_runtime(monkeypatch):
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(
        whatsapp_qr_template_name="qr_fixture", whatsapp_access_token="fixture",
        whatsapp_phone_number_id="fixture",
    ))
    original_status = routes.qr_status
    monkeypatch.setattr(routes, "qr_status", lambda token: original_status(
        token, now=datetime.now(tz=UTC).replace(tzinfo=token.expires_at.tzinfo),
    ) if token else "not_generated")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "welcome_status", [None, "queued", "processing", "submitted", "sent", "failed", "delivery_unknown",
                       "delivered", "read"]
)
async def test_preview_explains_welcome_block_and_only_allows_delivered_numbers(
    db_session, qr_test_runtime, welcome_status
):
    context = await _seed_private_delivery_context(db_session)
    context["token"].expires_at = datetime.now(tz=UTC) + timedelta(days=1)
    state = (await db_session.execute(select(WhatsAppPhoneWelcomeModel))).scalar_one()
    if welcome_status is None:
        await db_session.delete(state)
    else:
        state.status = welcome_status
    await db_session.flush()
    preview = await routes._build_preview(db_session, group=context["group"])
    assert len(preview.recipients) == 1
    row = preview.recipients[0]
    assert row.phone_number == PHONE
    if welcome_status in {"delivered", "read"}:
        assert row.eligible and preview.can_send
        assert preview.summary.ready == 1
    else:
        assert not row.eligible and not preview.can_send
        assert "welcome" in row.reason.lower()
        assert preview.summary.blocked == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("include_ready", [False, True])
async def test_explicit_send_with_unwelcomed_number_rejects_entire_selection(
    db_session, monkeypatch, qr_test_runtime, include_ready
):
    context = await _seed_private_delivery_context(db_session, passenger_count=2)
    first, second = context["passengers"]
    first.client_phone, first.family_head_phone = PHONE, None
    second.client_phone, second.family_head_phone = OTHER_PHONE, None
    context["token"].expires_at = datetime.now(tz=UTC) + timedelta(days=1)
    other_token = PassengerQRTokenModel(
        id=uuid.uuid4(), agency_id=context["agency"].id, passenger_id=second.id,
        token_hash=uuid.uuid4().hex, token_version=1, qr_payload="pdatt:" + "B" * 43,
        is_active=True, expires_at=datetime.now(tz=UTC) + timedelta(days=1),
    )
    db_session.add_all([
        other_token,
        WhatsAppBroadcastRecipientModel(
            agency_id=context["agency"].id, broadcast_group_id=context["broadcast"].id,
            name="Other traveller", phone_number=OTHER_PHONE,
            normalized_phone_number=OTHER_PHONE, imported_fields={},
        ),
    ])
    await db_session.flush()
    preview = await routes._build_preview(db_session, group=context["group"])
    assert preview.summary.ready == 1 and preview.summary.blocked == 1
    monkeypatch.setattr(routes, "_manageable_group", AsyncMock(return_value=context["group"]))
    from app.infrastructure.whatsapp.tasks import process_qr_whatsapp_broadcast

    publish = MagicMock()
    monkeypatch.setattr(process_qr_whatsapp_broadcast, "apply_async", publish)
    selected = [other_token.id, *([context["token"].id] if include_ready else [])]
    with pytest.raises(HTTPException) as rejected:
        await routes.send_qr_whatsapp_broadcast(
            context["group"].id,
            payload=SendQrBroadcastRequest(qr_token_ids=selected, message_content="Your QR"),
            current_user=SimpleNamespace(id=uuid.uuid4(), email="fixture@example.test"),
            _csrf=None, session=db_session,
        )
    assert rejected.value.status_code == 409
    assert "welcome" in rejected.value.detail.lower()
    publish.assert_not_called()
    assert await db_session.scalar(select(func.count()).select_from(PassengerQrWhatsAppDeliveryModel)) == 0
