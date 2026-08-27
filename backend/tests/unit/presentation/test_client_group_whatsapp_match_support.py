"""Characterization tests for extracted WhatsApp roster response assembly."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.application.use_cases.whatsapp.group_submission_matching import (
    SubmissionMatchSummary,
)
from app.infrastructure.database.models import (
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    WhatsAppBroadcastRecipientModel,
)
from app.presentation.api.v1.routes.client_group_whatsapp_match_support import (
    build_whatsapp_matches_response,
    include_active_resolution_rows,
    stored_uuid_list,
)


def test_manual_roster_resolution_rows_preserve_recovery_context_and_pagination() -> None:
    now = datetime.now(tz=UTC)
    group_id = uuid.uuid4()
    broadcast_id = uuid.uuid4()
    recipient_id = uuid.uuid4()
    submission_id = uuid.uuid4()
    replacement_id = uuid.uuid4()
    rejection_id = uuid.uuid4()

    submission = PassportSubmissionModel(
        id=submission_id,
        client_name="Passenger One",
        client_phone="+919999999999",
        client_email=None,
        confirmed_fields={},
        extracted_fields={},
        staff_metadata={},
        departure_city=None,
        nearest_domestic_airport=None,
        family_relation=None,
        family_head_name=None,
        updated_at=now,
    )
    recipient = WhatsAppBroadcastRecipientModel(
        id=recipient_id,
        broadcast_group_id=broadcast_id,
        name="Passenger One",
        normalized_phone_number="+919999999999",
        imported_fields={"zone": "A"},
    )
    replacement = PassportRosterResolutionModel(
        id=replacement_id,
        submission_id=submission_id,
        resolution_type="replacement",
        suppressed_recipient_ids=[str(recipient_id), str(recipient_id), "invalid"],
        broadcast_recipient_id=recipient_id,
        created_at=now + timedelta(seconds=1),
    )
    rejection = PassportRosterResolutionModel(
        id=rejection_id,
        submission_id=submission_id,
        resolution_type="rejected",
        suppressed_recipient_ids=[],
        broadcast_recipient_id=None,
        created_at=now + timedelta(seconds=2),
    )

    rows = include_active_resolution_rows(
        [],
        active_resolutions=[replacement, rejection],
        submissions_by_id={submission_id: submission},
        recipients_by_id={recipient_id: recipient},
        linked_broadcasts={broadcast_id: "Arrival List"},
    )

    assert [row.status for row in rows] == ["replacement", "rejected_upload"]
    assert rows[0].recipient_ids == (recipient_id,)
    assert rows[0].broadcast_names == ("Arrival List",)
    assert rows[0].recipient_fields[0].fields == {"zone": "A"}
    assert rows[1].normalized_phone == "+919999999999"
    assert stored_uuid_list([str(recipient_id), str(recipient_id), "invalid"]) == [recipient_id]

    response = build_whatsapp_matches_response(
        client_group_id=group_id,
        selected_broadcast_id=None,
        linked_broadcast_count=1,
        counts=SubmissionMatchSummary(
            total_recipients=1,
            submitted_count=0,
            not_submitted_count=0,
            multiple_submission_count=0,
            matched_submission_count=0,
            replacement_count=1,
            rejected_upload_count=1,
        ),
        page_rows=rows,
        submissions_by_id={submission_id: submission},
        total=2,
        page=1,
        page_size=1,
    )
    assert response.total_pages == 2
    assert [item.status for item in response.matches] == [
        "replacement",
        "rejected_upload",
    ]
    assert response.matches[0].submission_details[0].name == "Passenger One"
