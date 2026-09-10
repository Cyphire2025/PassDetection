from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.application.use_cases.whatsapp.group_submission_matching import (
    RecipientForComparison,
    SubmissionForComparison,
    compare_group_submissions,
)

NOW = datetime(2026, 9, 11, tzinfo=UTC)


def _recipient(**changes: object) -> RecipientForComparison:
    recipient = RecipientForComparison(
        id=uuid.uuid4(), broadcast_id=uuid.uuid4(), broadcast_name="Party roster",
        name="Producer Person", phone="9876543210", updated_at=NOW,
        imported_fields={"producer_code": "2453900000"},
        matching_field_keys=("name", "phone_number", "producer_code"),
    )
    return replace(recipient, **changes)


def _traveller(index: int, **changes: object) -> SubmissionForComparison:
    submission = SubmissionForComparison(
        id=uuid.uuid4(), name=f"Traveller {index}",
        client_phone=f"91234567{index:02d}", family_head_phone=None,
        updated_at=NOW, confirmed_fields={"passport_number": f"P12345{index:02d}"},
        custom_answers=({"label": "Producer Code", "value": "2453900000"},),
    )
    return replace(submission, **changes)


def test_producer_and_two_different_travellers_are_identified_not_duplicates() -> None:
    producer = _traveller(1, name="Producer Person", client_phone="9876543210")
    first, second = _traveller(2), _traveller(3)
    rows, summary = compare_group_submissions([_recipient()], [producer, first, second])

    assert len(rows) == 1
    assert rows[0].status == "submitted"
    assert set(rows[0].submission_ids) == {producer.id, first.id, second.id}
    assert rows[0].duplicate_submission_ids == ()
    assert rows[0].candidate_submission_ids == ()
    assert summary.matched_submission_count == 3
    assert summary.multiple_submission_count == summary.unmatched_submission_count == 0
    phone_evidence = [item for item in rows[0].match_evidence if item.kind == "phone_number"]
    assert len(phone_evidence) == 1
    assert phone_evidence[0].submission_id == producer.id
    assert phone_evidence[0].private_identity_confirmed is True
    assert all(
        item.private_identity_confirmed is False
        for item in rows[0].match_evidence if item.kind == "agent_employee_code"
    )


def test_duplicate_passport_pair_does_not_mark_another_traveller_duplicate() -> None:
    first = _traveller(1, confirmed_fields={"passport_number": "P1234567", "dob": "01/02/1990"})
    duplicate = _traveller(2, confirmed_fields={"passport_no": "P1234567", "date_of_birth": "1990-02-01"})
    distinct = _traveller(3)
    rows, summary = compare_group_submissions([_recipient()], [first, duplicate, distinct])

    assert rows[0].status == "multiple_submissions"
    assert set(rows[0].submission_ids) == {first.id, duplicate.id, distinct.id}
    assert set(rows[0].duplicate_submission_ids) == {first.id, duplicate.id}
    assert summary.multiple_submission_count == 1
    assert summary.matched_submission_count == 3


def test_unknown_birth_date_cannot_bridge_conflicting_duplicate_identities() -> None:
    submissions = [
        _traveller(1, confirmed_fields={"passport_number": "P1234567", "dob": "01/02/1990"}),
        _traveller(2, confirmed_fields={"passport_number": "P1234567", "dob": "01/02/1991"}),
        _traveller(3, confirmed_fields={"passport_number": "P1234567"}),
    ]
    rows, _ = compare_group_submissions([_recipient()], submissions)
    assert rows[0].status == "submitted"
    assert rows[0].duplicate_submission_ids == ()


@pytest.mark.parametrize("passport", [None, "", "N/A", "Not Available"])
def test_missing_passports_do_not_make_shared_code_uploads_duplicates(passport: str | None) -> None:
    submissions = [
        _traveller(index, confirmed_fields={"passport_number": passport}) for index in (1, 2)
    ]
    rows, summary = compare_group_submissions([_recipient()], submissions)
    assert rows[0].status == "submitted"
    assert rows[0].duplicate_submission_ids == ()
    assert summary.matched_submission_count == 2


def test_shared_producer_across_roster_contacts_stays_reviewable() -> None:
    first = _recipient()
    other = _recipient(phone="9888888888", name="Other Producer")
    submissions = [_traveller(1), _traveller(2)]
    rows, summary = compare_group_submissions([first, other], submissions)

    assert len(rows) == 2
    assert all(row.status == "needs_review" for row in rows)
    assert all(set(row.candidate_submission_ids) == {item.id for item in submissions} for row in rows)
    assert summary.matched_submission_count == summary.unmatched_submission_count == 0


