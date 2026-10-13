"""Calendar-month operational checks and explicitly versioned itinerary rules.

O(d) time and O(d) output space for a bounded itinerary of d destinations.
Unknown rule coverage is never reported as suitable. Rules are configured by an
authorised operator; examples in external guidance are not universal visa rules.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class SuitabilityOutcome(StrEnum):
    SUITABLE = "suitable"
    REPLACEMENT_REQUIRED = "replacement_required"
    REVIEW_REQUIRED = "review_required"
    CANNOT_ASSESS = "cannot_assess"


def add_calendar_months(value: date, months: int) -> date:
    year, month_zero = divmod(value.year * 12 + value.month - 1 + months, 12)
    month = month_zero + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


@dataclass(frozen=True, slots=True)
class TravelDocument:
    issuing_country: str | None
    nationality: str | None
    document_type: str | None
    issue_date: date | None
    expiry_date: date | None
    accepted: bool
    available: bool
    lifecycle: str


@dataclass(frozen=True, slots=True)
class DestinationRule:
    destination: str
    version: str
    source_url: str
    valid_until: date
    arrival: date
    departure: date
    validity_months: int
    anchor: str  # validated on entry: arrival or departure
    maximum_issue_age_months: int | None = None


@dataclass(frozen=True, slots=True)
class SuitabilityResult:
    outcome: SuitabilityOutcome
    reason_codes: tuple[str, ...]
    rule_versions: tuple[str, ...]


def assess_document(
    document: TravelDocument,
    *,
    travel_date: date | None,
    today: date,
    destinations: tuple[str, ...],
    rules: tuple[DestinationRule, ...],
) -> SuitabilityResult:
    if len(destinations) > 32 or len(rules) > 32:
        raise ValueError("itinerary exceeds the supported bounded check")
    if document.lifecycle in {"lost", "cancelled", "stolen", "compromised", "unusable"}:
        return SuitabilityResult(SuitabilityOutcome.REPLACEMENT_REQUIRED, ("document_unusable",), ())
    if not document.accepted:
        return SuitabilityResult(SuitabilityOutcome.REVIEW_REQUIRED, ("acceptance_required",), ())
    if not document.available:
        return SuitabilityResult(SuitabilityOutcome.REPLACEMENT_REQUIRED, ("scan_unavailable",), ())
    if document.expiry_date is None or travel_date is None:
        return SuitabilityResult(SuitabilityOutcome.CANNOT_ASSESS, ("dates_missing",), ())
    if document.expiry_date <= max(today, add_calendar_months(travel_date, 6)):
        return SuitabilityResult(
            SuitabilityOutcome.REPLACEMENT_REQUIRED, ("operational_six_month_rule",), (),
        )
    if not all((document.issuing_country, document.nationality, document.document_type)):
        return SuitabilityResult(SuitabilityOutcome.CANNOT_ASSESS, ("document_context_missing",), ())
    by_destination = {rule.destination: rule for rule in rules}
    if len(by_destination) != len(rules):
        raise ValueError("ambiguous destination rule coverage")
    reasons: list[str] = []
    versions: list[str] = []
    if not destinations:
        reasons.append("itinerary_missing")
    for destination in dict.fromkeys(destinations):
        rule = by_destination.get(destination)
        if rule is None or rule.valid_until < today:
            reasons.append("rule_coverage_missing")
            continue
        if (
            rule.anchor not in {"arrival", "departure"}
            or not 0 <= rule.validity_months <= 120
            or rule.departure < rule.arrival
            or not rule.version
            or not rule.source_url.startswith("https://")
            or (rule.maximum_issue_age_months is not None and not 1 <= rule.maximum_issue_age_months <= 240)
        ):
            raise ValueError("invalid destination rule")
        versions.append(rule.version)
        anchor = rule.arrival if rule.anchor == "arrival" else rule.departure
        if document.expiry_date < add_calendar_months(anchor, rule.validity_months):
            return SuitabilityResult(
                SuitabilityOutcome.REPLACEMENT_REQUIRED, ("destination_validity_rule",), tuple(versions),
            )
        if rule.maximum_issue_age_months is not None:
            if document.issue_date is None:
                reasons.append("issue_date_missing")
            elif document.issue_date > rule.arrival or rule.arrival >= add_calendar_months(
                document.issue_date, rule.maximum_issue_age_months,
            ):
                return SuitabilityResult(
                    SuitabilityOutcome.REPLACEMENT_REQUIRED, ("destination_issue_age_rule",), tuple(versions),
                )
    return SuitabilityResult(
        SuitabilityOutcome.REVIEW_REQUIRED if reasons else SuitabilityOutcome.SUITABLE,
        tuple(dict.fromkeys(reasons)), tuple(versions),
    )
