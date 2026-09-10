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
    imported_fields: dict[str, str] | None = None,
    matching_field_keys: tuple[str, ...] | None = None,
) -> RecipientForComparison:
    return RecipientForComparison(
        id=uuid.uuid4(),
        broadcast_id=broadcast_id or uuid.uuid4(),
        broadcast_name=broadcast_name,
        name=name,
        phone=phone,
        updated_at=NOW,
        imported_fields=imported_fields or {},
        matching_field_keys=matching_field_keys,
    )


def _submission(
    *,
    client_phone: str | None = None,
    family_head_phone: str | None = None,
    name: str = "Passenger",
    client_email: str | None = None,
    family_head_email: str | None = None,
    confirmed_fields: dict[str, object] | None = None,
    extracted_fields: dict[str, object] | None = None,
    staff_metadata: dict[str, object] | None = None,
    custom_answers: tuple[dict[str, object], ...] = (),
    custom_detail_answers: tuple[dict[str, object], ...] = (),
) -> SubmissionForComparison:
    return SubmissionForComparison(
        id=uuid.uuid4(),
        name=name,
        client_phone=client_phone,
        family_head_phone=family_head_phone,
        updated_at=NOW + timedelta(minutes=1),
        client_email=client_email,
        family_head_email=family_head_email,
        confirmed_fields=confirmed_fields or {},
        extracted_fields=extracted_fields or {},
        staff_metadata=staff_metadata or {},
        custom_answers=custom_answers,
        custom_detail_answers=custom_detail_answers,
    )


def test_same_phone_across_broadcasts_is_one_logical_submitted_recipient() -> None:
    first = _recipient("+919876543210", broadcast_name="North")
    second = _recipient("9876543210", broadcast_name="South")
    submission = _submission(client_phone="9876543210")

    rows, counts = compare_group_submissions([first, second], [submission])

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

    rows, counts = compare_group_submissions([recipient], [member, head])

    assert rows[0].status == "multiple_submissions"
    assert set(rows[0].submission_ids) == {member.id, head.id}
    assert counts.submitted_count == 1
    assert counts.multiple_submission_count == 1
    assert counts.matched_submission_count == 2


def test_name_only_is_reviewable_and_never_auto_matches() -> None:
    recipient = _recipient("9876543210", name="Same Name")
    submission = _submission(client_phone="9123456789", name="Same Name")

    rows, counts = compare_group_submissions([recipient], [submission])

    assert rows[0].status == "needs_review"
    assert rows[0].match_basis == "entered_name"
    assert rows[0].submission_ids == ()
    assert rows[0].candidate_submission_ids == (submission.id,)
    assert counts.needs_review_count == 1
    assert counts.matched_submission_count == 0


def test_match_filter_and_sort_use_final_status_vocabulary() -> None:
    submitted_recipient = _recipient("9876543210", name="Zulu")
    missing_recipient = _recipient("9123456789", name="Alpha")
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
    north_rows = [row for row in rows if north_id in row.broadcast_ids]
    counts = summarize_match_rows(north_rows)

    assert len(north_rows) == 1
    assert set(north_rows[0].broadcast_ids) == {north_id, south_id}
    assert set(north_rows[0].broadcast_names) == {"North", "South"}
    assert counts.total_recipients == 1
    assert counts.submitted_count == 1
    assert counts.matched_submission_count == 1


def test_exact_email_matches_when_submitted_phone_changed() -> None:
    recipient = _recipient(
        "9876543210",
        name="Irfan Khan",
        imported_fields={"email": "IRFAN@example.com"},
    )
    submission = _submission(
        name="Irfan Khan",
        client_phone="9123456789",
        client_email="irfan@example.com",
    )

    rows, counts = compare_group_submissions([recipient], [submission])

    assert rows[0].status == "submitted"
    assert rows[0].submission_ids == (submission.id,)
    assert "email" in (rows[0].match_basis or "")
    assert counts.matched_submission_count == 1


