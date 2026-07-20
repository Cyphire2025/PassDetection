from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.application.use_cases.whatsapp.group_submission_matching import (
    RecipientForComparison,
    SubmissionForComparison,
    compare_group_submissions,
    filter_and_sort_match_rows,
    summarize_match_rows,
)

NOW = datetime(2026, 7, 20, 12, tzinfo=UTC)


def _recipient(
    phone: str,
    *,
    broadcast_id: uuid.UUID | None = None,
    broadcast_name: str = "List",
    name: str = "Passenger",
) -> RecipientForComparison:
    return RecipientForComparison(
        id=uuid.uuid4(),
        broadcast_id=broadcast_id or uuid.uuid4(),
        broadcast_name=broadcast_name,
        name=name,
        phone=phone,
        updated_at=NOW,
    )


def _submission(
    *,
    client_phone: str | None = None,
    family_head_phone: str | None = None,
    name: str = "Passenger",
) -> SubmissionForComparison:
    return SubmissionForComparison(
        id=uuid.uuid4(),
        name=name,
        client_phone=client_phone,
        family_head_phone=family_head_phone,
        updated_at=NOW + timedelta(minutes=1),
    )


def test_same_phone_across_broadcasts_is_one_logical_submitted_recipient() -> None:
    first = _recipient(
        "+919876543210", broadcast_name="North"
    )
    second = _recipient(
        "9876543210", broadcast_name="South"
    )
    submission = _submission(client_phone="9876543210")

    rows, counts = compare_group_submissions(
        [first, second], [submission]
    )

    assert len(rows) == 1
    assert rows[0].status == "submitted"
    assert set(rows[0].recipient_ids) == {first.id, second.id}
    assert set(rows[0].broadcast_names) == {"North", "South"}
    assert rows[0].submission_ids == (submission.id,)
    assert counts.total_recipients == 1
    assert counts.submitted_count == 1
    assert counts.not_submitted_count == 0


def test_family_head_phone_matches_and_multiple_submissions_stay_visible() -> None:
    recipient = _recipient("+919999888877")
    member = _submission(family_head_phone="9999888877", name="Member")
    head = _submission(client_phone="+919999888877", name="Head")

    rows, counts = compare_group_submissions(
        [recipient], [member, head]
    )

    assert rows[0].status == "multiple_submissions"
    assert set(rows[0].submission_ids) == {member.id, head.id}
    assert counts.submitted_count == 1
    assert counts.multiple_submission_count == 1
    assert counts.matched_submission_count == 2


def test_names_are_diagnostic_only_and_never_auto_match() -> None:
    recipient = _recipient("9876543210", name="Same Name")
    submission = _submission(
        client_phone="9123456789", name="Same Name"
    )

    rows, counts = compare_group_submissions(
        [recipient], [submission]
    )

    assert rows[0].status == "not_submitted"
    assert rows[0].match_basis is None
    assert rows[0].submission_ids == ()
    assert counts.not_submitted_count == 1


def test_match_filter_and_sort_use_final_status_vocabulary() -> None:
    submitted_recipient = _recipient(
        "9876543210", name="Zulu"
    )
    missing_recipient = _recipient(
        "9123456789", name="Alpha"
    )
    rows, _ = compare_group_submissions(
        [submitted_recipient, missing_recipient],
        [_submission(client_phone="9876543210")],
    )

    filtered = filter_and_sort_match_rows(
        rows,
        status="not_submitted",
        sort_by="name",
        sort_order="asc",
    )

    assert [row.status for row in filtered] == ["not_submitted"]
    assert filtered[0].recipient_names == ("Alpha",)


def test_broadcast_subset_keeps_unique_phone_and_full_provenance() -> None:
    north_id = uuid.uuid4()
    south_id = uuid.uuid4()
    shared_north = _recipient(
        "9876543210",
        broadcast_id=north_id,
        broadcast_name="North",
    )
    shared_south = _recipient(
        "+919876543210",
        broadcast_id=south_id,
        broadcast_name="South",
    )
    south_only = _recipient(
        "9123456789",
        broadcast_id=south_id,
        broadcast_name="South",
    )
    submission = _submission(client_phone="9876543210")

    rows, _ = compare_group_submissions(
        [shared_north, shared_south, south_only],
        [submission],
    )
    north_rows = [
        row for row in rows if north_id in row.broadcast_ids
    ]
    counts = summarize_match_rows(north_rows)

    assert len(north_rows) == 1
    assert set(north_rows[0].broadcast_ids) == {north_id, south_id}
    assert set(north_rows[0].broadcast_names) == {"North", "South"}
    assert counts.total_recipients == 1
    assert counts.submitted_count == 1
    assert counts.matched_submission_count == 1
