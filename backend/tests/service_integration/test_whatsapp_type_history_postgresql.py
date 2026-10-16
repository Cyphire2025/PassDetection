"""Exercise parameterized grouping on PostgreSQL, not SQLite's permissive GROUP BY."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
)
from app.presentation.api.v1.routes.whatsapp_type_history import (
    list_message_types,
    list_type_recipients,
    list_type_versions,
)
from tests.service_integration.test_whatsapp_receipts_postgresql import pg_factory as pg_factory

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1",
        reason="requires isolated PostgreSQL test service",
    ),
]


@pytest.mark.parametrize("kind", ["reminder", "group_invite", "document_update"])
async def test_type_coverage_and_numbered_identical_sends_on_postgresql(pg_factory, kind):
    async with pg_factory() as session:
        agency = AgencyModel(id=uuid.uuid4(), name="History fixture", email="history@example.test")
        session.add(agency)
        await session.flush()
        group = WhatsAppBroadcastGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Trip")
        session.add(group)
        await session.flush()
        person = WhatsAppBroadcastRecipientModel(
            id=uuid.uuid4(),
            broadcast_group_id=group.id,
            agency_id=agency.id,
            name="Fixture traveller",
            phone_number="+919800000001",
            normalized_phone_number="919800000001",
        )
        session.add(person)
        await session.flush()
        batches = [uuid.uuid4(), uuid.uuid4()]
        now = datetime.now(UTC)
        for index, batch in enumerate(batches):
            session.add(
                WhatsAppMessageLogModel(
                    id=uuid.uuid4(),
                    batch_id=batch,
                    broadcast_group_id=group.id,
                    agency_id=agency.id,
                    recipient_id=person.id,
                    normalized_phone_number=person.normalized_phone_number,
                    message_type="update" if kind == "document_update" and index == 0 else kind,
                    rendered_message="Same message on different days",
                    status="read" if index == 0 else "failed",
                    status_updated_at=now,
                    created_at=now - timedelta(days=1 - index),
                    template_name="fixture",
                    template_parameter_values=[],
                    header_parameter_values=[],
                )
            )
        await session.flush()
        actor = User(
            id=uuid.uuid4(),
            agency_id=agency.id,
            email="staff@example.test",
            hashed_password="fixture",
            full_name="Staff",
            role=UserRole.AGENCY_ADMIN,
        )
        summary = next(
            row
            for row in await list_message_types(
                group.id,
                current_user=actor,
                session=session,
            )
            if row.message_type == kind
        )
        assert summary.counts.all == summary.counts.sent == 1
        assert summary.counts.failed == 0 and summary.version_count == 2
        versions = await list_type_versions(
            group.id,
            kind,
            q="",
            offset=0,
            limit=25,
            current_user=actor,
            session=session,
        )
        assert [(row.id, row.version_number) for row in versions.items] == [
            (batches[1], 2),
            (batches[0], 1),
        ]
        assert versions.items[0].counts.failed == 1 and versions.items[1].counts.sent == 1
        recipients = await list_type_recipients(
            group.id,
            kind,
            status_filter="sent",
            q="Fixture",
            offset=0,
            limit=50,
            current_user=actor,
            session=session,
        )
        assert recipients.total == 1 and recipients.items[0].message_id == batches[0]