def test_exact_passport_or_staff_code_matches_without_contact_match() -> None:
    passport_recipient = _recipient(
        "9876543210",
        imported_fields={"passport_number": " Z-123 456 "},
    )
    staff_recipient = _recipient(
        "9123456789",
        imported_fields={"staff_code": " GC-0042 "},
    )
    passport_submission = _submission(
        client_phone="9000000001",
        confirmed_fields={"passport_number": "Z123456"},
    )
    staff_submission = _submission(
        client_phone="9000000002",
        staff_metadata={"staff_code": "GC0042"},
    )

    rows, counts = compare_group_submissions(
        [passport_recipient, staff_recipient],
        [passport_submission, staff_submission],
    )

    submitted = {row.normalized_phone: row for row in rows if row.recipient_ids}
    assert submitted["+919876543210"].submission_ids == (passport_submission.id,)
    assert submitted["+919123456789"].submission_ids == (staff_submission.id,)
    assert counts.matched_submission_count == 2


def test_alternate_identifier_from_duplicate_phone_row_is_matchable() -> None:
    recipient = _recipient(
        "9876543210",
        imported_fields={
            "passport_number": "Z1111111",
            "passport_number_2": "Z2222222",
            "duplicate_conflicting_fields": "passport_number",
        },
    )
    submission = _submission(
        client_phone="9000000000",
        confirmed_fields={"passport_number": "Z2222222"},
    )

    rows, counts = compare_group_submissions([recipient], [submission])

    assert rows[0].status == "submitted"
    assert "passport_number" in (rows[0].match_basis or "")
    assert counts.matched_submission_count == 1


def test_unique_entered_and_passport_name_compound_can_match() -> None:
    recipient = _recipient(
        "9876543210",
        name="Abhishek Sharma",
    )
    submission = _submission(
        name="Abhishek Sharma",
        client_phone="9000000000",
        confirmed_fields={
            "given_names": "Abhishek",
            "surname": "Sharma",
        },
    )

    rows, counts = compare_group_submissions([recipient], [submission])

    assert rows[0].status == "submitted"
    assert rows[0].match_basis == "entered_name+passport_name"
    assert counts.submitted_count == 1


def test_duplicate_name_is_disambiguated_by_phone_without_false_review() -> None:
    matching = _recipient("9876543210", name="Irfan Khan")
    same_name = _recipient("9123456789", name="Irfan Khan")
    submission = _submission(
        name="Irfan Khan",
        client_phone="9876543210",
        confirmed_fields={"given_names": "Irfan", "surname": "Khan"},
    )

    rows, counts = compare_group_submissions(
        [matching, same_name],
        [submission],
    )
    by_recipient = {row.recipient_ids[0]: row for row in rows if row.recipient_ids}

    assert by_recipient[matching.id].status == "submitted"
    assert by_recipient[same_name.id].status == "not_submitted"
    assert counts.needs_review_count == 0


def test_cross_recipient_strong_identifier_conflict_requires_review() -> None:
    phone_owner = _recipient(
        "9876543210",
        name="Alpha Person",
    )
    email_owner = _recipient(
        "9123456789",
        name="Beta Person",
        imported_fields={"email": "shared@example.com"},
    )
    submission = _submission(
        name="Alpha Person",
        client_phone="9876543210",
        client_email="shared@example.com",
    )

    rows, counts = compare_group_submissions(
        [phone_owner, email_owner],
        [submission],
    )
    recipient_rows = [row for row in rows if row.recipient_ids]

    assert {row.status for row in recipient_rows} == {"needs_review"}
    assert all(row.candidate_submission_ids == (submission.id,) for row in recipient_rows)
    assert counts.matched_submission_count == 0
    assert counts.needs_review_submission_count == 1


def test_duplicate_name_without_identifiers_is_ambiguous() -> None:
    first = _recipient("9876543210", name="Irfan Khan")
    second = _recipient("9123456789", name="Irfan Khan")
    submission = _submission(
        name="Irfan Khan",
        client_phone="9000000000",
        confirmed_fields={"given_names": "Irfan", "surname": "Khan"},
    )

    rows, counts = compare_group_submissions(
        [first, second],
        [submission],
    )

    assert all(row.status == "needs_review" for row in rows if row.recipient_ids)
    assert counts.needs_review_count == 2
    assert counts.needs_review_submission_count == 1


