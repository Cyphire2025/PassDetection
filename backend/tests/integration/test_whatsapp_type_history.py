"""Overall reach, repeated identical sends and legacy boundaries use real SQL."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
)
from app.presentation.api.v1.routes.whatsapp_type_history import (
    list_message_types,
    list_type_recipients,
    list_type_versions,
)
from tests.integration.test_whatsapp_workspace import workspace as workspace


def log(group, person, batch, *, kind="reminder", status="read", days=0, content="Same reminder"):
    at = datetime.now(UTC) - timedelta(days=days)
    return WhatsAppMessageLogModel(
        id=uuid.uuid4(),
        batch_id=batch,
        broadcast_group_id=group.id,
        agency_id=group.agency_id,
        recipient_id=person.id,
        normalized_phone_number=person.normalized_phone_number,
        message_type=kind,
        status=status,
        status_updated_at=datetime.now(UTC),
        created_at=at,
        rendered_message=content,
        template_name="approved",
        header_parameter_values=[],
        template_parameter_values=[content],
    )


async def people(session, group, count):
    rows = [
        WhatsAppBroadcastRecipientModel(
            id=uuid.uuid4(),
            broadcast_group_id=group.id,
            agency_id=group.agency_id,
            name=f"Person {index}",
            phone_number=f"+9198111111{index:02}",
            normalized_phone_number=f"9198111111{index:02}",
        )
        for index in range(count)
    ]
    session.add_all(rows)
    await session.flush()
    return rows


async def test_type_totals_count_people_once_and_keep_previous_success(workspace):
    session, group, first, actor = workspace
    second, third, fourth = await people(session, group, 3)
    batch1, batch2 = uuid.uuid4(), uuid.uuid4()
    session.add_all(
        [
            log(group, first, batch1, days=3),
            log(group, first, batch2, status="failed"),
            log(group, second, batch2, status="queued"),
            log(group, third, batch2, status="failed"),
        ]
    )
    await session.flush()
    summaries = await list_message_types(group.id, current_user=actor, session=session)
    reminder = next(row for row in summaries if row.message_type == "reminder")
    assert reminder.counts.model_dump() == {
        "all": 4,
        "sent": 1,
        "not_sent": 2,
        "delivery_left": 0,
        "failed": 1,
    }
    assert (
        reminder.version_count,
        reminder.total_attempts,
        reminder.accepted_attempts,
        reminder.never_attempted,
    ) == (2, 4, 1, 1)
    welcome = next(row for row in summaries if row.message_type == "welcome")
    assert welcome.counts.not_sent == 4 and welcome.send_count == 0
    report = await list_type_recipients(
        group.id,
        "reminder",
        status_filter="sent",
        q="",
        offset=0,
        limit=50,
        current_user=actor,
        session=session,
    )
    assert report.total == 1 and report.items[0].recipient_id == first.id
    assert report.items[0].status == "read" and report.items[0].message_id == batch1
    unsent = await list_type_recipients(
        group.id,
        "reminder",
        status_filter="not_sent",
        q="",
        offset=0,
        limit=50,
        current_user=actor,
        session=session,
    )
    assert {row.recipient_id for row in unsent.items} == {second.id, fourth.id}
    never = next(row for row in unsent.items if row.recipient_id == fourth.id)
    assert never.message_id is None and never.message_log_id is None


@pytest.mark.parametrize("kind", ["reminder", "group_invite", "document_update"])
async def test_identical_wording_is_still_a_new_numbered_version(workspace, kind):
    session, group, person, actor = workspace
    first, second = uuid.uuid4(), uuid.uuid4()
    session.add_all(
        [log(group, person, first, kind=kind, days=2), log(group, person, second, kind=kind)]
    )
    await session.flush()
    report = await list_type_versions(
        group.id, kind, q="", offset=0, limit=1, current_user=actor, session=session
    )
    assert (
        report.total == 2 and report.items[0].id == second and report.items[0].version_number == 2
    )
    previous = await list_type_versions(
        group.id, kind, q="", offset=1, limit=1, current_user=actor, session=session
    )
    assert previous.items[0].id == first and previous.items[0].version_number == 1
    assert previous.items[0].message_preview == report.items[0].message_preview
    summary = next(
        row
        for row in await list_message_types(group.id, current_user=actor, session=session)
        if row.message_type == kind
    )
    assert summary.counts.sent == 1 and summary.accepted_attempts == 2


async def test_legacy_records_are_visible_without_invented_versions_and_search_keeps_numbers(
    workspace,
):
    session, group, person, actor = workspace
    session.add_all(
        [
            log(group, person, None, days=5),
            log(group, person, uuid.uuid4(), days=3, content="First send"),
            log(group, person, uuid.uuid4(), content="Second send"),
        ]
    )
    await session.flush()
    all_rows = await list_type_versions(
        group.id, "reminder", q="", offset=0, limit=25, current_user=actor, session=session
    )
    assert [row.version_number for row in all_rows.items] == [2, 1, None]
    filtered = await list_type_versions(
        group.id, "reminder", q="First", offset=0, limit=25, current_user=actor, session=session
    )
    assert filtered.total == 1 and filtered.items[0].version_number == 1


async def test_type_scope_search_and_removed_recipients_keep_audiences_distinct(workspace):
    session, group, person, actor = workspace
    (other,) = await people(session, group, 1)
    other.name = "Literal % name"
    batch = uuid.uuid4()
    session.add_all(
        [log(group, person, batch), log(group, other, batch, status="delivery_unknown")]
    )
    await session.flush()
    report = await list_type_recipients(
        group.id,
        "reminder",
        status_filter="all",
        q="%",
        offset=0,
        limit=25,
        current_user=actor,
        session=session,
    )
    assert report.total == 1 and report.items[0].recipient_id == other.id
    assert report.counts.all == 2 and report.counts.failed == 1
    other.removed_at = datetime.now(UTC)
    await session.flush()
    summary = next(
        row
        for row in await list_message_types(group.id, current_user=actor, session=session)
        if row.message_type == "reminder"
    )
    assert summary.counts.all == 1 and summary.counts.failed == 0
    version = await list_type_versions(
        group.id, "reminder", q="", offset=0, limit=25, current_user=actor, session=session
    )
    assert version.items[0].counts.all == 2
    actor.agency_id = uuid.uuid4()
    for operation, kwargs in [
        (list_message_types, {}),
        (list_type_versions, {"message_type": "reminder", "q": "", "offset": 0, "limit": 25}),
        (
            list_type_recipients,
            {"message_type": "reminder", "status_filter": "all", "q": "", "offset": 0, "limit": 25},
        ),
    ]:
        with pytest.raises(HTTPException) as denied:
            await operation(group.id, current_user=actor, session=session, **kwargs)
        assert denied.value.status_code == 404


async def test_update_alias_is_one_type_and_provider_acceptance_is_delivery_left(workspace):
    session, group, person, actor = workspace
    session.add_all(
        [
            log(group, person, uuid.uuid4(), kind="update", days=2, status="sent"),
            log(group, person, uuid.uuid4(), kind="document_update", status="failed"),
        ]
    )
    await session.flush()
    summary = next(
        row
        for row in await list_message_types(group.id, current_user=actor, session=session)
        if row.message_type == "document_update"
    )
    assert summary.version_count == 2 and summary.counts.sent == summary.counts.delivery_left == 1
    report = await list_type_versions(
        group.id, "document_update", q="", offset=0, limit=25, current_user=actor, session=session
    )
    assert report.total == 2
