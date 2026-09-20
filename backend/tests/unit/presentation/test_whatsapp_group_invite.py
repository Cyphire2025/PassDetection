"""Official group invitations preserve their two-variable text template end to end."""

from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, Request

from app.application.use_cases.whatsapp.message_templates import (
    GROUP_INVITE_DEFAULT_MESSAGE_CONTENT,
    default_message_content,
    render_message,
    template_header_parameters,
    template_parameters,
    validate_group_invite_link,
    validate_template_parameters,
)
from app.domain.entities.entities import UserRole
from app.presentation.api.v1.routes import whatsapp_composer as preview_route
from app.presentation.api.v1.routes import whatsapp_resend as resend_route
from app.presentation.api.v1.routes import whatsapp_scope, whatsapp_send
from app.presentation.api.v1.routes.whatsapp_bulk_resend_composer import (
    BulkResendEdits,
    resolve_saved_resend_snapshot,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_support import selection_fingerprint
from app.presentation.api.v1.routes.whatsapp_composer_support import (
    _composer_snapshot_from_log,
    _merge_composer_snapshot,
    _validate_group_invite_link,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBulkResendRequest,
    WhatsAppPreviewRequest,
    WhatsAppResendRequest,
    WhatsAppSendRequest,
)
from tests.unit.presentation import test_whatsapp_bulk_resend as bulk_test_support

bulk_fixture = bulk_test_support.fixture

LINK = "https://chat.whatsapp.com/SyntheticInviteToken123?mode=ac_t"
EDITED_LINK = "https://chat.whatsapp.com/EditedInviteToken456?mode=ac_t"
CONTENT = "Please join the trip group for important updates."


def rendered(content=CONTENT, link=LINK):
    return (
        "Dear Delegates\n\nGreetings from Global Connect Travels\n\n"
        f"{content}\n\n{link}\n\nRegards\nTeam Global Connect Travels"
    )


def saved_log(**overrides):
    values = dict(
        id=uuid.uuid4(), message_type="group_invite", template_name="whatsapp_group_invite_v1",
        header_parameter_values=[], template_parameter_values=[CONTENT, LINK],
        rendered_message=rendered(), status="delivered", template_language="en",
    )
    return SimpleNamespace(**(values | overrides))


def db_result(value=None, rows=None):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalars.return_value.all.return_value = rows or []
    return result


def test_invite_matches_exact_approved_copy_and_parameter_order():
    assert default_message_content("group_invite", group_name="Ignored") == GROUP_INVITE_DEFAULT_MESSAGE_CONTENT
    assert render_message(
        message_type="group_invite", group_name="Ignored", support_contacts="Ignored",
        message_content=CONTENT, group_invite_link=LINK,
    ) == rendered()
    params = template_parameters(
        message_type="group_invite", group_name="Ignored", support_contacts="Ignored",
        message_content=CONTENT, group_invite_link=LINK,
    )
    assert params == [CONTENT, LINK]
    assert template_header_parameters(message_type="group_invite", header_image_id="stale-media") == []
    validate_template_parameters(message_type="group_invite", header_parameters=[], body_parameters=params)


@pytest.mark.parametrize("link", [
    "", "https://chat.whatsapp.com/", "http://chat.whatsapp.com/Abc123", "https://example.com/Abc123",
    "https://chat.whatsapp.com.evil.example/Abc123", "https://chat.whatsapp.com@evil.example/Abc123",
    "https://user:password@chat.whatsapp.com/Abc123", "https://chat.whatsapp.com:443/Abc123",
    "https://chat.whatsapp.com/Abc123/another", "https://chat.whatsapp.com/Abc123#section",
    "https://chat.whatsapp.com/Abc 123", "https://chat.whatsapp.com/Abc123?mode=bad\nvalue",
])
def test_invite_rejects_missing_or_nonofficial_links(link):
    with pytest.raises(ValueError):
        validate_group_invite_link(link)
    with pytest.raises(HTTPException):
        _validate_group_invite_link(link)


@pytest.mark.parametrize("link", [LINK, "https://chat.whatsapp.com/Abc123", "https://chat.whatsapp.com/Abc123/?mode=ac_t"])
def test_invite_preserves_valid_share_query(link):
    assert validate_group_invite_link(f" {link} ") == link


@pytest.mark.parametrize("headers,body", [(["image"], [CONTENT, LINK]), ([], [CONTENT]), ([], [CONTENT, LINK, "extra"]), ([], ["", LINK]), ([], [CONTENT, "https://example.com/unsafe"])])
def test_invalid_provider_shape_is_rejected(headers, body):
    with pytest.raises(ValueError):
        validate_template_parameters(message_type="group_invite", header_parameters=headers, body_parameters=body)


def test_snapshot_reopens_and_edits_each_invite_without_passport_fields():
    original = saved_log()
    snapshot = _composer_snapshot_from_log(original)
    assert snapshot.group_invite_link == LINK
    assert snapshot.message_content == CONTENT
    assert snapshot.passport_link is None
    assert snapshot.header_image_id is None
    merged = _merge_composer_snapshot(WhatsAppSendRequest(message_type="group_invite"), snapshot)
    assert merged.group_invite_link == LINK
    edited = _merge_composer_snapshot(
        WhatsAppSendRequest(message_type="group_invite", group_invite_link=EDITED_LINK, message_content="New invitation"), snapshot,
    )
    assert edited.group_invite_link == EDITED_LINK
    assert edited.message_content == "New invitation"
    bulk = resolve_saved_resend_snapshot(original, BulkResendEdits(message_content="Updated invitation", group_invite_link=EDITED_LINK))
    assert bulk.parameters == ["Updated invitation", EDITED_LINK]
    assert bulk.header_parameters == []
    assert bulk.rendered_message == rendered("Updated invitation", EDITED_LINK)
    assert original.template_parameter_values == [CONTENT, LINK]


def test_bulk_idempotency_fingerprint_changes_with_invite_link_edit():
    body = WhatsAppBulkResendRequest(message_type="group_invite", recipient_ids=[uuid.uuid4()], request_id=uuid.uuid4())
    edited = body.model_copy(update={"group_invite_link": EDITED_LINK})
    assert selection_fingerprint(body) != selection_fingerprint(edited)


@pytest.fixture
def rig(monkeypatch):
    group = SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4(), name="Trip", archived_at=None, recipient_opt_in_confirmed_at=datetime.now(UTC))
    recipient = SimpleNamespace(id=uuid.uuid4(), agency_id=group.agency_id, broadcast_group_id=group.id, name="Traveller", normalized_phone_number="+919876543210", removed_at=None)
    settings = SimpleNamespace(whatsapp_access_token="synthetic-token", whatsapp_phone_number_id="synthetic-provider", whatsapp_group_invite_template_name="whatsapp_group_invite_v1", whatsapp_group_invite_template_language="en", whatsapp_template_language="en_US")
    user = SimpleNamespace(id=uuid.uuid4(), agency_id=group.agency_id, role=UserRole.AGENCY_ADMIN, email="staff@example.com")
    session = AsyncMock()
    session.add = MagicMock()
    publish = AsyncMock()
    prerequisite = AsyncMock()
    for module in (whatsapp_send, preview_route, resend_route):
        monkeypatch.setattr(module, "_support_contacts_for_group", AsyncMock(return_value=[]))
    for module in (whatsapp_send, preview_route):
        monkeypatch.setattr(module, "_group_recipients", AsyncMock(return_value=[recipient]))
        monkeypatch.setattr(module, "_latest_composer_snapshot", AsyncMock(return_value=None))
    for module in (whatsapp_send, resend_route):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
        monkeypatch.setattr(module, "enforce_broadcast_welcome_prerequisite", prerequisite)
        monkeypatch.setattr(module, "publish_whatsapp_task", publish)
    monkeypatch.setattr(whatsapp_scope, "get_settings", lambda: settings)
    monkeypatch.setattr(preview_route, "_recipient_delivery_counts", AsyncMock(return_value=(1, 0, 0, 0)))
    monkeypatch.setattr(preview_route, "welcome_preview_values", AsyncMock(return_value={}))
    monkeypatch.setattr(resend_route, "active_replacement_resolution_id_for_recipient", AsyncMock(return_value=None))
    monkeypatch.setattr(resend_route.AuditLogRepository, "record", AsyncMock())
    monkeypatch.setitem(sys.modules, "app.infrastructure.whatsapp.tasks", SimpleNamespace(process_whatsapp_broadcast=object()))
    return SimpleNamespace(group=group, recipient=recipient, user=user, session=session, publish=publish, prerequisite=prerequisite, settings=settings)


