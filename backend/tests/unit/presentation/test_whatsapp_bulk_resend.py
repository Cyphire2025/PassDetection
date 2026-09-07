"""Selected resends keep recipient scope, private snapshots and durable retry identity."""

from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.domain.entities.entities import UserRole
from app.presentation.api.v1.routes import whatsapp_bulk_resend as route
from app.presentation.api.v1.routes import whatsapp_bulk_resend_support as support
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBulkResendRequest,
    WhatsAppSendResult,
)


def result(value=None, rows=None):
    response = MagicMock()
    response.scalar_one_or_none.return_value = value
    response.scalars.return_value.all.return_value = rows or []
    return response


def source(recipient, message_type="welcome", **overrides):
    values = dict(
        id=uuid.uuid4(),
        recipient_id=recipient.id,
        broadcast_group_id=recipient.broadcast_group_id,
        message_type=message_type,
        template_name=f"{message_type}_approved",
        rendered_message=f"Saved message for {recipient.id}",
        header_parameter_values=[f"saved-media-{recipient.id}"],
        template_parameter_values=(
            [f"Saved welcome for {recipient.id}"]
            if message_type == "welcome"
            else [
                "Saved intro",
                f"https://tech.gctravels.com/passport/{recipient.id}",
                f"Saved instructions {recipient.id}",
                "Saved coordinator: +919876543210",
            ]
        ),
        status="sent",
    )
    return SimpleNamespace(**(values | overrides))


@pytest.fixture
def fixture(monkeypatch):
    group = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        name="Test trip",
        recipient_opt_in_confirmed_at=datetime.now(tz=UTC),
    )
    recipients = [
        SimpleNamespace(
            id=uuid.uuid4(),
            agency_id=group.agency_id,
            broadcast_group_id=group.id,
            normalized_phone_number=f"+9198765432{index:02}",
            removed_at=None,
        )
        for index in range(10)
    ]
    states = {
        recipient.id: SimpleNamespace(recipient_id=recipient.id, status="sent")
        for recipient in recipients
    }
    sources = {recipient.id: source(recipient) for recipient in recipients}
    session = AsyncMock()
    session.add = MagicMock()
    session.execute.side_effect = [result(group), result(), result(rows=recipients)]
    audit = AsyncMock()
    publish = AsyncMock()
    expire = AsyncMock()
    maps = AsyncMock(return_value=(states, {}, sources))
    replaced = AsyncMock(return_value=set())
    monkeypatch.setattr(route.AuditLogRepository, "record", audit)
    monkeypatch.setattr(route, "publish_whatsapp_task", publish)
    monkeypatch.setattr(route, "expire_stale_explicit_claims", expire)
    monkeypatch.setattr(route, "selection_delivery_maps", maps)
    monkeypatch.setattr(route, "active_replacement_phone_numbers_for_broadcast", replaced)
    monkeypatch.setattr(
        route,
        "get_settings",
        lambda: SimpleNamespace(
            whatsapp_access_token="test-token",
            whatsapp_phone_number_id="test-phone",
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.infrastructure.whatsapp.tasks",
        SimpleNamespace(
            process_whatsapp_broadcast=object(),
        ),
    )
    user = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=group.agency_id,
        role=UserRole.AGENCY_ADMIN,
        email="staff@example.com",
    )
    body = WhatsAppBulkResendRequest(
        message_type="welcome",
        recipient_ids=[person.id for person in recipients],
        request_id=uuid.uuid4(),
    )
    return SimpleNamespace(
        group=group,
        recipients=recipients,
        states=states,
        sources=sources,
        session=session,
        audit=audit,
        publish=publish,
        expire=expire,
        maps=maps,
        replaced=replaced,
        user=user,
        body=body,
    )


async def invoke(fixture, body=None):
    return await route.resend_selected_recipient_messages(
        group_id=fixture.group.id,
        body=body or fixture.body,
        request=Request({"type": "http", "client": ("127.0.0.1", 1234)}),
        current_user=fixture.user,
        session=fixture.session,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"recipient_ids": []},
        {"recipient_ids": None},
        {"message_type": "reminder"},
        {"message_type": "unknown"},
        {"request_id": None},
        {"unsupported_override": "Do not silently accept an unknown override"},
        {"passport_link": "https://example.com/shared"},
    ],
)
def test_request_requires_explicit_bounded_selection_and_no_content_overrides(changes):
    payload = dict(message_type="welcome", recipient_ids=[uuid.uuid4()], request_id=uuid.uuid4())
    with pytest.raises(ValidationError):
        WhatsAppBulkResendRequest(**(payload | changes))


