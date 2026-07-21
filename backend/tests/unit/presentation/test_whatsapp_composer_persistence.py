from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, Request

from app.domain.entities.entities import UserRole
from app.presentation.api.v1.routes.whatsapp import (
    WhatsAppPreviewRequest,
    WhatsAppResendRequest,
    WhatsAppSendRequest,
    _composer_snapshot_from_log,
    _latest_composer_snapshot,
    _merge_composer_snapshot,
    _resolve_send_header_image,
    _resolve_send_passport_intro,
    preview_broadcast_message,
    resend_recipient_message,
    send_broadcast_message,
)


def _passport_log(*, explicit: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        broadcast_group_id=uuid.uuid4(),
        recipient_id=uuid.uuid4(),
        message_type="passport_link",
        status="delivered",
        status_updated_at=datetime.now(tz=UTC),
        created_at=datetime.now(tz=UTC),
        is_explicit_resend=explicit,
        rendered_message=None,
        header_parameter_values=["passport-media-123"],
        template_parameter_values=[
            "Custom BODY one introduction.",
            "https://tech.example/upload/token",
            "Custom BODY three instructions.",
            "Travel desk: +919876543210",
        ],
    )


def test_passport_snapshot_restores_every_editable_composer_field() -> None:
    snapshot = _composer_snapshot_from_log(_passport_log())

    assert snapshot.passport_intro == "Custom BODY one introduction."
    assert snapshot.passport_link == "https://tech.example/upload/token"
    assert snapshot.message_content == "Custom BODY three instructions."
    assert snapshot.header_image_id == "passport-media-123"

    merged = _merge_composer_snapshot(
        WhatsAppSendRequest(
            message_type="passport_link",
            message_content="Edited instructions only.",
        ),
        snapshot,
    )
    assert merged.passport_intro == snapshot.passport_intro
    assert merged.passport_link == snapshot.passport_link
    assert merged.message_content == "Edited instructions only."
    assert merged.header_image_id == snapshot.header_image_id


def test_new_sends_require_nonempty_passport_intro_and_image_header() -> None:
    with pytest.raises(HTTPException) as intro_error:
        _resolve_send_passport_intro("   ", group_name="Vietnam")
    assert intro_error.value.status_code == 400
    assert "BODY {{1}}" in str(intro_error.value.detail)

    with pytest.raises(HTTPException) as image_error:
        _resolve_send_header_image("passport_link", None)
    assert image_error.value.status_code == 400
    assert image_error.value.detail == (
        "Upload the required Passport Link image before sending"
    )
    assert (
        _resolve_send_header_image("passport_link", "  media-passport-v3  ")
        == "media-passport-v3"
    )


@pytest.mark.asyncio
async def test_group_snapshot_is_successful_non_resend_and_authored_ordered() -> None:
    result = MagicMock()
    result.scalars.return_value.all.return_value = [_passport_log()]
    session = AsyncMock()
    session.execute.return_value = result

    snapshot = await _latest_composer_snapshot(
        session,
        group_id=uuid.uuid4(),
        message_type="passport_link",
        accepted_only=True,
    )

    assert snapshot is not None
    statement = session.execute.await_args.args[0]
    where_sql = str(statement.whereclause)
    order_sql = str(statement).split("ORDER BY", 1)[1]
    assert "is_explicit_resend IS false" in where_sql
    assert "status IN" in where_sql
    assert order_sql.index("created_at DESC") < order_sql.index("status_updated_at DESC")


@pytest.mark.asyncio
async def test_group_preview_reuses_latest_group_snapshot_not_preview_recipient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_id = uuid.uuid4()
    preview_recipient_id = uuid.uuid4()
    group = SimpleNamespace(id=group_id, name="Vietnam")
    recipient = SimpleNamespace(id=preview_recipient_id, name="Aarav")
    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = group
    session = AsyncMock()
    session.execute.return_value = group_result
    latest_snapshot = AsyncMock(return_value=_composer_snapshot_from_log(_passport_log()))
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp._group_recipients",
        AsyncMock(return_value=[recipient]),
    )
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp._latest_composer_snapshot",
        latest_snapshot,
    )
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp._support_contacts_for_group",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp._recipient_delivery_counts",
        AsyncMock(return_value=(0, 1, 0, 0)),
    )
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp.get_settings",
        lambda: SimpleNamespace(
            whatsapp_welcome_template_name="welcome_v3",
            whatsapp_passport_link_template_name="passport_v3",
        ),
    )

    response = await preview_broadcast_message(
        group_id=group_id,
        body=WhatsAppPreviewRequest(
            message_type="passport_link",
            recipient_id=preview_recipient_id,
        ),
        current_user=SimpleNamespace(
            role=UserRole.SUPER_ADMIN,
            agency_id=None,
        ),
        session=session,
    )

    call = latest_snapshot.await_args
    assert call.kwargs["accepted_only"] is True
    assert "recipient_id" not in call.kwargs
    assert response.content_source == "latest_group"
    assert response.passport_intro == "Custom BODY one introduction."
    assert response.passport_link == "https://tech.example/upload/token"
    assert response.message_content == "Custom BODY three instructions."
    assert response.header_image_id == "passport-media-123"
    assert response.header_parameter_values == ["passport-media-123"]