def test_assigned_recipient_keeps_unresolved_selected_code_candidates_visible() -> None:
    first = _recipient()
    other = _recipient(phone="9888888888", name="Other Producer")
    producer = _traveller(1, name="Producer Person", client_phone="9876543210")
    nominee = _traveller(2)
    rows, summary = compare_group_submissions([first, other], [producer, nominee])

    first_row = next(row for row in rows if first.id in row.recipient_ids)
    assert first_row.status == "needs_review"
    assert set(first_row.candidate_submission_ids) == {producer.id, nominee.id}
    assert any(item.submission_id == nominee.id for item in first_row.match_evidence)
    assert summary.unmatched_submission_count == 0


def test_identifier_prefix_is_not_discarded_to_make_a_match() -> None:
    exact = _traveller(1)
    prefixed = _traveller(2, custom_answers=({"label": "Producer Code", "value": "AIG2453900000"},))
    rows, summary = compare_group_submissions([_recipient()], [exact, prefixed])

    assert next(row for row in rows if row.recipient_ids).submission_ids == (exact.id,)
    assert next(row for row in rows if row.status == "unmatched_submission").submission_ids == (prefixed.id,)
    assert summary.matched_submission_count == 1


def test_selected_name_phone_alone_do_not_gain_shared_party_authority() -> None:
    recipient = _recipient(matching_field_keys=("name", "phone_number"))
    submissions = [
        _traveller(index, name="Producer Person", client_phone="9876543210") for index in (1, 2)
    ]
    rows, summary = compare_group_submissions([recipient], submissions)
    assert rows[0].status == "needs_review"
    assert summary.matched_submission_count == 0


def test_shared_selected_email_associates_party_without_private_identity() -> None:
    recipient = _recipient(imported_fields={"email": "shared@example.com"}, matching_field_keys=("email",))
    submissions = [_traveller(index, client_email="shared@example.com") for index in (1, 2)]
    rows, summary = compare_group_submissions([recipient], submissions)
    assert rows[0].status == "submitted"
    assert summary.matched_submission_count == 2
    assert all(item.private_identity_confirmed is False for item in rows[0].match_evidence)


def test_distinct_travellers_can_match_different_selected_details_with_or_semantics() -> None:
    recipient = _recipient(
        imported_fields={"producer_code": "2453900000", "location": "North"},
        matching_field_keys=("producer_code", "location"),
    )
    code_match = _traveller(1)
    location_match = _traveller(2, custom_answers=({"label": "Location", "value": "North"},))
    rows, summary = compare_group_submissions([recipient], [code_match, location_match])
    assert rows[0].status == "submitted"
    assert set(rows[0].submission_ids) == {code_match.id, location_match.id}
    assert rows[0].duplicate_submission_ids == ()
    assert summary.matched_submission_count == 2


def test_selected_passport_repeats_are_duplicates_not_private_identity() -> None:
    recipient = _recipient(imported_fields={"passport_number": "P1234567"}, matching_field_keys=("passport_number",))
    submissions = [_traveller(index, confirmed_fields={"passport_number": "P1234567"}) for index in (1, 2)]
    rows, _ = compare_group_submissions([recipient], submissions)
    assert rows[0].status == "multiple_submissions"
    assert set(rows[0].duplicate_submission_ids) == {item.id for item in submissions}
    assert all(item.private_identity_confirmed is False for item in rows[0].match_evidence)


def test_legacy_family_contact_distinguishes_duplicate_passports() -> None:
    recipient = _recipient(matching_field_keys=None)
    first = _traveller(1, family_head_phone="9876543210", confirmed_fields={"passport_number": "P1234567"})
    duplicate = _traveller(2, family_head_phone="9876543210", confirmed_fields={"passport_number": "P1234567"})
    distinct = _traveller(3, family_head_phone="9876543210")
    rows, _ = compare_group_submissions([recipient], [first, duplicate, distinct])
    assert rows[0].status == "multiple_submissions"
    assert set(rows[0].duplicate_submission_ids) == {first.id, duplicate.id}


def test_roster_unique_alternate_evidence_is_preferred_without_private_upgrade() -> None:
    recipient = _recipient(
        imported_fields={
            "producer_code": "A100", "producer_code_2": "Z200",
            "duplicate_conflicting_fields": "producer_code",
        }, matching_field_keys=("producer_code",),
    )
    other = _recipient(phone="9888888888", imported_fields={"producer_code": "A100"}, matching_field_keys=("producer_code",))
    submissions = [
        _traveller(index, custom_answers=(
            {"label": "Producer Code", "value": "A100"},
            {"label": "Agent Code", "value": "Z200"},
        )) for index in (1, 2)
    ]
    rows, summary = compare_group_submissions([recipient, other], submissions)
    recipient_row = next(row for row in rows if recipient.id in row.recipient_ids)
    assert recipient_row.status == "submitted"
    assert summary.matched_submission_count == 2
    assert all(item.recipient_value == "Z200" for item in recipient_row.match_evidence)
    assert all(item.private_identity_confirmed is False for item in recipient_row.match_evidence)
