"""Count real comparison work and retain fresh source/recipient reads."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.export.whatsapp_filter_excel_exporter import WhatsAppExportTooLarge
from app.infrastructure.repositories import passport_whatsapp_matching_repository as matching
from app.presentation.api.v1.routes import whatsapp_export_hydration as hydration
from app.presentation.api.v1.routes import whatsapp_export_matching as export_matching
from app.presentation.api.v1.routes import whatsapp_export_selection as selection
from app.presentation.api.v1.routes import whatsapp_exports as exports
from tests.whatsapp_filter_export_fixtures import NOW, persist_export_graph


@pytest.mark.parametrize("change_source", [False, True])
async def test_comparison_work_and_current_source_change_are_observable(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    change_source: bool,
) -> None:
    graph = await persist_export_graph(db_session)
    comparisons = []
    original_compare = matching.compare_group_submissions
    original_roster = selection.get_broadcast_recipient_roster

    def compare(recipients, submissions):
        comparisons.append(
            (
                tuple(row.id for row in submissions),
                tuple(dict(row.staff_metadata) for row in submissions),
            )
        )
        return original_compare(recipients, submissions)

    async def roster(*args, **kwargs):
        value = await original_roster(*args, **kwargs)
        if change_source:
            graph.submissions[2].staff_metadata = {"staff_code": "NO-LONGER-MATCHED"}
            await db_session.commit()
        return value

    monkeypatch.setattr(matching, "compare_group_submissions", compare)
    monkeypatch.setattr(selection, "get_broadcast_recipient_roster", roster)
    rows = await exports._gather_export_rows(
        graph.request(
            ("recipient", graph.recipients[1].id),
        ),
        graph.broadcast,
        graph.actor,
        db_session,
    )
    assert (
        len(comparisons) == 3
    )  # two visible groups in roster, then one manual group in enrichment
    manual = [value for value in comparisons if graph.submissions[2].id in value[0]]
    assert len(manual) == 2
    assert (manual[0] == manual[1]) is (not change_source)
    assert len(rows) == 1
    assert (rows[0].submission is None) is change_source
    if not change_source:
        assert rows[0].submission.id == graph.submissions[2].id


@pytest.mark.parametrize("change", ["removed", "missing"])
async def test_recipient_hydration_revalidates_after_roster_read(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    graph = await persist_export_graph(db_session)
    original_roster = selection.get_broadcast_recipient_roster

    async def roster(*args, **kwargs):
        value = await original_roster(*args, **kwargs)
        if change == "removed":
            graph.recipients[1].removed_at = NOW
        else:
            await db_session.delete(graph.recipients[1])
        await db_session.commit()
        return value

    selected_id = graph.recipients[1].id
    monkeypatch.setattr(selection, "get_broadcast_recipient_roster", roster)
    with pytest.raises(HTTPException) as error:
        await exports._gather_export_rows(
            graph.request(
                ("recipient", selected_id),
            ),
            graph.broadcast,
            graph.actor,
            db_session,
        )
    assert error.value.status_code == 409


async def test_manual_group_population_budget_precedes_comparison(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = await persist_export_graph(db_session)
    monkeypatch.setattr(export_matching, "MAX_EXPORT_ROWS", 1)
    with pytest.raises(WhatsAppExportTooLarge, match="linked groups"):
        await exports._gather_export_rows(
            graph.request(
                ("recipient", graph.recipients[1].id),
            ),
            graph.broadcast,
            graph.actor,
            db_session,
        )


async def test_required_source_budget_includes_valid_correction_expansion(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.infrastructure.database.models import WhatsAppTravellerPhoneOverrideModel
    from app.infrastructure.whatsapp.phone_overrides import source_phone_fingerprint

    graph = await persist_export_graph(db_session)
    passenger = graph.submissions[2]
    db_session.add(
        WhatsAppTravellerPhoneOverrideModel(
            agency_id=graph.broadcast.agency_id,
            broadcast_group_id=graph.broadcast.id,
            group_id=graph.manual_group.id,
            passenger_id=passenger.id,
            recipient_id=graph.recipients[0].id,
            source_phone_fingerprint=source_phone_fingerprint(passenger),
        )
    )
    await db_session.commit()
    monkeypatch.setattr(hydration, "MAX_EXPORT_ROWS", 2)
    with pytest.raises(WhatsAppExportTooLarge, match="source travellers"):
        await exports._gather_export_rows(
            graph.request(
                ("recipient", graph.recipients[0].id),
            ),
            graph.broadcast,
            graph.actor,
            db_session,
        )
