"""Field projection preserves ambiguity while visiting each imported header once."""

from __future__ import annotations

import sys
import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.application.use_cases.whatsapp.group_submission_matching import (
    RecipientFieldSet,
    SubmissionMatchRow,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    PassportSubmissionModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.rooming import priority_fields
from tests.unit.infrastructure.test_rooming_priority_fields import (
    _RowsResult,
    _ScalarResult,
    _Session,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("selected_count", [6, None])
async def test_context_projects_selected_or_complete_catalog_without_repeated_header_work(
    monkeypatch,
    selected_count,
):
    agency_id, group_id, broadcast_id, passenger_id = (uuid.uuid4() for _ in range(4))
    fields = {f"Grouping Column {index}": f"Value {index}" for index in range(64)}
    second = {"Grouping Column 1": "conflicting value", "Grouping Column 2": " VALUE 2 "}
    group = ClientGroupModel(
        id=group_id, agency_id=agency_id, name="Synthetic grouping", token="synthetic-token"
    )
    passenger = PassportSubmissionModel(
        id=passenger_id,
        agency_id=agency_id,
        group_id=group_id,
        client_name="Synthetic passenger",
        image_s3_key="synthetic/image.jpg",
        status="confirmed",
        submission_mode="single",
        staff_metadata={},
    )
    recipients = [
        WhatsAppBroadcastRecipientModel(
            id=uuid.UUID(int=index),
            agency_id=agency_id,
            broadcast_group_id=broadcast_id,
            normalized_phone_number="+919999999999",
            imported_fields=values,
        )
        for index, values in [(1, fields), (2, second)]
    ]
    row = SubmissionMatchRow(
        status="submitted",
        match_basis="selected_fields",
        normalized_phone=None,
        recipient_ids=tuple(item.id for item in recipients),
        submission_ids=(passenger_id,),
        broadcast_ids=(broadcast_id,),
        broadcast_names=("Synthetic roster",),
        recipient_names=(),
        submission_names=("Synthetic passenger",),
        updated_at=datetime.now(tz=UTC),
        recipient_fields=tuple(
            RecipientFieldSet(item.id, dict(item.imported_fields)) for item in recipients
        ),
    )
    # Matching/tenant query policy has its own regression suites. This test
    # isolates the field projection work after an already-authorized match row.
    monkeypatch.setattr(priority_fields, "recipient_comparison_from_model", lambda *_args: object())
    monkeypatch.setattr(
        priority_fields, "submission_comparison_from_model", lambda *_args: object()
    )
    monkeypatch.setattr(priority_fields, "compare_group_submissions", lambda *_args: ([row], None))
    session = _Session(
        [_RowsResult([(broadcast_id, "Synthetic roster", None)]), _ScalarResult(recipients)]
    )
    selected = (
        [f"whatsapp:grouping_column_{index}" for index in range(selected_count)]
        if selected_count
        else None
    )
    normalized_code = priority_fields.normalize_imported_field_key.__code__
    visits = 0

    def count_headers(frame, event, _argument):
        nonlocal visits
        if event == "call" and frame.f_code is normalized_code:
            visits += 1

    previous = sys.getprofile()
    sys.setprofile(count_headers)
    try:
        context = await priority_fields.build_rooming_priority_context(
            session,
            group=group,
            passengers=[passenger],
            requested_keys=selected,
        )
    finally:
        sys.setprofile(previous)

    count = selected_count or 64
    assert {
        key: value
        for key, value in context.values_by_passenger[passenger_id].items()
        if key.startswith("whatsapp:")
    } == {
        f"whatsapp:grouping_column_{index}": None if index == 1 else f"Value {index}"
        for index in range(count)
    }
    assert visits <= 4 * (len(fields) + len(second)), (
        f"{visits} header normalizations for 66 source fields; "
        "selected-key count must not multiply projection work"
    )
    assert priority_fields._recipient_value(row, "grouping_column_1") is None
    assert priority_fields._recipient_value(row, "grouping_column_2") == "Value 2"
    assert priority_fields._recipient_value(row, "missing_column") is None
    replay = replace(
        row,
        recipient_fields=(
            RecipientFieldSet(
                uuid.UUID(int=3),
                {"Grouping Column 1": "Value 1", "Grouping Column 3": "N/A"},
            ),
            *reversed(row.recipient_fields),
        ),
    )
    # A later matching literal cannot undo earlier conflicting values. Empty
    # markers cannot override a value; input order cannot change UUID precedence.
    assert priority_fields._recipient_values(
        replay, ["grouping_column_1", "grouping_column_2", "grouping_column_3"]
    ) == {
        "grouping_column_1": None,
        "grouping_column_2": "Value 2",
        "grouping_column_3": "Value 3",
    }