async def test_preview_returns_invite_field_exact_body_and_no_image(rig):
    rig.session.execute.return_value = db_result(rig.group)
    response = await preview_route.preview_broadcast_message(
        rig.group.id, WhatsAppPreviewRequest(message_type="group_invite", message_content=CONTENT, group_invite_link=LINK, header_image_id="stale-media"),
        current_user=rig.user, session=rig.session,
    )
    assert response.group_invite_link == LINK
    assert response.rendered_message == rendered()
    assert response.parameter_values == [CONTENT, LINK]
    assert response.header_parameter_values == []
    assert response.header_image_id is None
    assert response.template_name == "whatsapp_group_invite_v1"


async def test_preview_keeps_missing_invite_null_with_clear_placeholder(rig):
    rig.session.execute.return_value = db_result(rig.group)
    response = await preview_route.preview_broadcast_message(
        rig.group.id, WhatsAppPreviewRequest(message_type="group_invite"), current_user=rig.user, session=rig.session,
    )
    assert response.group_invite_link is None
    assert "[WhatsApp group invite link]" in response.rendered_message


@pytest.mark.parametrize("blocked", [None, "archive", "opt_in", "welcome", "missing_link"])
async def test_send_freezes_valid_invite_before_queue_and_keeps_existing_gates(rig, blocked):
    rig.session.execute.side_effect = [db_result(rig.group), db_result(), db_result(), db_result(), db_result(rows=[rig.recipient.id])]
    if blocked == "archive":
        rig.group.archived_at = datetime.now(UTC)
    elif blocked == "opt_in":
        rig.group.recipient_opt_in_confirmed_at = None
    elif blocked == "welcome":
        rig.prerequisite.side_effect = HTTPException(409, "Welcome required")
    body = WhatsAppSendRequest(message_type="group_invite", message_content=CONTENT, group_invite_link=None if blocked == "missing_link" else LINK)
    if blocked:
        with pytest.raises(HTTPException):
            await whatsapp_send.send_broadcast_message(rig.group.id, body, current_user=rig.user, session=rig.session)
        rig.session.add.assert_not_called()
        rig.publish.assert_not_awaited()
        return
    response = await whatsapp_send.send_broadcast_message(rig.group.id, body, current_user=rig.user, session=rig.session)
    assert response.queued == 1
    log = rig.session.add.call_args.args[0]
    assert log.template_parameter_values == [CONTENT, LINK]
    assert log.header_parameter_values == []
    assert log.rendered_message == rendered()
    assert log.template_language == "en"
    payload = rig.publish.await_args.kwargs["payload"]
    assert payload["group_invite_link"] == LINK
    assert payload["message_type"] == "group_invite"
    assert payload["passport_link"] is None
    rig.session.commit.assert_awaited_once()
    assert rig.prerequisite.await_args.kwargs["message_type"] == "group_invite"