def test_request_rejects_duplicates_missing_selection_and_over_capacity():
    person = uuid.uuid4()
    for selected in ([person, person], [uuid.uuid4() for _ in range(1501)]):
        with pytest.raises(ValidationError):
            WhatsAppBulkResendRequest(
                message_type="welcome", recipient_ids=selected, request_id=uuid.uuid4()
            )
    with pytest.raises(ValidationError):
        WhatsAppBulkResendRequest(message_type="welcome", request_id=uuid.uuid4())


def test_route_has_existing_role_csrf_and_session_boundary():
    endpoint = route.router.routes[0]
    assert endpoint.path == "/groups/{group_id}/recipients/resend"
    assert endpoint.methods == {"POST"}
    assert [item.call.__name__ for item in endpoint.dependant.dependencies] == [
        "require_cookie_csrf",
        "_check_role",
        "get_db_session",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing_group", "opt_in", "foreign_recipient"])
async def test_invalid_scope_fails_atomically_before_claims(fixture, failure):
    if failure == "missing_group":
        fixture.session.execute.side_effect = [result()]
    elif failure == "opt_in":
        fixture.group.recipient_opt_in_confirmed_at = None
    else:
        fixture.session.execute.side_effect = [
            result(fixture.group),
            result(),
            result(rows=fixture.recipients[:-1]),
        ]
    with pytest.raises(HTTPException) as caught:
        await invoke(fixture)
    assert caught.value.status_code == (400 if failure == "opt_in" else 404)
    fixture.session.add.assert_not_called()
    fixture.expire.assert_not_awaited()
    fixture.publish.assert_not_awaited()
    fixture.audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_group_and_recipient_queries_are_agency_scoped_locked_and_exact(fixture):
    await invoke(fixture)
    statements = [call.args[0] for call in fixture.session.execute.await_args_list]
    sql = [
        str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={
                    "literal_binds": True,
                },
            )
        )
        for statement in statements
    ]
    assert str(fixture.user.agency_id) in sql[0] and "FOR UPDATE" in sql[0]
    assert str(fixture.group.id) in sql[2] and "FOR UPDATE" in sql[2]
    assert "removed_at IS NULL" in sql[2]
    assert "whatsapp_broadcast_recipients.id IN" in sql[2]
    assert "whatsapp_broadcast_recipients.agency_id" in sql[2]


@pytest.mark.asyncio
async def test_mixed_selection_skips_blocked_and_preserves_accepted_baseline(fixture):
    people = fixture.recipients
    fixture.states[people[1].id].status = "failed"
    fixture.states[people[2].id].status = "queued"
    fixture.states[people[3].id].status = "delivery_unknown"
    fixture.states.pop(people[4].id)
    fixture.sources.pop(people[5].id)
    fixture.states[people[6].id].status = "cancelled"
    fixture.replaced.return_value = {people[7].normalized_phone_number}
    active = {people[8].id: {"delivery_unknown"}, people[9].id: {"processing"}}
    fixture.maps.return_value = (fixture.states, active, fixture.sources)

    response = await invoke(fixture)
    assert response.selected == 10 and response.queued == 2
    assert response.skipped_in_progress == 2
    assert response.skipped_delivery_unknown == 2
    assert response.skipped_no_saved_message == 2
    assert response.skipped_replaced == 1 and response.skipped_ineligible == 1
    assert response.skipped_already_sent == 0
    logs = [call.args[0] for call in fixture.session.add.call_args_list]
    assert {log.recipient_id for log in logs} == {people[0].id, people[1].id}
    assert {log.batch_id for log in logs} == {response.batch_id}
    assert logs[0].is_explicit_resend is True
    assert fixture.states[people[0].id].status == "sent"
    assert logs[1].is_explicit_resend is False
    assert fixture.states[people[1].id].status == "queued"
    assert fixture.states[people[1].id].batch_id == response.batch_id
    fixture.publish.assert_awaited_once()
    fixture.audit.assert_awaited_once()
    assert all(item.error_message for item in response.results if item.status.startswith("skipped"))


