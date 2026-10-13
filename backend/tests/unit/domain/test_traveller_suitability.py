from dataclasses import replace
from datetime import date

from app.domain.services.traveller_suitability import (
    DestinationRule,
    SuitabilityOutcome,
    TravelDocument,
    add_calendar_months,
    assess_document,
)

DOCUMENT = TravelDocument("IND", "IND", "P", date(2025, 1, 1), date(2035, 1, 1), True, True, "current")


def test_calendar_months_handle_leap_days_and_month_ends():
    assert add_calendar_months(date(2024, 2, 29), 12) == date(2025, 2, 28)
    assert add_calendar_months(date(2026, 8, 31), 6) == date(2027, 2, 28)


def test_unknown_coverage_cannot_silently_pass():
    result = assess_document(DOCUMENT, travel_date=date(2026, 11, 1), today=date(2026, 10, 13), destinations=("IDN",), rules=())
    assert result.outcome == SuitabilityOutcome.REVIEW_REQUIRED
    assert "rule_coverage_missing" in result.reason_codes


def test_lost_and_purged_documents_require_recollection():
    for document in (replace(DOCUMENT, lifecycle="lost"), replace(DOCUMENT, available=False)):
        result = assess_document(document, travel_date=None, today=date(2026, 10, 13), destinations=(), rules=())
        assert result.outcome == SuitabilityOutcome.REPLACEMENT_REQUIRED


def test_versioned_arrival_rule_and_operational_policy_are_distinct():
    rule = DestinationRule("IDN", "synthetic-rule-v1", "https://example.test/authority", date(2027, 1, 1), date(2026, 11, 1), date(2026, 11, 20), 6, "arrival")
    result = assess_document(DOCUMENT, travel_date=date(2026, 11, 1), today=date(2026, 10, 13), destinations=("IDN",), rules=(rule,))
    assert result.outcome == SuitabilityOutcome.SUITABLE
    assert result.rule_versions == ("synthetic-rule-v1",)
    changed = replace(rule, departure=date(2035, 1, 1), anchor="departure")
    result = assess_document(DOCUMENT, travel_date=date(2026, 11, 1), today=date(2026, 10, 13), destinations=("IDN",), rules=(changed,))
    assert result.reason_codes == ("destination_validity_rule",)
