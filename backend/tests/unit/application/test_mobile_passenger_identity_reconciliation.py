from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.application.mobile.passenger_identity_reconciliation import (
    plan_passenger_identities,
)
from app.application.use_cases.whatsapp.group_submission_matching import (
    MatchEvidence,
    SubmissionMatchRow,
)


def _submission(
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    employee_code: str | None = None,
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        group_id=group_id,
        confirmed_fields={},
        staff_metadata={"employee_code": employee_code} if employee_code else {},
    )


def _row(*submissions, status: str = "submitted") -> SubmissionMatchRow:
    return SubmissionMatchRow(
        status=status,
        match_basis="phone",
        normalized_phone="+919876543210",
        recipient_ids=(uuid.uuid4(),),
        submission_ids=tuple(item.id for item in submissions),
        broadcast_ids=(uuid.uuid4(),),
        broadcast_names=("Roster",),
        recipient_names=("Passenger",),
        submission_names=tuple("Passenger" for _item in submissions),
        updated_at=datetime.now(tz=UTC),
        confidence="high",
        match_evidence=tuple(
            MatchEvidence(
                submission_id=item.id,
                kind="phone",
                recipient_value="+919876543210",
                submission_value="+919876543210",
                weight=100,
            )
            for item in submissions
        ),
    )


def test_shared_number_requires_distinct_secondary_factors() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    first = _submission(
        agency_id=agency_id, group_id=group_id, employee_code="EMP-001"
    )
    second = _submission(
        agency_id=agency_id, group_id=group_id, employee_code="EMP-002"
    )

    plan = plan_passenger_identities(
        [_row(first, second, status="multiple_submissions")],
        [first, second],
        agency_id=agency_id,
        group_id=group_id,
    )

    assert len(plan.candidates) == 2
    assert {item.secondary_factor_value for item in plan.candidates} == {
        "EMP-001",
        "EMP-002",
    }
    assert all(item.secondary_factor_type == "employee_code" for item in plan.candidates)
    assert all(item.is_shared_number for item in plan.candidates)
    assert all(item.requires_secondary_verification for item in plan.candidates)


def test_unique_group_identity_retains_factor_for_cross_group_otp_collision() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    submission = _submission(
        agency_id=agency_id,
        group_id=group_id,
        employee_code="EMP-UNIQUE",
    )

    plan = plan_passenger_identities(
        [_row(submission)],
        [submission],
        agency_id=agency_id,
        group_id=group_id,
    )

    assert len(plan.candidates) == 1
    candidate = plan.candidates[0]
    assert candidate.secondary_factor_type == "employee_code"
    assert candidate.secondary_factor_value == "EMP-UNIQUE"
    assert candidate.is_shared_number is False
    assert candidate.requires_secondary_verification is False


def test_shared_number_with_duplicate_factor_fails_closed() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    first = _submission(
        agency_id=agency_id, group_id=group_id, employee_code="EMP-SHARED"
    )
    second = _submission(
        agency_id=agency_id, group_id=group_id, employee_code="emp-shared"
    )

    plan = plan_passenger_identities(
        [_row(first, second, status="multiple_submissions")],
        [first, second],
        agency_id=agency_id,
        group_id=group_id,
    )

    assert plan.candidates == ()
    assert plan.skipped_without_secondary_factor == 2


def test_name_only_or_ambiguous_rows_never_provision() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    submission = _submission(agency_id=agency_id, group_id=group_id)
    row = _row(submission, status="needs_review")
    row = SubmissionMatchRow(
        **{
            **row.__dict__,
            "match_basis": "entered_name",
            "submission_ids": (),
            "candidate_submission_ids": (submission.id,),
            "match_evidence": (),
        }
    )

    plan = plan_passenger_identities(
        [row], [submission], agency_id=agency_id, group_id=group_id
    )

    assert plan.candidates == ()
    assert plan.skipped_ambiguous == 1


def test_cross_tenant_submission_is_rejected_even_if_row_references_it() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    other_tenant_submission = _submission(
        agency_id=uuid.uuid4(), group_id=group_id, employee_code="EMP-001"
    )

    plan = plan_passenger_identities(
        [_row(other_tenant_submission)],
        [other_tenant_submission],
        agency_id=agency_id,
        group_id=group_id,
    )

    assert plan.candidates == ()
    assert plan.skipped_ambiguous == 1
