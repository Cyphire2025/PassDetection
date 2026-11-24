"""Historical update validation/counts survive bounded detail retention."""

from __future__ import annotations

import uuid
import weakref
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.application.use_cases.whatsapp.document_updates import ACTIVE
from app.application.use_cases.whatsapp.group_updates import GroupUpdateFilters
from app.infrastructure.database.models import WhatsAppMessageLogModel
from app.presentation.api.v1.routes import group_update_preview as preview
from app.presentation.api.v1.schemas.group_update_schemas import GroupUpdateAudience
from tests.integration.test_group_updates import group_update as group_update

STATUSES = ("read", "failed", "delivery_unknown", "delivered", "queued", "processing")


async def seed_history(context, count: int):
    contacts = await preview.load_group_update_audience(
        context.session, agency_id=context.agency.id, group_id=context.group.id,
        filters=GroupUpdateFilters(),
    )
    logs = []
    for index in range(count):
        contact = contacts[index % len(contacts)]
        at = datetime(2026, 9, 1, tzinfo=UTC) + timedelta(seconds=index)
        details = {"group_id": str(context.group.id), "document_type": "visa"}
        if index % 2 and contact.passenger_id:
            details["passenger_ids"] = [str(contact.passenger_id)]
        else:
            details["audience_keys"] = [contact.audience_key]
        row = WhatsAppMessageLogModel(
            id=uuid.uuid4(), agency_id=context.agency.id,
            broadcast_group_id=context.broadcast.id, recipient_id=context.recipients[0].id,
            normalized_phone_number=contact.phone_number if index % 3 else "+919333444555",
            message_type="document_update", status=STATUSES[index % len(STATUSES)],
            created_at=at, status_updated_at=at, rendered_message=f"Saved update {index}",
            template_name="pending_v1", document_update_context=details,
        )
        context.session.add(row)
        logs.append(row)
    await context.session.commit()
    return contacts, logs


def observe_constructions(factory):
    metrics = SimpleNamespace(created=0, live=0, peak=0)

    def released():
        metrics.live -= 1

    def observed(**values):
        value = factory(**values)
        metrics.created += 1
        metrics.live += 1
        metrics.peak = max(metrics.peak, metrics.live)
        weakref.finalize(value, released)
        return value

    return observed, metrics


@pytest.mark.parametrize("count", [0, 1, 64, 512])
async def test_history_counts_and_latest_details_do_not_retain_every_attempt(
    group_update, monkeypatch, count,
):
    contacts, logs = await seed_history(group_update, count)
    observed, metrics = observe_constructions(preview.GroupUpdateAttempt)
    monkeypatch.setattr(preview, "GroupUpdateAttempt", observed)

    result = await preview.build_group_update_preview(
        group_update.session, group=group_update.group, audience=GroupUpdateAudience(),
    )

    # Every row is still validated, including old/unselected historical rows.
    assert metrics.created == count
    assert [row.audience_key for row in result.recipients] == [row.audience_key for row in contacts]
    for index, row in enumerate(result.recipients):
        own_logs = logs[index::len(contacts)]
        assert row.update_attempt_count == len(own_logs)
        if own_logs:
            latest = own_logs[-1]
            assert row.latest_update.id == latest.id
            assert row.latest_update_status == latest.status
            assert row.latest_update.message == latest.rendered_message
            assert row.latest_update.phone_number == latest.normalized_phone_number
            assert row.eligible is not any(log.status in ACTIVE for log in own_logs)
        else:
            assert row.latest_update is None and row.latest_update_status is None
    # The history maps still scan all rows. Only retained detail DTOs are bounded
    # by current audience keys/phones plus the current validation temporary.
    keys = {contact.audience_key for contact in contacts}
    keys.update(f"phone:{contact.phone_number}" for contact in contacts if contact.phone_number)
    assert metrics.peak <= len(keys) + 1
    group_update.provider.assert_not_awaited()
    group_update.publish.assert_not_awaited()


@pytest.mark.parametrize("current_contact", [True, False])
async def test_old_invalid_detail_is_validated_even_outside_current_audience(
    group_update, current_contact,
):
    contacts, _ = await seed_history(group_update, 1)
    context = {"group_id": str(group_update.group.id), "document_type": 42,
               "audience_keys": [contacts[0].audience_key if current_contact else f"recipient:{uuid.uuid4()}"]}
    group_update.session.add(WhatsAppMessageLogModel(
        id=uuid.uuid4(), agency_id=group_update.agency.id,
        broadcast_group_id=group_update.broadcast.id, recipient_id=group_update.recipients[0].id,
        normalized_phone_number="+919999444555", message_type="document_update", status="failed",
        created_at=datetime(2025, 1, 1, tzinfo=UTC), rendered_message="Legacy saved update",
        document_update_context=context,
    ))
    await group_update.session.commit()

    with pytest.raises(ValidationError) as raised:
        await preview.build_group_update_preview(
            group_update.session, group=group_update.group, audience=GroupUpdateAudience(),
        )

    assert raised.value.errors()[0]["loc"] == ("document_type",)
    group_update.provider.assert_not_awaited()
    group_update.publish.assert_not_awaited()
