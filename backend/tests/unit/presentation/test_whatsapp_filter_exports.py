"""Actual SQLite authorization/source selection and generated workbook contracts."""

from __future__ import annotations

import io
import uuid

import pytest
from fastapi import HTTPException
from openpyxl import load_workbook
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import UserRole
from app.infrastructure.export.whatsapp_filter_excel_exporter import (
    WhatsAppExportRow,
    WhatsAppExportTooLarge,
    build_whatsapp_filter_workbook,
)
from app.presentation.api.v1.routes import whatsapp_export_sources as export_sources
from app.presentation.api.v1.routes import whatsapp_exports as exports
from app.presentation.api.v1.schemas.whatsapp_export_schemas import WhatsAppFilterExportRequest
from tests.whatsapp_filter_export_fixtures import ExportGraph, persist_export_graph


@pytest.fixture
async def export_graph(db_session: AsyncSession) -> ExportGraph:
    return await persist_export_graph(db_session)


async def test_delivery_preserves_selected_order_aliases_sources_and_private_scalars(
    db_session: AsyncSession,
    export_graph: ExportGraph,
) -> None:
    graph = export_graph
    body = graph.request(
        ("rejected", graph.rejected.id),
        ("recipient", graph.recipients[1].id),
        ("recipient", graph.recipients[0].id),
    )
    rows = await exports._gather_export_rows(body, graph.broadcast, graph.actor, db_session)
    assert [row.values["Roster row ID"] for row in rows] == [
        str(graph.rejected.id),
        str(graph.recipients[1].id),
        str(graph.alias_id),
        str(graph.recipients[0].id),
        str(graph.recipients[0].id),
    ]
    assert [row.submission.id if row.submission else None for row in rows] == [
        None,
        graph.submissions[2].id,
        None,
        graph.submissions[0].id,
        graph.submissions[1].id,
    ]
    assert [row.values["WhatsApp Email"] for row in rows] == [
        "rejected@example.test",
        "manual@example.test",
        "alias@example.test",
        "shared@example.test",
        "shared@example.test",
    ]
    assert [row.values["Zone Name"] for row in rows] == [
        "Rejected zone",
        "Manual zone",
        "Alias zone",
        "Source zone",
        "Source zone",
    ]
    assert rows[0].values["Import row"] == 7
    assert rows[2].values["Shared delivery number"] is True
    assert rows[-1].values["Source issue"] == "shared_number"
    assert rows[-1].values["Welcome latest attempt status"] == "failed"
    assert rows[-1].values["Welcome status"] == "not_sent"
    assert all("PRIVATE_" not in repr(row) for row in rows)
    assert not db_session.new and not db_session.dirty and not db_session.deleted


async def test_travellers_keep_request_order_and_exact_source_identity(
    db_session: AsyncSession,
    export_graph: ExportGraph,
) -> None:
    graph = export_graph
    rows = await exports._gather_export_rows(
        graph.request(
            ("source_contact", graph.submissions[1].id),
            ("source_contact", graph.submissions[0].id),
            view="travellers",
        ),
        graph.broadcast,
        graph.actor,
        db_session,
    )
    assert [row.submission.id for row in rows] == [graph.submissions[1].id, graph.submissions[0].id]
    assert [row.values["Source contact name"] for row in rows] == ["Source 1", "Source 0"]
    assert all(row.values["Source import only"] is True for row in rows)
    assert all(row.values["Delivery recipient ID"] == str(graph.recipients[0].id) for row in rows)
    graph.sources[1].recipient_id = None
    await db_session.commit()
    rows = await exports._gather_export_rows(
        graph.request(
            ("source_contact", graph.submissions[1].id),
            view="travellers",
        ),
        graph.broadcast,
        graph.actor,
        db_session,
    )
    assert rows[0].values["Welcome status"] == "not_sent"
    assert "Delivery recipient ID" not in rows[0].values


async def test_unidentified_selection_uses_authorized_exact_passenger(
    db_session: AsyncSession,
    export_graph: ExportGraph,
) -> None:
    graph = export_graph
    rows = await exports._gather_export_rows(
        graph.request(
            ("unidentified", graph.submissions[3].id),
        ),
        graph.broadcast,
        graph.actor,
        db_session,
    )
    assert len(rows) == 1
    assert rows[0].submission.id == graph.submissions[3].id
    assert rows[0].values["Source contact name"] == "Unidentified person Person"
    assert rows[0].values["Zone Name"] == "Fallback 3"


@pytest.mark.parametrize(
    "changed", ["missing_source", "invisible_group", "inactive_source_group", "non_export_role"]
)
async def test_source_snapshot_fails_closed_instead_of_omitting_selected_rows(
    db_session: AsyncSession,
    export_graph: ExportGraph,
    changed: str,
) -> None:
    graph = export_graph
    selected_id = graph.submissions[0].id
    if changed == "missing_source":
        selected_id = uuid.uuid4()
    elif changed == "invisible_group":
        graph.actor.role = UserRole.AGENCY_STAFF
    elif changed == "non_export_role":
        graph.actor.role = UserRole.AGENCY_COORDINATOR
    else:
        graph.source_group.status = "archived"
    await db_session.commit()
    with pytest.raises(HTTPException) as error:
        await exports._gather_export_rows(
            graph.request(
                ("source_contact", selected_id),
                view="travellers",
            ),
            graph.broadcast,
            graph.actor,
            db_session,
        )
    assert error.value.status_code == 409


