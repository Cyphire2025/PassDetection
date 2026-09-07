"""Editable selected resends preserve personal links and preview without mutations."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Response
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.presentation.api.v1.routes import whatsapp_bulk_resend_composer as composer
from app.presentation.api.v1.routes import whatsapp_bulk_resend_preview as preview_route
from app.presentation.api.v1.routes import whatsapp_bulk_resend_support as support
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBulkResendPreviewRequest,
    WhatsAppBulkResendRequest,
)
from tests.unit.presentation import test_whatsapp_bulk_resend as resend_test_support
from tests.unit.presentation.test_whatsapp_bulk_resend import (
    invoke,
    result,
    source,
)

bulk_resend_fixture = resend_test_support.fixture


@pytest.fixture
def preview_fixture(bulk_resend_fixture, monkeypatch):
    fixture = bulk_resend_fixture
    for recipient in fixture.recipients:
        recipient.name = f"Passenger {recipient.id}"
    fixture.body = fixture.body.model_copy(update={"message_type": "passport_link"})
    fixture.sources.update(
        {recipient.id: source(recipient, "passport_link") for recipient in fixture.recipients}
    )
    fixture.session.execute.side_effect = [result(fixture.group), result(rows=fixture.recipients)]
    monkeypatch.setattr(preview_route, "selection_delivery_maps", fixture.maps)
    monkeypatch.setattr(
        preview_route, "active_replacement_phone_numbers_for_broadcast", fixture.replaced
    )
    monkeypatch.setattr(
        composer, "_configured_template_name", lambda message_type: f"current-{message_type}"
    )
    return fixture


async def preview(fixture, **changes):
    body = WhatsAppBulkResendPreviewRequest(
        **(fixture.body.model_dump(exclude={"request_id"}) | changes)
    )
    response = Response()
    value = await preview_route.preview_selected_recipient_messages(
        group_id=fixture.group.id,
        body=body,
        response=response,
        current_user=fixture.user,
        session=fixture.session,
    )
    assert response.headers["Cache-Control"] == "private, no-store"
    return value


@pytest.mark.asyncio
async def test_preview_uses_chosen_persons_saved_passport_link_and_preserves_others(
    preview_fixture,
):
    fixture = preview_fixture
    chosen = fixture.recipients[1]
    shown = await preview(fixture, preview_recipient_id=chosen.id)
    assert shown.recipient_id == chosen.id
    assert shown.passport_link == fixture.sources[chosen.id].template_parameter_values[1]
    assert shown.message_content == fixture.sources[chosen.id].template_parameter_values[2]
    assert shown.eligible_recipient_ids == fixture.body.recipient_ids
    assert shown.eligible_recipient_count == shown.selected == 10
    fixture.session.add.assert_not_called()
    fixture.session.flush.assert_not_awaited()
    fixture.session.commit.assert_not_awaited()
    fixture.publish.assert_not_awaited()
    fixture.audit.assert_not_awaited()
    fixture.maps.assert_awaited_once()
    assert fixture.maps.await_args.kwargs["lock_states"] is False
    statements = [
        str(
            call.args[0].compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        for call in fixture.session.execute.await_args_list
    ]
    assert all(
        statement.startswith("SELECT") and "FOR UPDATE" not in statement for statement in statements
    )
    assert str(fixture.group.agency_id) in statements[0]
    assert str(fixture.group.agency_id) in statements[1]
    assert str(chosen.id) in statements[1]


@pytest.mark.asyncio
async def test_preview_and_send_share_exact_rendering_while_private_links_remain_distinct(
    preview_fixture,
):
    fixture = preview_fixture
    edits = {
        "message_content": "Please upload your revised documents.",
        "passport_intro": "Your new trip information.",
    }
    chosen = fixture.recipients[1]
    shown = await preview(fixture, preview_recipient_id=chosen.id, **edits)
    fixture.body = fixture.body.model_copy(update=edits)
    fixture.session.execute.side_effect = [
        result(fixture.group),
        result(),
        result(rows=fixture.recipients),
    ]
    sent = await invoke(fixture)
    assert sent.queued == 10
    logs = [call.args[0] for call in fixture.session.add.call_args_list]
    for log in logs:
        saved = fixture.sources[log.recipient_id]
        assert log.template_parameter_values[0] == edits["passport_intro"]
        assert log.template_parameter_values[2] == edits["message_content"]
        assert log.template_parameter_values[1] == saved.template_parameter_values[1]
        assert log.template_parameter_values[3] == saved.template_parameter_values[3]
        assert log.header_parameter_values == saved.header_parameter_values
    chosen_log = next(log for log in logs if log.recipient_id == chosen.id)
    assert shown.rendered_message == chosen_log.rendered_message
    assert shown.parameter_values == chosen_log.template_parameter_values
    assert shown.header_parameter_values == chosen_log.header_parameter_values
    assert len({log.template_parameter_values[1] for log in logs}) == 10


@pytest.mark.asyncio
async def test_preview_counts_skip_replaced_unknown_active_and_missing_sources(preview_fixture):
    fixture = preview_fixture
    people = fixture.recipients
    fixture.states[people[0].id].status = "processing"
    fixture.states[people[1].id].status = "delivery_unknown"
    fixture.replaced.return_value = {people[2].normalized_phone_number}
    fixture.sources.pop(people[3].id)
    fixture.states[people[4].id].status = "cancelled"
    shown = await preview(fixture)
    assert shown.recipient_id == people[5].id
    assert shown.eligible_recipient_count == 5
    assert shown.skipped_in_progress == shown.skipped_delivery_unknown == 1
    assert shown.skipped_replaced == shown.skipped_no_saved_message == shown.skipped_ineligible == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["group", "foreign_selection", "outside_preview", "blocked_preview", "no_eligible"]
)
async def test_preview_rejects_inaccessible_or_ineligible_selection_without_effects(
    preview_fixture, failure
):
    fixture = preview_fixture
    changes = {}
    expected = 404
    if failure == "group":
        fixture.session.execute.side_effect = [result()]
    elif failure == "foreign_selection":
        fixture.session.execute.side_effect = [
            result(fixture.group),
            result(rows=fixture.recipients[:-1]),
        ]
    elif failure == "outside_preview":
        changes["preview_recipient_id"] = uuid.uuid4()
    elif failure == "blocked_preview":
        fixture.states[fixture.recipients[0].id].status = "delivery_unknown"
        changes["preview_recipient_id"] = fixture.recipients[0].id
        expected = 409
    else:
        fixture.maps.return_value = ({}, {}, {})
        expected = 409
    with pytest.raises(HTTPException) as caught:
        await preview(fixture, **changes)
    assert caught.value.status_code == expected
    fixture.session.add.assert_not_called()
    fixture.session.flush.assert_not_awaited()
    fixture.session.commit.assert_not_awaited()
    fixture.publish.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "draft", [{"message_content": " "}, {"passport_intro": "\n"}, {"header_image_id": " "}]
)
async def test_invalid_draft_is_atomic_before_stale_claim_mutation(preview_fixture, draft):
    fixture = preview_fixture
    fixture.body = fixture.body.model_copy(update=draft)
    fixture.session.execute.side_effect = [
        result(fixture.group),
        result(),
        result(rows=fixture.recipients),
    ]
    with pytest.raises(HTTPException) as caught:
        await invoke(fixture)
    assert caught.value.status_code == 400
    fixture.expire.assert_not_awaited()
    fixture.maps.assert_not_awaited()
    fixture.session.add.assert_not_called()
    fixture.session.commit.assert_not_awaited()
    fixture.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_support_contact_override_is_scoped_and_omission_preserves_saved_block(
    preview_fixture, monkeypatch
):
    fixture = preview_fixture
    contact = SimpleNamespace(id=uuid.uuid4(), name="New coordinator", phone_number="+919876543210")
    contacts = AsyncMock(return_value=[contact])
    monkeypatch.setattr(composer, "_support_contacts_for_group", contacts)
    shown = await preview(fixture, support_contact_ids=[contact.id])
    assert shown.parameter_values[3] == "New coordinator: +919876543210"
    assert (
        shown.passport_link
        == fixture.sources[fixture.recipients[0].id].template_parameter_values[1]
    )
    contacts.assert_awaited_once_with(fixture.session, fixture.group.id)
    for requested, expected in [([], 400), ([uuid.uuid4()], 404)]:
        fixture.session.execute.side_effect = [
            result(fixture.group),
            result(rows=fixture.recipients),
        ]
        with pytest.raises(HTTPException) as caught:
            await preview(fixture, support_contact_ids=requested)
        assert caught.value.status_code == expected


@pytest.mark.asyncio
async def test_header_override_uses_existing_header_validator_and_current_template(preview_fixture):
    shown = await preview(preview_fixture, header_image_id=" newly-uploaded-media ")
    assert shown.header_parameter_values == ["newly-uploaded-media"]
    assert shown.template_name == "current-passport_link"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"message_content": "Changed body"},
        {"passport_intro": "Changed intro"},
        {"header_image_id": "changed-media"},
        {"support_contact_ids": [uuid.uuid4()]},
    ],
)
async def test_changed_draft_with_same_request_id_is_rejected_before_dispatch(
    preview_fixture, changes
):
    fixture = preview_fixture
    fixture.session.execute.side_effect = [
        result(fixture.group),
        result(),
        result(rows=fixture.recipients),
    ]
    await invoke(fixture)
    receipt = fixture.audit.await_args.kwargs["metadata"]
    fixture.session.execute.side_effect = [
        result(fixture.group),
        result(SimpleNamespace(metadata_json=receipt)),
    ]
    with pytest.raises(HTTPException) as caught:
        await invoke(fixture, fixture.body.model_copy(update=changes))
    assert caught.value.status_code == 409
    fixture.publish.assert_awaited_once()


def test_null_and_omitted_overrides_preserve_old_receipt_fingerprint():
    recipient_id = uuid.uuid4()
    original = WhatsAppBulkResendRequest(
        message_type="welcome", recipient_ids=[recipient_id], request_id=uuid.uuid4()
    )
    explicit_nulls = original.model_copy(
        update={
            "message_content": None,
            "passport_intro": None,
            "header_image_id": None,
            "support_contact_ids": None,
        }
    )
    legacy = hashlib.sha256(f"welcome:{recipient_id}".encode()).hexdigest()
    assert (
        support.selection_fingerprint(original)
        == support.selection_fingerprint(explicit_nulls)
        == legacy
    )


@pytest.mark.parametrize("model", [WhatsAppBulkResendRequest, WhatsAppBulkResendPreviewRequest])
def test_private_passport_link_override_remains_forbidden(model):
    kwargs = dict(
        message_type="passport_link",
        recipient_ids=[uuid.uuid4()],
        passport_link="https://example.com/shared",
    )
    if model is WhatsAppBulkResendRequest:
        kwargs["request_id"] = uuid.uuid4()
    with pytest.raises(ValidationError):
        model(**kwargs)


@pytest.mark.asyncio
async def test_preview_delivery_reads_do_not_lock_or_change_stale_logs(preview_fixture):
    fixture = preview_fixture
    stale = datetime.now(tz=UTC) - timedelta(minutes=31)
    queued = SimpleNamespace(
        recipient_id=fixture.recipients[0].id,
        status="queued",
        is_explicit_resend=True,
        status_updated_at=stale,
    )
    processing = SimpleNamespace(
        recipient_id=fixture.recipients[1].id,
        status="processing",
        is_explicit_resend=True,
        status_updated_at=stale,
    )
    session = AsyncMock()
    session.execute.side_effect = [
        result(rows=list(fixture.states.values())),
        result(rows=[queued, processing]),
        result(rows=list(fixture.sources.values())),
    ]
    _, active, _ = await support.selection_delivery_maps(
        session, group_id=fixture.group.id, body=fixture.body, lock_states=False
    )
    assert queued.recipient_id not in active
    assert active[processing.recipient_id] == {"delivery_unknown"}
    assert queued.status == "queued" and processing.status == "processing"
    assert all("FOR UPDATE" not in str(call.args[0]) for call in session.execute.await_args_list)
    session.flush.assert_not_awaited()
    session.commit.assert_not_awaited()


def test_preview_route_is_read_only_role_protected():
    endpoint = preview_route.router.routes[0]
    assert endpoint.path == "/groups/{group_id}/recipients/resend/preview"
    assert [item.call.__name__ for item in endpoint.dependant.dependencies] == [
        "_check_role",
        "get_db_session",
    ]


@pytest.mark.asyncio
async def test_null_draft_fields_do_not_copy_sample_values_to_other_recipients(preview_fixture):
    fixture = preview_fixture
    shown = await preview(
        fixture,
        message_content=None,
        passport_intro=None,
        header_image_id=None,
        support_contact_ids=None,
    )
    fixture.body = fixture.body.model_copy(
        update={
            "message_content": None,
            "passport_intro": None,
            "header_image_id": None,
            "support_contact_ids": None,
        }
    )
    fixture.session.execute.side_effect = [
        result(fixture.group),
        result(),
        result(rows=fixture.recipients),
    ]
    await invoke(fixture)
    logs = [call.args[0] for call in fixture.session.add.call_args_list]
    assert logs[0].rendered_message == shown.rendered_message
    assert len({log.template_parameter_values[2] for log in logs}) == 10
    assert len({tuple(log.header_parameter_values) for log in logs}) == 10


@pytest.mark.asyncio
async def test_welcome_body_edits_keep_each_saved_image_and_no_passport_fields(preview_fixture):
    fixture = preview_fixture
    fixture.body = fixture.body.model_copy(update={"message_type": "welcome"})
    fixture.sources.update({recipient.id: source(recipient) for recipient in fixture.recipients})
    shown = await preview(fixture, message_content="We look forward to welcoming you.")
    assert shown.passport_link is None and shown.passport_intro is None
    assert shown.parameter_values == ["We look forward to welcoming you."]
    assert (
        shown.header_parameter_values
        == fixture.sources[fixture.recipients[0].id].header_parameter_values
    )
    assert "We look forward to welcoming you." in shown.rendered_message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes", [{"passport_intro": "Not a welcome field"}, {"support_contact_ids": []}]
)
async def test_welcome_rejects_inapplicable_edits_before_any_claim(preview_fixture, changes):
    fixture = preview_fixture
    fixture.body = fixture.body.model_copy(update={"message_type": "welcome"} | changes)
    fixture.session.execute.side_effect = [
        result(fixture.group),
        result(),
        result(rows=fixture.recipients),
    ]
    with pytest.raises(HTTPException) as caught:
        await invoke(fixture)
    assert caught.value.status_code == 400
    fixture.expire.assert_not_awaited()
    fixture.session.add.assert_not_called()


def test_legacy_welcome_edit_keeps_old_support_and_explicit_image_upgrades_template(
    preview_fixture,
):
    saved = source(
        preview_fixture.recipients[0],
        header_parameter_values=[],
        template_parameter_values=["Original welcome", "Saved coordinator"],
        template_name="legacy-text-welcome",
    )
    changed = composer.resolve_saved_resend_snapshot(
        saved, composer.BulkResendEdits(message_content="Edited welcome")
    )
    assert changed.template_name == "legacy-text-welcome"
    assert changed.parameters == ["Edited welcome", "Saved coordinator"]
    assert "For assistance, please contact:\nSaved coordinator" in changed.rendered_message
    upgraded = composer.resolve_saved_resend_snapshot(
        saved,
        composer.BulkResendEdits(
            header_image_id="new-media", media_template_name="current-media-welcome"
        ),
    )
    assert upgraded.template_name == "current-media-welcome"
    assert upgraded.parameters == ["Original welcome"]
    assert upgraded.header_parameters == ["new-media"]
    assert "For assistance" not in upgraded.rendered_message


@pytest.mark.parametrize("field", ["message_content", "passport_intro", "header_image_id"])
def test_draft_schema_limits_match_existing_composer(field):
    limit = 255 if field == "header_image_id" else 600
    with pytest.raises(ValidationError):
        WhatsAppBulkResendPreviewRequest(
            message_type="passport_link", recipient_ids=[uuid.uuid4()], **{field: "x" * (limit + 1)}
        )
