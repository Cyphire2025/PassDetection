from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.group_submission_matching import (
    RecipientFieldSet,
    SubmissionMatchRow,
)
from app.domain.entities.entities import ClientGroup, GroupStatus
from app.presentation.api.v1.routes.passports import (
    _apply_pending_export_fields,
    _export_additional_values,
    _export_field_catalog,
    _export_whatsapp_contacts,
    _export_whatsapp_match_rows,
    _pending_recipient_export_rows,
    _recipient_export_value,
    _resolve_export_group_by,
)

NOW = datetime(2026, 7, 23, 12, tzinfo=UTC)


def _group() -> ClientGroup:
    return ClientGroup(
        id=uuid.uuid4(),
        name="Vietnam 2026",
        token=f"token-{uuid.uuid4()}",
        agency_id=uuid.uuid4(),
        status=GroupStatus.ACTIVE,
        created_by_user_id=uuid.uuid4(),
        created_at=NOW,
        destination="Vietnam",
        travel_date=date(2026, 8, 12),
        return_date=date(2026, 8, 15),
    )


def _match_row(
    *,
    status: str,
    recipient_fields: tuple[RecipientFieldSet, ...],
    phone: str = "+919876543210",
    recipient_names: tuple[str, ...] = ("Pending Passenger",),
) -> SubmissionMatchRow:
    recipient_ids = tuple(item.recipient_id for item in recipient_fields)
    return SubmissionMatchRow(
        status=status,
        match_basis=None,
        normalized_phone=phone,
        recipient_ids=recipient_ids,
        submission_ids=(),
        broadcast_ids=(uuid.uuid4(),),
        broadcast_names=("Vietnam recipients",),
        recipient_names=recipient_names,
        submission_names=(),
        updated_at=NOW,
        recipient_fields=recipient_fields,
    )


def test_recipient_export_value_leaves_conflicting_duplicate_fields_blank() -> None:
    first_id = uuid.UUID(int=1)
    second_id = uuid.UUID(int=2)
    row = _match_row(
        status="not_submitted",
        recipient_fields=(
            RecipientFieldSet(
                recipient_id=first_id,
                fields={"Zone Name": "Delhi"},
            ),
            RecipientFieldSet(
                recipient_id=second_id,
                fields={"zone_name": "Mumbai-1"},
            ),
        ),
    )

    assert _recipient_export_value(row, "zone_name", "zone") is None


def test_recipient_export_value_deduplicates_equivalent_values() -> None:
    row = _match_row(
        status="not_submitted",
        recipient_fields=(
            RecipientFieldSet(
                recipient_id=uuid.UUID(int=1),
                fields={"Zone Name": " Delhi "},
            ),
            RecipientFieldSet(
                recipient_id=uuid.UUID(int=2),
                fields={"zone_name": "delhi"},
            ),
        ),
    )

    value = _recipient_export_value(row, "zone_name", "zone")

    assert value is not None
    assert value.casefold() == "delhi"


def test_pending_mapper_includes_unresolved_recipients_and_excludes_submitted() -> None:
    group = _group()
    pending_fields = (
        RecipientFieldSet(
            recipient_id=uuid.uuid4(),
            fields={
                "Zone Name": "Mumbai-2",
                "Staff Code": "25290",
                "Email ID": "pending@example.test",
            },
        ),
    )
    rows = [
        _match_row(status="not_submitted", recipient_fields=pending_fields),
        _match_row(
            status="needs_review",
            recipient_fields=(
                RecipientFieldSet(
                    recipient_id=uuid.uuid4(),
                    fields={"Zone Name": "Delhi"},
                ),
            ),
            phone="+919123456789",
            recipient_names=("Review Passenger",),
        ),
        _match_row(
            status="submitted",
            recipient_fields=(
                RecipientFieldSet(
                    recipient_id=uuid.uuid4(),
                    fields={"Zone Name": "Kolkata"},
                ),
            ),
            phone="+919999999999",
            recipient_names=("Submitted Passenger",),
        ),
    ]

    pending = _pending_recipient_export_rows(group=group, rows=rows)

    assert len(pending) == 2
    assert [item["GIVEN NAME"] for item in pending] == [
        "PENDING PASSENGER",
        "REVIEW PASSENGER",
    ]
    assert pending[0]["Zone Name"] == "Mumbai-2"
    assert pending[0]["Staff Code"] == "25290"
    assert pending[0]["WhatsApp Email"] == "pending@example.test"
    assert pending[0]["WhatsApp Phone"] == "+919876543210"
    assert "Upload Email" not in pending[0]
    assert "Upload Phone" not in pending[0]
    assert pending[0]["Destination"] == "Vietnam"
    assert pending[0]["Travel/Departure Date"] == "2026-08-12"