async def test_handler_keeps_tenant_boundary_and_safe_workbook_headers(
    db_session: AsyncSession,
    export_graph: ExportGraph,
) -> None:
    graph = export_graph
    body = graph.request(("source_contact", graph.submissions[0].id), view="travellers")
    broadcast_id, submission_id = graph.broadcast.id, graph.submissions[0].id
    response = await exports.export_broadcast_filter(broadcast_id, body, graph.actor, db_session)
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-type"] == exports._MIME
    assert response.headers["content-disposition"].startswith(
        'attachment; filename="broadcast-export.xlsx";'
    )
    assert "%E1%BB%87t" in response.headers["content-disposition"]
    assert not db_session.in_transaction()
    workbook = load_workbook(io.BytesIO(response.body))
    sheet = workbook.active
    assert sheet.max_row == 2
    header = [cell.value for cell in sheet[1]]
    values = dict(zip(header, [cell.value for cell in sheet[2]], strict=True))
    assert values["Roster row ID"] == str(submission_id)
    assert "PRIVATE_" not in repr(values)
    workbook.close()
    graph.actor.agency_id = uuid.uuid4()
    with pytest.raises(HTTPException) as error:
        await exports.export_broadcast_filter(broadcast_id, body, graph.actor, db_session)
    assert error.value.status_code == 404


def test_workbook_keeps_literal_formulas_identifiers_and_dates() -> None:
    workbook = load_workbook(
        io.BytesIO(
            build_whatsapp_filter_workbook(
                [
                    WhatsAppExportRow(
                        values={
                            "=literal header": "=literal value",
                            "Leading zero": "00123",
                            "DOB": "1990-01-02",
                        },
                        broadcast_fields={"External code": "+00123"},
                    ),
                ]
            )
        )
    )
    sheet = workbook.active
    by_header = {cell.value: sheet.cell(2, cell.column) for cell in sheet[1]}
    assert by_header["=literal header"].value == "=literal value"
    assert by_header["=literal header"].data_type == "s"
    assert by_header["Leading zero"].value == "00123"
    assert by_header["Broadcast import: External code"].value == "+00123"
    assert by_header["DOB"].value.year == 1990
    assert by_header["DOB"].number_format == "DD.MM.YYYY"
    workbook.close()


async def test_source_query_reads_only_one_overflow_row(
    db_session: AsyncSession,
    export_graph: ExportGraph,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = export_graph
    limits = []
    original_execute = db_session.execute

    async def execute(statement, *args, **kwargs):
        if "whatsapp_broadcast_source_contacts" in str(statement):
            limits.append(statement._limit_clause.value)
        return await original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", execute)
    monkeypatch.setattr(export_sources, "MAX_EXPORT_ROWS", 1)
    with pytest.raises(WhatsAppExportTooLarge, match="source travellers"):
        await exports._gather_export_rows(
            graph.request(
                ("source_contact", graph.submissions[0].id),
                ("source_contact", graph.submissions[1].id),
                view="travellers",
            ),
            graph.broadcast,
            graph.actor,
            db_session,
        )
    assert limits == [2]


@pytest.mark.parametrize(
    "data",
    [
        {"view": "delivery", "items": [{"kind": "source_contact", "id": str(uuid.uuid4())}]},
        {"view": "travellers", "items": [{"kind": "recipient", "id": str(uuid.uuid4())}]},
        {"view": "travellers", "items": [{"kind": "source_contact", "id": str(uuid.uuid4())}]},
        {"view": "delivery", "items": []},
    ],
)
def test_export_selection_contract_rejects_invalid_snapshot_shapes(data: dict) -> None:
    with pytest.raises(ValidationError):
        WhatsAppFilterExportRequest.model_validate(data)


def test_duplicate_export_identities_are_rejected() -> None:
    item = {"kind": "recipient", "id": str(uuid.uuid4())}
    with pytest.raises(ValidationError, match="unique"):
        WhatsAppFilterExportRequest.model_validate({"view": "delivery", "items": [item, item]})


@pytest.mark.parametrize(
    ("fields", "email"),
    [
        ({"Email": " One@Example.test ", "E-mail": "one@example.test"}, "One@Example.test"),
        ({"Email": "one@example.test", "E-mail": "two@example.test"}, None),
        ({"Email": "N/A", "Other": "ignored@example.test"}, None),
    ],
)
def test_contact_projection_preserves_unambiguous_email_only(
    fields: dict, email: str | None
) -> None:
    assert exports._broadcast_import_contact_values(fields)["WhatsApp Email"] == email


async def test_handler_maps_bounded_overflow_to_bad_request(
    db_session: AsyncSession,
    export_graph: ExportGraph,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = export_graph
    monkeypatch.setattr(export_sources, "MAX_EXPORT_ROWS", 1)
    with pytest.raises(HTTPException) as error:
        await exports.export_broadcast_filter(
            graph.broadcast.id,
            graph.request(
                ("source_contact", graph.submissions[0].id),
                ("source_contact", graph.submissions[1].id),
                view="travellers",
            ),
            graph.actor,
            db_session,
        )
    assert error.value.status_code == 400
    assert "source travellers" in error.value.detail


async def test_export_without_message_filter_keeps_requested_row_and_detached_worker(
    db_session: AsyncSession,
    export_graph: ExportGraph,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    graph = export_graph
    original_builder = exports.build_whatsapp_filter_workbook
    event_loop_thread = threading.get_ident()
    calls = []

    def builder(rows):
        assert threading.get_ident() != event_loop_thread
        assert not db_session.in_transaction()
        assert all("Selected message status" not in row.values for row in rows)
        calls.append(len(rows))
        return original_builder(rows)

    monkeypatch.setattr(exports, "build_whatsapp_filter_workbook", builder)
    body = graph.request(("rejected", graph.rejected.id)).model_copy(update={"message_type": None})
    response = await exports.export_broadcast_filter(
        graph.broadcast.id, body, graph.actor, db_session
    )
    assert response.status_code == 200
    assert calls == [1]
