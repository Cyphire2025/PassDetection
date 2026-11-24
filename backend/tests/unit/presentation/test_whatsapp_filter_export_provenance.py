"""Real source correction, displacement, SQL batch and expansion controls."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    WhatsAppBroadcastSourceContactModel,
    WhatsAppTravellerPhoneOverrideModel,
)
from app.infrastructure.export.whatsapp_filter_excel_exporter import WhatsAppExportTooLarge
from app.infrastructure.whatsapp.phone_overrides import source_phone_fingerprint
from app.presentation.api.v1.routes import whatsapp_export_projection as export_projection
from app.presentation.api.v1.routes import whatsapp_exports as exports
from tests.persistence import persist_graph
from tests.whatsapp_filter_export_fixtures import NOW, persist_export_graph


async def test_replacement_exports_displaced_original_not_replacement_passenger(
    db_session: AsyncSession,
) -> None:
    graph = await persist_export_graph(db_session)
    original, displaced, replacement = (
        graph.recipients[1],
        graph.submissions[2],
        graph.submissions[3],
    )
    resolution = PassportRosterResolutionModel(
        id=uuid.uuid4(),
        agency_id=graph.broadcast.agency_id,
        client_group_id=graph.manual_group.id,
        submission_id=replacement.id,
        broadcast_recipient_id=original.id,
        original_recipient_name="Original snapshot",
        original_recipient_phone=original.phone_number,
        replaced_recipient_normalized_phone=original.normalized_phone_number,
        original_recipient_imported_fields={"Email": "old@example.test", "Zone Name": "Old zone"},
        resolution_type="replacement",
        status="active",
        excluded_submission_ids=[str(displaced.id)],
        created_at=NOW,
    )
    db_session.add(resolution)
    await db_session.flush()
    original.removed_at = NOW
    original.suppressed_by_roster_resolution_id = resolution.id
    await db_session.commit()
    rows = await exports._gather_export_rows(
        graph.request(
            ("replaced", original.id),
        ),
        graph.broadcast,
        graph.actor,
        db_session,
    )
    assert [row.submission.id for row in rows] == [displaced.id]
    assert rows[0].values["Broadcast contact name"] == "Original snapshot"
    assert rows[0].values["Replacement name"] == replacement.client_name
    assert rows[0].values["WhatsApp Email"] == "old@example.test"
    assert rows[0].broadcast_fields == resolution.original_recipient_imported_fields
    assert not db_session.new and not db_session.dirty


async def test_valid_override_wins_matching_and_changed_phone_invalidates_it(
    db_session: AsyncSession,
) -> None:
    graph = await persist_export_graph(db_session)
    passenger = graph.submissions[2]
    db_session.add(
        WhatsAppTravellerPhoneOverrideModel(
            id=uuid.uuid4(),
            agency_id=graph.broadcast.agency_id,
            broadcast_group_id=graph.broadcast.id,
            group_id=graph.manual_group.id,
            passenger_id=passenger.id,
            recipient_id=graph.recipients[0].id,
            source_phone_fingerprint=source_phone_fingerprint(passenger),
        )
    )
    await db_session.commit()
    body = graph.request(
        ("recipient", graph.recipients[0].id), ("recipient", graph.recipients[1].id)
    )
    rows = await exports._gather_export_rows(body, graph.broadcast, graph.actor, db_session)
    matched = [row for row in rows if row.submission and row.submission.id == passenger.id]
    assert len(matched) == 1
    assert matched[0].values["Delivery recipient ID"] == str(graph.recipients[0].id)
    assert matched[0].values["WhatsApp Email"] == "shared@example.test"
    passenger.client_phone = "+919444444444"
    await db_session.commit()
    rows = await exports._gather_export_rows(body, graph.broadcast, graph.actor, db_session)
    matched = [row for row in rows if row.submission and row.submission.id == passenger.id]
    assert len(matched) == 1
    assert matched[0].values["Delivery recipient ID"] == str(graph.recipients[1].id)
    assert matched[0].values["WhatsApp Email"] == "manual@example.test"


async def test_actual_source_and_entity_reads_chunk_1001_keys_without_reordering(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = await persist_export_graph(db_session)
    passengers = [
        PassportSubmissionModel(
            id=uuid.uuid4(),
            agency_id=graph.broadcast.agency_id,
            group_id=graph.source_group.id,
            client_name=f"Extra {index}",
            image_s3_key=f"synthetic/extra-{index}.jpg",
            status="staff_approved",
            confirmed_fields={"passport_number": f"EX{index}"},
        )
        for index in range(999)
    ]
    sources = [
        WhatsAppBroadcastSourceContactModel(
            id=uuid.uuid4(),
            agency_id=graph.broadcast.agency_id,
            broadcast_group_id=graph.broadcast.id,
            source_group_id=graph.source_group.id,
            source_submission_id=passenger.id,
            recipient_id=None,
            name=passenger.client_name,
        )
        for passenger in passengers
    ]
    await persist_graph(db_session, [*passengers, *sources])
    await db_session.commit()
    selected = list(reversed([*graph.submissions[:2], *passengers]))
    source_batches, entity_batches = [], []
    original_execute = db_session.execute

    async def execute(statement, *args, **kwargs):
        compiled = statement.compile()
        sql = str(compiled)
        pairs = [
            value
            for value in compiled.params.values()
            if isinstance(value, list) and value and isinstance(value[0], tuple)
        ]
        if pairs:
            if "FROM whatsapp_broadcast_source_contacts" in sql:
                source_batches.append(len(pairs[0]))
            elif "FROM passport_submissions" in sql:
                entity_batches.append(len(pairs[0]))
        return await original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", execute)
    rows = await exports._gather_export_rows(
        graph.request(
            *(("source_contact", item.id) for item in selected),
            view="travellers",
        ),
        graph.broadcast,
        graph.actor,
        db_session,
    )
    assert len(rows) == 1001
    assert [row.submission.id for row in rows] == [item.id for item in selected]
    assert source_batches == [1000, 1]
    assert entity_batches == [1000, 1]


async def test_expanded_alias_rows_enforce_limit_without_silent_truncation(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = await persist_export_graph(db_session)
    monkeypatch.setattr(export_projection, "MAX_EXPORT_ROWS", 2)
    # This case must exercise only durable sources, rather than the separate manual-group count limit.
    await db_session.execute(
        delete(ClientGroupWhatsAppBroadcastLinkModel).where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == graph.manual_group.id,
        )
    )
    await db_session.commit()
    with pytest.raises(WhatsAppExportTooLarge, match="20,000 rows"):
        await exports._gather_export_rows(
            graph.request(
                ("recipient", graph.recipients[0].id),
            ),
            graph.broadcast,
            graph.actor,
            db_session,
        )


async def test_missing_office_visible_passenger_rejects_whole_selected_source_snapshot(
    db_session: AsyncSession,
) -> None:
    graph = await persist_export_graph(db_session)
    graph.submissions[0].status = "pending"
    await db_session.commit()
    with pytest.raises(HTTPException) as error:
        await exports._gather_export_rows(
            graph.request(
                ("source_contact", graph.submissions[0].id),
                view="travellers",
            ),
            graph.broadcast,
            graph.actor,
            db_session,
        )
    assert error.value.status_code == 409