def test_export_field_catalog_lists_only_selectable_whatsapp_columns() -> None:
    group = _group()
    current_question_id = uuid.uuid4()
    historical_question_id = uuid.uuid4()
    group.custom_questions = [
        {
            "id": str(current_question_id),
            "label": "T-shirt size",
            "options": ["S", "M"],
            "enabled": True,
        },
    ]
    row = _match_row(
        status="not_submitted",
        recipient_fields=(
            RecipientFieldSet(
                recipient_id=uuid.uuid4(),
                fields={
                    "Zone Name": "Delhi",
                    "Department": "Sales",
                    "Phone": "9876543210",
                    "Email ID": "sales@example.test",
                },
            ),
        ),
    )
    historical_submission = SimpleNamespace(
        custom_answers=[
            {
                "question_id": str(historical_question_id),
                "label": "Dinner session",
                "value": "Second",
            },
        ],
    )

    catalog = _export_field_catalog(group, [row], [historical_submission])
    by_key = {str(field["key"]): field for field in catalog}

    assert by_key["zone_name"]["selected_by_default"] is True
    assert by_key["whatsapp:department"]["label"] == "Department"
    assert f"custom:{current_question_id}" not in by_key
    assert f"custom:{historical_question_id}" not in by_key
    assert "whatsapp:phone" not in by_key
    assert "whatsapp:email_id" not in by_key


def test_dynamic_export_values_preserve_exact_whatsapp_matches() -> None:
    submission_id = uuid.uuid4()
    question_id = uuid.uuid4()
    row = SubmissionMatchRow(
        status="submitted",
        match_basis="phone",
        normalized_phone="+919876543210",
        recipient_ids=(uuid.uuid4(),),
        submission_ids=(submission_id,),
        broadcast_ids=(uuid.uuid4(),),
        broadcast_names=("Vietnam recipients",),
        recipient_names=("Submitted Passenger",),
        submission_names=("Submitted Passenger",),
        updated_at=NOW,
        recipient_fields=(
            RecipientFieldSet(
                recipient_id=uuid.uuid4(),
                fields={"Department": "Sales"},
            ),
        ),
    )
    submission = SimpleNamespace(
        id=submission_id,
        custom_answers=[
            {
                "question_id": str(question_id),
                "label": "T-shirt size",
                "value": "M",
            },
        ],
    )
    selected = [
        {
            "key": "whatsapp:department",
            "label": "Department",
            "source": "whatsapp",
            "selected_by_default": False,
        },
    ]

    values = _export_additional_values(
        [submission],
        {uuid.uuid4(): [row]},
        selected,
    )

    assert values[submission_id]["whatsapp:department"] == "Sales"
    assert f"custom:{question_id}" not in values[submission_id]

    pending_row = _match_row(
        status="not_submitted",
        recipient_fields=(
            RecipientFieldSet(
                recipient_id=uuid.uuid4(),
                fields={"Department": "Operations"},
            ),
        ),
    )
    pending = [{}]
    _apply_pending_export_fields(pending, [pending_row], selected)
    assert pending == [{"Department": "Operations"}]