@pytest.mark.asyncio
async def test_only_selected_two_are_queued_with_individual_saved_passport_links(fixture):
    people = fixture.recipients[:2]
    fixture.session.execute.side_effect = [result(fixture.group), result(), result(rows=people)]
    fixture.body = fixture.body.model_copy(
        update={
            "message_type": "passport_link",
            "recipient_ids": [person.id for person in people],
        }
    )
    fixture.sources.update({person.id: source(person, "passport_link") for person in people})
    response = await invoke(fixture)
    logs = [call.args[0] for call in fixture.session.add.call_args_list]
    assert response.queued == 2 and len(logs) == 2
    for log, person in zip(logs, people, strict=True):
        saved = fixture.sources[person.id]
        assert log.template_parameter_values == saved.template_parameter_values
        assert log.header_parameter_values == saved.header_parameter_values
        assert log.template_name == saved.template_name
        assert log.rendered_message == saved.rendered_message
    assert logs[0].template_parameter_values[1] != logs[1].template_parameter_values[1]
    metadata = fixture.audit.await_args.kwargs["metadata"]
    assert all(item["phone_number"] == "" for item in metadata["response"]["results"])
    assert "passport/" not in str(metadata)
    assert "saved-media" not in str(metadata)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["missing_template", "missing_snapshot", "invalid_link"])
async def test_invalid_saved_message_is_skipped_without_guessing(fixture, invalid):
    person = fixture.recipients[0]
    fixture.body = fixture.body.model_copy(
        update={
            "message_type": "passport_link",
            "recipient_ids": [person.id],
        }
    )
    fixture.session.execute.side_effect = [result(fixture.group), result(), result(rows=[person])]
    saved = source(person, "passport_link")
    if invalid == "missing_template":
        saved.template_name = None
    elif invalid == "missing_snapshot":
        saved.header_parameter_values = None
    else:
        saved.template_parameter_values[1] = "javascript:alert(1)"
    fixture.sources[person.id] = saved
    response = await invoke(fixture)
    assert response.queued == 0 and response.batch_id is None
    assert response.skipped_no_saved_message == 1
    fixture.publish.assert_not_awaited()
    fixture.session.add.assert_not_called()


@pytest.mark.asyncio
async def test_repeated_request_returns_current_batch_without_another_dispatch(fixture):
    first = await invoke(fixture)
    receipt = fixture.audit.await_args.kwargs["metadata"]
    delivered_logs = [
        SimpleNamespace(
            recipient_id=person.id,
            status="delivered",
            provider_message_id="test-provider",
            error_message=None,
        )
        for person in fixture.recipients
    ]
    fixture.session.execute.side_effect = [
        result(fixture.group),
        result(SimpleNamespace(metadata_json=receipt)),
        result(rows=fixture.recipients),
        result(rows=delivered_logs),
    ]
    second = await invoke(fixture)
    assert second.replayed is True
    assert second.batch_id == first.batch_id and second.sent == 10 and second.queued == 0
    assert all(item.phone_number for item in second.results)
    fixture.publish.assert_awaited_once()
    assert fixture.session.add.call_count == 10
    fixture.audit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["selection", "message_type"])
async def test_same_request_id_rejects_changed_payload(fixture, change):
    await invoke(fixture)
    receipt = fixture.audit.await_args.kwargs["metadata"]
    fixture.session.execute.side_effect = [
        result(fixture.group),
        result(SimpleNamespace(metadata_json=receipt)),
    ]
    updates = (
        {"recipient_ids": fixture.body.recipient_ids[:1]}
        if change == "selection"
        else {"message_type": "passport_link"}
    )
    with pytest.raises(HTTPException) as caught:
        await invoke(fixture, fixture.body.model_copy(update=updates))
    assert caught.value.status_code == 409
    fixture.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_all_skipped_request_is_still_durable_and_replayable(fixture):
    fixture.maps.return_value = ({}, {}, {})
    first = await invoke(fixture)
    receipt = fixture.audit.await_args.kwargs["metadata"]
    fixture.session.execute.side_effect = [
        result(fixture.group),
        result(SimpleNamespace(metadata_json=receipt)),
        result(rows=fixture.recipients),
    ]
    second = await invoke(fixture)
    assert first.batch_id is None and second.batch_id is None
    assert second.replayed and second.skipped_no_saved_message == 10
    fixture.publish.assert_not_awaited()
    fixture.audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_provider_config_rolls_back_and_never_records_accepted_request(
    fixture, monkeypatch
):
    monkeypatch.setattr(
        route,
        "get_settings",
        lambda: SimpleNamespace(
            whatsapp_access_token="",
            whatsapp_phone_number_id="",
        ),
    )
    with pytest.raises(HTTPException) as caught:
        await invoke(fixture)
    assert caught.value.status_code == 503
    fixture.session.rollback.assert_awaited_once()
    fixture.session.commit.assert_not_awaited()
    fixture.audit.assert_not_awaited()
    fixture.publish.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("log_status", ["queued", "processing"])