@pytest.mark.asyncio
async def test_resend_preview_is_scoped_to_one_recipient_and_latest_recipient_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_id = uuid.uuid4()
    recipient_id = uuid.uuid4()
    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = SimpleNamespace(
        id=group_id,
        name="Vietnam",
    )
    state_result = MagicMock()
    state_result.scalar_one_or_none.return_value = SimpleNamespace(
        status="submitted",
    )
    session = AsyncMock()
    session.execute.side_effect = [group_result, state_result]
    recipient = SimpleNamespace(id=recipient_id, name="Aarav")
    latest_snapshot = AsyncMock(return_value=_composer_snapshot_from_log(_passport_log(explicit=True)))
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp._group_recipients",
        AsyncMock(return_value=[recipient]),
    )
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp._latest_composer_snapshot",
        latest_snapshot,
    )
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp._support_contacts_for_group",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp.get_settings",
        lambda: SimpleNamespace(
            whatsapp_welcome_template_name="welcome_v3",
            whatsapp_passport_link_template_name="passport_v3",
        ),
    )

    response = await preview_broadcast_message(
        group_id=group_id,
        body=WhatsAppPreviewRequest(
            message_type="passport_link",
            resend_recipient_id=recipient_id,
        ),
        current_user=SimpleNamespace(
            role=UserRole.SUPER_ADMIN,
            agency_id=None,
        ),
        session=session,
    )

    call = latest_snapshot.await_args
    assert call.kwargs["recipient_id"] == recipient_id
    assert call.kwargs["accepted_only"] is True
    assert call.kwargs["include_explicit_resends"] is True
    assert response.content_source == "latest_recipient"
    assert response.recipient_count == 1
    assert response.eligible_recipient_count == 1


@pytest.mark.asyncio
async def test_failed_message_preview_reuses_saved_content_for_one_person_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_id = uuid.uuid4()
    recipient_id = uuid.uuid4()
    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = SimpleNamespace(
        id=group_id,
        name="Vietnam",
    )
    state_result = MagicMock()
    state_result.scalar_one_or_none.return_value = SimpleNamespace(status="failed")
    session = AsyncMock()
    session.execute.side_effect = [group_result, state_result]
    latest_snapshot = AsyncMock(
        return_value=_composer_snapshot_from_log(_passport_log())
    )
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp._group_recipients",
        AsyncMock(
            return_value=[SimpleNamespace(id=recipient_id, name="Aarav")]
        ),
    )
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp._latest_composer_snapshot",
        latest_snapshot,
    )
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp._support_contacts_for_group",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp.get_settings",
        lambda: SimpleNamespace(
            whatsapp_welcome_template_name="welcome_v3",
            whatsapp_passport_link_template_name="passport_v3",
        ),
    )

    response = await preview_broadcast_message(
        group_id=group_id,
        body=WhatsAppPreviewRequest(
            message_type="passport_link",
            resend_recipient_id=recipient_id,
        ),
        current_user=SimpleNamespace(role=UserRole.SUPER_ADMIN, agency_id=None),
        session=session,
    )

    call = latest_snapshot.await_args
    assert call.kwargs["accepted_only"] is False
    assert call.kwargs["include_failed"] is True
    assert response.eligible_recipient_count == 1
    assert response.already_sent_count == 0