def test_submission_without_any_candidate_is_explicitly_visible() -> None:
    recipient = _recipient("9876543210", name="Expected Person")
    unknown = _submission(
        name="Unknown Person",
        client_phone="9000000000",
    )

    rows, counts = compare_group_submissions([recipient], [unknown])

    assert {row.status for row in rows} == {
        "not_submitted",
        "unmatched_submission",
    }
    unmatched = next(row for row in rows if row.status == "unmatched_submission")
    assert unmatched.submission_ids == (unknown.id,)
    assert counts.unmatched_submission_count == 1


def test_selected_producer_code_matches_with_or_semantics_despite_other_mismatches() -> None:
    recipient = _recipient(
        "9876543210",
        name="Roster Person",
        imported_fields={
            "name": "Roster Person",
            "phone_number": "9876543210",
            "producer_code": "PROD-0042",
        },
        matching_field_keys=("name", "phone_number", "producer_code"),
    )
    submission = _submission(
        name="Different Person",
        client_phone="9123456789",
        custom_detail_answers=({"label": "Producer Code", "value": "PROD0042"},),
    )

    rows, counts = compare_group_submissions([recipient], [submission])

    assert rows[0].status == "submitted"
    assert rows[0].submission_ids == (submission.id,)
    assert rows[0].match_basis == "agent_employee_code"
    assert rows[0].normalized_phone == "+919876543210"
    assert counts.matched_submission_count == 1


def test_explicit_matching_policy_does_not_fall_back_to_legacy_phone() -> None:
    recipient = _recipient(
        "9876543210",
        imported_fields={"producer_code": "PROD-0042"},
        matching_field_keys=("producer_code",),
    )
    submission = _submission(
        client_phone="9876543210",
        custom_detail_answers=({"label": "Producer Code", "value": "PROD-9999"},),
    )

    rows, counts = compare_group_submissions([recipient], [submission])

    assert next(row for row in rows if row.recipient_ids).status == "not_submitted"
    assert counts.submitted_count == 0


def test_selected_low_cardinality_collision_requires_review() -> None:
    recipients = [
        _recipient(
            f"98765432{index:02d}",
            name=f"Roster {index}",
            imported_fields={"location": "New Delhi"},
            matching_field_keys=("location",),
        )
        for index in range(2)
    ]
    submissions = [
        _submission(
            name=f"Submitted {index}",
            client_phone=f"91234567{index:02d}",
            custom_detail_answers=({"label": "Location", "value": "New   Delhi"},),
        )
        for index in range(2)
    ]

    rows, counts = compare_group_submissions(recipients, submissions)

    assert all(row.status == "needs_review" for row in rows if row.recipient_ids)
    assert counts.submitted_count == 0
    assert counts.needs_review_count == 2


def test_confirmed_value_supersedes_stale_extracted_value_for_selected_field() -> None:
    old_recipient = _recipient(
        "9876543210",
        imported_fields={"passport_number": "OLD-123"},
        matching_field_keys=("passport_number",),
    )
    corrected_recipient = _recipient(
        "9123456789",
        imported_fields={"passport_number": "NEW-456"},
        matching_field_keys=("passport_number",),
    )
    submission = _submission(
        extracted_fields={"passport_number": "OLD-123"},
        confirmed_fields={"passport_number": "NEW-456"},
    )

    rows, counts = compare_group_submissions(
        [old_recipient, corrected_recipient],
        [submission],
    )
    by_recipient = {row.recipient_ids[0]: row for row in rows if row.recipient_ids}

    assert by_recipient[old_recipient.id].status == "not_submitted"
    assert by_recipient[corrected_recipient.id].status == "submitted"
    assert counts.matched_submission_count == 1


def test_explicit_empty_matching_policy_fails_closed() -> None:
    recipient = _recipient(
        "9876543210",
        name="Same Person",
        matching_field_keys=(),
    )
    submission = _submission(
        client_phone="9876543210",
        name="Same Person",
    )

    rows, counts = compare_group_submissions([recipient], [submission])
    recipient_row = next(row for row in rows if row.recipient_ids)

    assert recipient_row.status == "not_submitted"
    assert recipient_row.normalized_phone == "+919876543210"
    assert counts.matched_submission_count == 0
    assert counts.unmatched_submission_count == 1