@pytest.mark.parametrize("prior_status", ["failed", "delivered"])
async def test_single_retry_and_explicit_resend_use_saved_invite_and_edited_link(rig, prior_status):
    source = saved_log()
    rig.settings.whatsapp_group_invite_template_language = "en_US"
    state = SimpleNamespace(status=prior_status)
    rig.session.execute.side_effect = [db_result(rig.group), db_result(rig.recipient), db_result(state), db_result(), db_result(), db_result(), db_result(source)]
    response = await resend_route.resend_recipient_message(
        rig.group.id, rig.recipient.id,
        WhatsAppResendRequest(message_type="group_invite", group_invite_link=EDITED_LINK),
        Request({"type": "http", "client": ("127.0.0.1", 1234)}), current_user=rig.user, session=rig.session,
    )
    assert response.queued == 1
    log = rig.session.add.call_args.args[0]
    assert log.template_parameter_values == [CONTENT, EDITED_LINK]
    assert log.template_language == "en"
    assert log.header_parameter_values == []
    assert log.rendered_message == rendered(link=EDITED_LINK)
    assert log.is_explicit_resend == (prior_status == "delivered")
    payload = rig.publish.await_args.kwargs["payload"]
    assert payload["group_invite_link"] == EDITED_LINK
    assert payload["message_content"] == CONTENT
    if prior_status == "failed":
        assert state.status == "queued"


@pytest.mark.parametrize("edited", [False, True])
async def test_bulk_retry_preserves_each_saved_invite_and_applies_only_explicit_edits(bulk_fixture, edited):
    fixture = bulk_fixture
    fixture.body = fixture.body.model_copy(update={
        "message_type": "group_invite",
        "message_content": "Updated shared invitation" if edited else None,
        "group_invite_link": EDITED_LINK if edited else None,
    })
    for index, person in enumerate(fixture.recipients):
        content, link = f"Saved invitation {index}", f"https://chat.whatsapp.com/PersonalInvite{index}"
        fixture.sources[person.id] = saved_log(template_parameter_values=[content, link], rendered_message=rendered(content, link))
    result = await bulk_test_support.invoke(fixture)
    assert result.queued == len(fixture.recipients)
    logs = {call.args[0].recipient_id: call.args[0] for call in fixture.session.add.call_args_list}
    for index, person in enumerate(fixture.recipients):
        expected = ["Updated shared invitation", EDITED_LINK] if edited else [f"Saved invitation {index}", f"https://chat.whatsapp.com/PersonalInvite{index}"]
        assert logs[person.id].template_parameter_values == expected
        assert logs[person.id].header_parameter_values == []
        assert logs[person.id].template_language == "en"
    payload = fixture.publish.await_args.kwargs["payload"]
    assert payload["message_type"] == "group_invite"
    assert payload["group_invite_link"].startswith("https://chat.whatsapp.com/")
    assert payload["passport_link"] is None