def test_whatsapp_contacts_are_resolved_separately_from_upload_contacts() -> None:
    submission_id = uuid.uuid4()
    recipient_id = uuid.uuid4()
    row = SubmissionMatchRow(
        status="submitted",
        match_basis="phone",
        normalized_phone="+919876543210",
        recipient_ids=(recipient_id,),
        submission_ids=(submission_id,),
        broadcast_ids=(uuid.uuid4(),),
        broadcast_names=("Vietnam recipients",),
        recipient_names=("Submitted Passenger",),
        submission_names=("Submitted Passenger",),
        updated_at=NOW,
        recipient_fields=(
            RecipientFieldSet(
                recipient_id=recipient_id,
                fields={"Email ID": "whatsapp@example.test"},
            ),
        ),
    )

    contacts = _export_whatsapp_contacts(
        [SimpleNamespace(id=submission_id)],
        {uuid.uuid4(): [row]},
    )

    assert contacts == {
        submission_id: {
            "email": "whatsapp@example.test",
            "phone": "+919876543210",
        }
    }


def test_whatsapp_contacts_leave_ambiguous_values_blank() -> None:
    submission_id = uuid.uuid4()

    def _row(*, email: str, phone: str) -> SubmissionMatchRow:
        recipient_id = uuid.uuid4()
        return SubmissionMatchRow(
            status="submitted",
            match_basis="phone",
            normalized_phone=phone,
            recipient_ids=(recipient_id,),
            submission_ids=(submission_id,),
            broadcast_ids=(uuid.uuid4(),),
            broadcast_names=("Vietnam recipients",),
            recipient_names=("Submitted Passenger",),
            submission_names=("Submitted Passenger",),
            updated_at=NOW,
            recipient_fields=(
                RecipientFieldSet(
                    recipient_id=recipient_id,
                    fields={"Email ID": email},
                ),
            ),
        )

    contacts = _export_whatsapp_contacts(
        [SimpleNamespace(id=submission_id)],
        {
            uuid.uuid4(): [
                _row(
                    email="first@example.test",
                    phone="+919876543210",
                ),
                _row(
                    email="second@example.test",
                    phone="+919999999999",
                ),
            ]
        },
    )

    assert contacts == {submission_id: {"email": None, "phone": None}}


def test_export_grouping_distinguishes_default_from_explicit_none() -> None:
    selected = ["zone_name", "whatsapp:department"]

    assert _resolve_export_group_by(None, selected) == "zone_name"
    assert _resolve_export_group_by("none", selected) is None
    assert (
        _resolve_export_group_by("international_airport", selected)
        == "international_airport"
    )


@pytest.mark.asyncio
async def test_match_rows_load_pending_recipients_when_group_has_no_submissions() -> None:
    group = _group()
    broadcast_id = uuid.uuid4()
    recipient_id = uuid.uuid4()

    linked_result = MagicMock()
    linked_result.all.return_value = [
        (group.id, broadcast_id, "Vietnam recipients"),
    ]
    recipient_result = MagicMock()
    recipient_result.scalars.return_value.all.return_value = [
        SimpleNamespace(
            id=recipient_id,
            broadcast_group_id=broadcast_id,
            name="Pending Passenger",
            normalized_phone_number="+919876543210",
            created_at=NOW,
            imported_fields={
                "Zone Name": "Delhi",
                "Email": "pending@example.test",
            },
        )
    ]
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [linked_result, recipient_result]

    rows_by_group = await _export_whatsapp_match_rows(
        session,
        [],
        groups=[group],
    )

    assert session.execute.await_count == 2
    rows = rows_by_group[group.id]
    assert len(rows) == 1
    assert rows[0].status == "not_submitted"
    assert rows[0].recipient_ids == (recipient_id,)
    assert rows[0].recipient_fields[0].fields["Zone Name"] == "Delhi"