def test_selected_legacy_named_fields_keep_collision_safety() -> None:
    cases = (
        (
            "email",
            "shared@example.com",
            {"client_email": "shared@example.com"},
        ),
        (
            "passport_number",
            "P1234567",
            {"confirmed_fields": {"passport_number": "P1234567"}},
        ),
        (
            "staff_code",
            "EMP-0042",
            {"confirmed_fields": {"staff_code": "EMP-0042"}},
        ),
    )

    for field_key, field_value, submission_kwargs in cases:
        recipient = _recipient(
            "9876543210",
            imported_fields={field_key: field_value},
            matching_field_keys=(field_key,),
        )
        first = _submission(name="First", **submission_kwargs)
        second = _submission(name="Second", **submission_kwargs)

        rows, counts = compare_group_submissions([recipient], [first, second])
        recipient_row = next(row for row in rows if row.recipient_ids)

        assert recipient_row.status == "needs_review", field_key
        assert recipient_row.submission_ids == (), field_key
        assert set(recipient_row.candidate_submission_ids) == {
            first.id,
            second.id,
        }, field_key
        assert counts.matched_submission_count == 0, field_key


def test_selected_field_prefers_unique_shared_value_over_lexical_first() -> None:
    recipient = _recipient(
        "9876543210",
        name="A Common",
        imported_fields={"name": "Z Unique"},
        matching_field_keys=("name",),
    )
    uniquely_identified = _submission(
        name="A Common",
        custom_answers=({"label": "Name", "value": "Z Unique"},),
    )
    shared_only = _submission(name="A Common")

    rows, counts = compare_group_submissions(
        [recipient],
        [uniquely_identified, shared_only],
    )
    recipient_row = next(row for row in rows if row.recipient_ids)

    assert recipient_row.status == "submitted"
    assert recipient_row.submission_ids == (uniquely_identified.id,)
    assert recipient_row.match_evidence[0].recipient_value == "z unique"
    assert counts.matched_submission_count == 1
    assert counts.unmatched_submission_count == 1


def test_selected_shared_email_is_not_private_identity_when_location_assigns() -> None:
    recipient = _recipient(
        "9876543210",
        imported_fields={
            "email": "shared@example.com",
            "location": "North",
        },
        matching_field_keys=("email", "location"),
    )
    identified = _submission(
        client_email="shared@example.com",
        custom_answers=({"label": "Location", "value": "North"},),
    )
    same_email = _submission(
        name="Other Person",
        client_email="shared@example.com",
        custom_answers=({"label": "Location", "value": "South"},),
    )

    rows, counts = compare_group_submissions([recipient], [identified, same_email])
    recipient_row = next(row for row in rows if row.recipient_ids)
    evidence_by_kind = {item.kind: item for item in recipient_row.match_evidence}

    assert recipient_row.status == "submitted"
    assert recipient_row.submission_ids == (identified.id,)
    assert evidence_by_kind["email"].private_identity_confirmed is False
    assert evidence_by_kind["location"].private_identity_confirmed is False
    assert counts.matched_submission_count == 1


def test_unique_selected_private_fields_confirm_private_identity() -> None:
    cases = (
        (
            "phone_number",
            {"phone_number": "9876543210"},
            {"client_phone": "9876543210"},
        ),
        (
            "email",
            {"email": "unique@example.com"},
            {"client_email": "unique@example.com"},
        ),
    )

    for field_key, imported_fields, submission_kwargs in cases:
        recipient = _recipient(
            "9876543210",
            imported_fields=imported_fields,
            matching_field_keys=(field_key,),
        )
        submission = _submission(**submission_kwargs)

        rows, counts = compare_group_submissions([recipient], [submission])
        recipient_row = next(row for row in rows if row.recipient_ids)

        assert recipient_row.status == "submitted", field_key
        assert len(recipient_row.match_evidence) == 1, field_key
        assert recipient_row.match_evidence[0].private_identity_confirmed is True
        assert counts.matched_submission_count == 1, field_key


