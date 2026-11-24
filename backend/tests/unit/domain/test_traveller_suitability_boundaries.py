"""Calendar comparisons retain their meaning beyond date's representable ceiling."""

from dataclasses import replace
from datetime import date

import pytest

from app.domain.services.traveller_suitability import (
    DestinationRule,
    SuitabilityOutcome,
    TravelDocument,
    assess_document,
)

DOCUMENT = TravelDocument("IND", "IND", "P", date(2025, 1, 1), date.max, True, True, "current")


@pytest.mark.parametrize("travel_date,expected", [
    (date(9999, 6, 30), SuitabilityOutcome.REVIEW_REQUIRED),
    (date(9999, 7, 1), SuitabilityOutcome.REPLACEMENT_REQUIRED),
    (date.max, SuitabilityOutcome.REPLACEMENT_REQUIRED),
])
def test_operational_deadline_crossing_maximum_year_requires_replacement(travel_date, expected):
    result = assess_document(DOCUMENT, travel_date=travel_date, today=date(2026, 1, 1),
                             destinations=(), rules=())
    assert result.outcome is expected
    assert result.reason_codes == (
        ("operational_six_month_rule",) if expected is SuitabilityOutcome.REPLACEMENT_REQUIRED
        else ("itinerary_missing",)
    )


@pytest.mark.parametrize("months,expected", [
    (0, SuitabilityOutcome.SUITABLE),
    (1, SuitabilityOutcome.REPLACEMENT_REQUIRED),
    (120, SuitabilityOutcome.REPLACEMENT_REQUIRED),
])
def test_destination_deadline_is_not_clamped_to_a_falsely_suitable_date(months, expected):
    rule = DestinationRule("SYN", "synthetic-v1", "https://example.test/rule", date.max,
                           date.max, date.max, months, "arrival")
    result = assess_document(DOCUMENT, travel_date=date(2026, 8, 1), today=date(2026, 1, 1),
                             destinations=("SYN",), rules=(rule,))
    assert result.outcome is expected
    assert result.rule_versions == ("synthetic-v1",)
    assert result.reason_codes == (() if months == 0 else ("destination_validity_rule",))


def test_issue_age_deadline_after_maximum_year_does_not_expire_early():
    rule = DestinationRule("SYN", "synthetic-v1", "https://example.test/rule", date.max,
                           date.max, date.max, 0, "arrival", maximum_issue_age_months=1)
    result = assess_document(replace(DOCUMENT, issue_date=date.max), travel_date=date(2026, 8, 1),
                             today=date(2026, 1, 1), destinations=("SYN",), rules=(rule,))
    assert result.outcome is SuitabilityOutcome.SUITABLE
    assert result.reason_codes == ()