@pytest.mark.asyncio
async def test_fresh_passport_send_rejects_missing_image_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_id = uuid.uuid4()
    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = SimpleNamespace(
        id=group_id,
        name="Vietnam",
        recipient_opt_in_confirmed_at=datetime.now(tz=UTC),
    )
    session = AsyncMock()
    session.execute.return_value = group_result
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp._group_recipients",
        AsyncMock(return_value=[SimpleNamespace(id=uuid.uuid4())]),
    )
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp._support_contacts_for_group",
        AsyncMock(
            return_value=[
                SimpleNamespace(
                    name="Travel desk",
                    phone_number="+919876543210",
                )
            ]
        ),
    )
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp._latest_composer_snapshot",
        AsyncMock(return_value=None),
    )

    with pytest.raises(HTTPException) as exc_info:
        await send_broadcast_message(
            group_id=group_id,
            body=WhatsAppSendRequest(
                message_type="passport_link",
                passport_intro="Please submit your travel documents.",
                passport_link="https://tech.example/upload/token",
                message_content="Complete all required details.",
            ),
            current_user=SimpleNamespace(
                role=UserRole.SUPER_ADMIN,
                agency_id=None,
            ),
            session=session,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == (
        "Upload the required Passport Link image before sending"
    )


@pytest.mark.asyncio
async def test_missing_passport_link_stays_null_while_preview_renders_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_id = uuid.uuid4()
    recipient_id = uuid.uuid4()
    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = SimpleNamespace(
        id=group_id,
        name="Vietnam",
    )
    session = AsyncMock()
    session.execute.return_value = group_result
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp._group_recipients",
        AsyncMock(return_value=[SimpleNamespace(id=recipient_id, name="Aarav")]),
    )
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp._latest_composer_snapshot",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp._support_contacts_for_group",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp._recipient_delivery_counts",
        AsyncMock(return_value=(1, 0, 0, 0)),
    )
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp.get_settings",
        lambda: SimpleNamespace(
            whatsapp_welcome_template_name="welcome_v3",
            whatsapp_passport_link_template_name="passport_v3",
        ),
    )

    response = await preview_broadcast_message(
        group_id=group_id,
        body=WhatsAppPreviewRequest(message_type="passport_link"),
        current_user=SimpleNamespace(
            role=UserRole.SUPER_ADMIN,
            agency_id=None,
        ),
        session=session,
    )

    assert response.passport_link is None
    assert "[passport upload link]" in response.rendered_message


@pytest.mark.asyncio
async def test_old_passport_snapshot_prefills_current_image_template_resend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_id = uuid.uuid4()
    recipient_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    group = SimpleNamespace(
        id=group_id,
        agency_id=agency_id,
        name="Vietnam",
        recipient_opt_in_confirmed_at=datetime.now(tz=UTC),
    )
    recipient = SimpleNamespace(
        id=recipient_id,
        agency_id=agency_id,
        name="Aarav",
        normalized_phone_number="+919876543210",
        removed_at=None,
    )
    source_log = _passport_log()
    source_log.template_name = "passport_link_v2"
    source_log.header_parameter_values = []

    def scalar_result(value: object) -> MagicMock:
        result = MagicMock()
        result.scalar_one_or_none.return_value = value
        return result

    support_result = MagicMock()
    support_result.scalars.return_value.all.return_value = [
        SimpleNamespace(name="Travel desk", phone_number="+919876543211")
    ]
    session = AsyncMock()
    session.add = MagicMock()
    session.execute.side_effect = [
        scalar_result(group),
        scalar_result(recipient),
        scalar_result(SimpleNamespace(status="delivered")),
        MagicMock(),
        MagicMock(),
        scalar_result(None),
        scalar_result(source_log),
        support_result,
    ]
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp.AuditLogRepository.record",
        AsyncMock(),
    )
    queue_message = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "app.infrastructure.whatsapp.tasks",
        SimpleNamespace(
            process_whatsapp_broadcast=SimpleNamespace(apply_async=queue_message),
        ),
    )
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp.get_settings",
        lambda: SimpleNamespace(
            whatsapp_access_token="token",
            whatsapp_phone_number_id="phone-id",
            whatsapp_welcome_template_name="welcome_v3",
            whatsapp_passport_link_template_name="passport_link_v3",
        ),
    )

    response = await resend_recipient_message(
        group_id=group_id,
        recipient_id=recipient_id,
        body=WhatsAppResendRequest(
            message_type="passport_link",
            header_image_id="passport-media-v3",
        ),
        request=Request({"type": "http", "client": ("127.0.0.1", 1234)}),
        current_user=SimpleNamespace(
            id=uuid.uuid4(),
            role=UserRole.SUPER_ADMIN,
            agency_id=None,
            email="admin@example.com",
        ),
        session=session,
    )

    assert response.queued == 1
    queued_log = session.add.call_args.args[0]
    assert queued_log.template_name == "passport_link_v3"
    assert queued_log.header_parameter_values == ["passport-media-v3"]
    assert queued_log.template_parameter_values[:3] == [
        "Custom BODY one introduction.",
        "https://tech.example/upload/token",
        "Custom BODY three instructions.",
    ]
    queue_kwargs = queue_message.call_args.kwargs["kwargs"]
    assert queue_kwargs["passport_intro"] == "Custom BODY one introduction."
    assert queue_kwargs["header_image_id"] == "passport-media-v3"