def test_or_matches_to_different_recipients_are_reviewable() -> None:
    producer_recipient = _recipient(
        "9876543210",
        imported_fields={
            "producer_code": "P100",
            "location": "North",
        },
        matching_field_keys=("producer_code", "location"),
    )
    location_recipient = _recipient(
        "9123456789",
        imported_fields={
            "producer_code": "P200",
            "location": "South",
        },
        matching_field_keys=("producer_code", "location"),
    )
    submission = _submission(
        custom_answers=(
            {"label": "Producer Code", "value": "P100"},
            {"label": "Location", "value": "South"},
        ),
    )

    rows, counts = compare_group_submissions(
        [producer_recipient, location_recipient],
        [submission],
    )
    recipient_rows = [row for row in rows if row.recipient_ids]

    assert {row.status for row in recipient_rows} == {"needs_review"}
    assert all(row.candidate_submission_ids == (submission.id,) for row in recipient_rows)
    assert counts.matched_submission_count == 0
    assert counts.needs_review_submission_count == 1


def test_selected_heading_does_not_read_unselected_alias_column() -> None:
    recipient = _recipient(
        "9876543210",
        imported_fields={
            "producer_code": "P100",
            "dealer_code": "D200",
        },
        matching_field_keys=("producer_code",),
    )
    submission = _submission(
        custom_answers=({"label": "Dealer Code", "value": "D200"},),
    )

    rows, counts = compare_group_submissions([recipient], [submission])
    recipient_row = next(row for row in rows if row.recipient_ids)

    assert recipient_row.status == "not_submitted"
    assert counts.matched_submission_count == 0
    assert counts.unmatched_submission_count == 1


def test_missing_like_selected_values_never_identify_a_submission() -> None:
    cases = (
        (
            "producer_code",
            "N/A",
            {"custom_answers": ({"label": "Producer Code", "value": "N/A"},)},
        ),
        (
            "date_of_birth",
            "Not Available",
            {"confirmed_fields": {"date_of_birth": "Not Available"}},
        ),
    )

    for field_key, field_value, submission_kwargs in cases:
        recipient = _recipient(
            "9876543210",
            imported_fields={field_key: field_value},
            matching_field_keys=(field_key,),
        )
        submission = _submission(**submission_kwargs)

        rows, counts = compare_group_submissions([recipient], [submission])
        recipient_row = next(row for row in rows if row.recipient_ids)

        assert recipient_row.status == "not_submitted", field_key
        assert counts.matched_submission_count == 0, field_key
        assert counts.unmatched_submission_count == 1, field_key


def test_confirmed_alias_supersedes_stale_extracted_selected_value() -> None:
    stale_recipient = _recipient(
        "9876543210",
        imported_fields={"date_of_birth": "01/01/2000"},
        matching_field_keys=("date_of_birth",),
    )
    corrected_recipient = _recipient(
        "9123456789",
        imported_fields={"date_of_birth": "02/02/2000"},
        matching_field_keys=("date_of_birth",),
    )
    submission = _submission(
        extracted_fields={"dob": "01/01/2000"},
        confirmed_fields={"date_of_birth": "02/02/2000"},
    )

    rows, counts = compare_group_submissions(
        [stale_recipient, corrected_recipient],
        [submission],
    )
    by_recipient = {row.recipient_ids[0]: row for row in rows if row.recipient_ids}

    assert by_recipient[stale_recipient.id].status == "not_submitted"
    assert by_recipient[corrected_recipient.id].status == "submitted"
    assert counts.matched_submission_count == 1


def test_confirmed_selected_value_supersedes_stale_staff_alias() -> None:
    stale_recipient = _recipient(
        "9876543210",
        imported_fields={"staff_code": "OLD-1"},
        matching_field_keys=("staff_code",),
    )
    corrected_recipient = _recipient(
        "9123456789",
        imported_fields={"staff_code": "NEW-2"},
        matching_field_keys=("staff_code",),
    )
    submission = _submission(
        staff_metadata={"employee_code": "OLD-1"},
        confirmed_fields={"staff_code": "NEW-2"},
    )

    rows, counts = compare_group_submissions(
        [stale_recipient, corrected_recipient],
        [submission],
    )
    by_recipient = {row.recipient_ids[0]: row for row in rows if row.recipient_ids}

    assert by_recipient[stale_recipient.id].status == "not_submitted"
    assert by_recipient[corrected_recipient.id].status == "submitted"
    assert counts.matched_submission_count == 1
