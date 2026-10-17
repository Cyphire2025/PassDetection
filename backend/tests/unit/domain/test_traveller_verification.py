from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from app.domain.services.traveller_verification import (
    DisclosureEvidence,
    DocumentQuestion,
    FailureBudget,
    VerificationFailure,
    answers_match,
    choose_questions,
    exact_passport_number,
    issuing_context,
    require_disclosure,
)

NOW = datetime(2026, 10, 13, tzinfo=UTC)


def test_identifier_is_lossless_and_requires_issuing_context():
    assert exact_passport_number(" 00O0123 ") == "00O0123"
    assert exact_passport_number("00O0123") != exact_passport_number("0000123")
    with pytest.raises(VerificationFailure):
        issuing_context("", "P")


def test_recovery_extends_stable_questions_and_rejects_missing_provenance():
    dob, issue, expiry = tuple(DocumentQuestion)
    selected = choose_questions((dob, issue, expiry), recovery=True, existing=(dob,))
    assert selected[0] == dob
    assert len(set(selected)) == 2
    assert choose_questions((dob, issue, expiry), recovery=True, existing=selected) == selected
    with pytest.raises(VerificationFailure):
        choose_questions((dob,), recovery=True)
    with pytest.raises(VerificationFailure):
        choose_questions((issue, expiry), recovery=True, existing=(dob,))


def test_dates_require_complete_exact_selected_set():
    selected = (DocumentQuestion.DATE_OF_BIRTH, DocumentQuestion.EXPIRY_DATE)
    expected = {selected[0]: date(2000, 2, 29), selected[1]: date(2030, 1, 1)}
    assert answers_match(selected, expected, {"date_of_birth": "2000-02-29", "expiry_date": "2030-01-01"})
    assert not answers_match(selected, expected, {"date_of_birth": "29/02/2000", "expiry_date": "2030-01-01"})
    assert not answers_match(selected, expected, {"date_of_birth": "2000-02-29"})
    assert not answers_match(selected, expected, {"date_of_birth": "2000-02-29", "expiry_date": "2030-01-01", "issue_date": "2020-01-01"})


def test_fifth_shared_failure_locks_for_fixed_thirty_minutes():
    budget = FailureBudget()
    for offset in range(5):
        budget = budget.fail(NOW + timedelta(seconds=offset))
    assert budget.blocked(NOW + timedelta(minutes=1))
    assert budget.fail(NOW + timedelta(minutes=20)) == budget
    assert not budget.blocked(NOW + timedelta(minutes=31))
    assert budget.fail(NOW + timedelta(minutes=31)).failures == 1


@pytest.mark.parametrize("field", [
    "eligible", "uniquely_resolved", "otp_verified", "passport_matched",
    "questions_passed", "authority_current", "actor_authorized",
])
def test_every_route_requires_the_same_complete_evidence(field):
    evidence = DisclosureEvidence(True, True, True, True, True, True, True, NOW + timedelta(minutes=1))
    require_disclosure(evidence, NOW)
    with pytest.raises(VerificationFailure):
        require_disclosure(replace(evidence, **{field: False}), NOW)
    with pytest.raises(VerificationFailure):
        require_disclosure(replace(evidence, claim_expires_at=NOW), NOW)