async def test_replay_of_interrupted_publication_reports_stalled_without_republishing(
    fixture, log_status
):
    first = await invoke(fixture)
    receipt = fixture.audit.await_args.kwargs["metadata"]
    logs = [
        SimpleNamespace(
            recipient_id=person.id,
            status=log_status,
            status_updated_at=datetime.now(tz=UTC) - timedelta(minutes=31),
            provider_message_id=None,
            error_message=None,
        )
        for person in fixture.recipients
    ]
    fixture.session.execute.side_effect = [
        result(fixture.group),
        result(SimpleNamespace(metadata_json=receipt)),
        result(rows=fixture.recipients),
        result(rows=logs),
    ]
    response = await invoke(fixture)
    assert response.batch_id == first.batch_id
    assert response.queued == 0 and response.delivery_unknown == 10
    assert all(item.status == "stalled" and item.error_message for item in response.results)
    fixture.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_concurrent_claim_constraint_failure_rolls_back_whole_batch(fixture):
    fixture.session.flush.side_effect = IntegrityError("test", {}, Exception("unique claim"))
    with pytest.raises(HTTPException) as caught:
        await invoke(fixture)
    assert caught.value.status_code == 409
    fixture.session.rollback.assert_awaited_once()
    fixture.session.commit.assert_not_awaited()
    fixture.publish.assert_not_awaited()
    fixture.audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_broker_failure_compensates_only_unclaimed_rows_and_returns_same_batch(
    fixture, monkeypatch
):
    compensate = AsyncMock()
    monkeypatch.setattr(route, "fail_unclaimed_broadcast_rows", compensate)
    fixture.publish.side_effect = RuntimeError("test broker interruption")
    failed = [
        SimpleNamespace(
            recipient_id=person.id,
            status="failed",
            provider_message_id=None,
            error_message="WHATSAPP_QUEUE_UNAVAILABLE",
        )
        for person in fixture.recipients
    ]
    fixture.session.execute.side_effect = [
        result(fixture.group),
        result(),
        result(rows=fixture.recipients),
        result(rows=failed),
    ]
    response = await invoke(fixture)
    assert response.batch_id is not None and response.failed == 10 and response.queued == 0
    compensate.assert_awaited_once()
    assert compensate.await_args.kwargs["batch_id"] == response.batch_id
    assert all(state.status == "sent" for state in fixture.states.values())


@pytest.mark.asyncio
async def test_selection_maps_bound_history_and_do_not_reuse_other_groups(fixture):
    session = AsyncMock()
    session.execute.side_effect = [result(rows=list(fixture.states.values())), result(), result()]
    await support.selection_delivery_maps(session, group_id=fixture.group.id, body=fixture.body)
    compiled = [
        str(
            call.args[0].compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        for call in session.execute.await_args_list
    ]
    assert all(str(fixture.group.id) in sql and "recipient_id IN" in sql for sql in compiled)
    assert "FOR UPDATE" in compiled[0]
    assert "DISTINCT ON (whatsapp_message_logs.recipient_id)" in compiled[2]
    assert "created_at DESC" in compiled[2]


@pytest.mark.asyncio
async def test_stale_processing_is_unknown_and_never_released_for_resend(fixture):
    session = AsyncMock()
    await support.expire_stale_explicit_claims(
        session, group_id=fixture.group.id, body=fixture.body
    )
    statements = [call.args[0] for call in session.execute.await_args_list]
    parameters = [statement.compile().params for statement in statements]
    assert parameters[0]["status"] == "failed"
    assert parameters[1]["status"] == "delivery_unknown"
    sql = [str(statement.compile(dialect=postgresql.dialect())) for statement in statements]
    assert all(
        "is_explicit_resend IS true" in query and "recipient_id IN" in query for query in sql
    )


def test_selection_fingerprint_is_order_independent_but_type_specific(fixture):
    reverse = fixture.body.model_copy(
        update={"recipient_ids": list(reversed(fixture.body.recipient_ids))}
    )
    assert support.selection_fingerprint(reverse) == support.selection_fingerprint(fixture.body)
    other = fixture.body.model_copy(update={"message_type": "passport_link"})
    assert support.selection_fingerprint(other) != support.selection_fingerprint(fixture.body)


def test_response_keeps_actual_unknown_separate_from_skipped_unknown():
    response = support.build_response(
        batch_id=uuid.uuid4(),
        results=[
            WhatsAppSendResult(recipient_id=uuid.uuid4(), phone_number="", status=value)
            for value in [
                "queued",
                "processing",
                "submitted",
                "delivered",
                "failed",
                "delivery_unknown",
                "skipped_delivery_unknown",
            ]
        ],
    )
    assert (
        response.queued,
        response.sent,
        response.failed,
        response.delivery_unknown,
        response.skipped_delivery_unknown,
    ) == (2, 2, 1, 1, 1)
