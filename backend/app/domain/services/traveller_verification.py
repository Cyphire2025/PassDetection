"""Pure returning-traveller proof rules, shared by all three entry methods.

All operations are O(1) time/space: at most three corroborating dates and five
attempts are examined. Persistence/locking belongs to the application service.
Possession of a phone and passport information is not proof of passport ownership.
"""

from __future__ import annotations

import hmac
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum

CLAIM_LIFETIME = timedelta(minutes=10)
GRANT_IDLE_LIFETIME = timedelta(minutes=15)
GRANT_ABSOLUTE_LIFETIME = timedelta(minutes=60)
QUESTION_WINDOW = timedelta(hours=24)
FAILURE_WINDOW = timedelta(minutes=30)
MAX_FAILURES = 5
MAX_PHONE_CANDIDATES = 20


class DocumentQuestion(StrEnum):
    DATE_OF_BIRTH = "date_of_birth"
    ISSUE_DATE = "issue_date"
    EXPIRY_DATE = "expiry_date"


class VerificationFailure(ValueError):
    """A bounded internal reason; presentation must use a generic message."""


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def exact_passport_number(value: str) -> str:
    """Case-insensitive identifier; never rewrite O/0 or drop leading zeroes."""
    value = value.strip().upper()
    if not 3 <= len(value) <= 32 or not value.isascii() or not value.isalnum():
        raise VerificationFailure("invalid_passport_identifier")
    return value


def issuing_context(value: str, document_type: str) -> tuple[str, str]:
    country = value.strip().upper()
    kind = document_type.strip().upper()
    if len(country) != 3 or not country.isascii() or not country.isalpha():
        raise VerificationFailure("issuing_country_required")
    if not 1 <= len(kind) <= 16 or not kind.isascii() or not kind.isalnum():
        raise VerificationFailure("document_type_required")
    return country, kind


def parse_answer(value: str) -> date:
    """Only explicit ISO calendar dates; locale guessing creates false matches."""
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        raise VerificationFailure("invalid_date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise VerificationFailure("invalid_date") from exc
    if parsed.isoformat() != value:
        raise VerificationFailure("invalid_date")
    return parsed


def choose_questions(
    reliable: Sequence[DocumentQuestion],
    *,
    recovery: bool,
    existing: Sequence[DocumentQuestion] = (),
) -> tuple[DocumentQuestion, ...]:
    """Choose once under a persisted selection-row lock, never on each request.

    Recovery extends the existing question set and cannot replace an inconvenient
    question. The caller stores the complete result until the selection expires.
    """
    available = tuple(dict.fromkeys(reliable))
    selected = list(dict.fromkeys(existing))
    if any(question not in available for question in selected):
        raise VerificationFailure("document_evidence_changed")
    required = 2 if recovery else 1
    if len(available) < required:
        raise VerificationFailure("insufficient_reliable_evidence")
    while len(selected) < required:
        # User-selected policy: DOB first, then other reliable dates. Explicit
        # question changes are persisted by the service without resetting limits.
        selected.append(next(q for q in DocumentQuestion if q in available and q not in selected))
    return tuple(selected)


def answers_match(
    selected: Sequence[DocumentQuestion],
    expected: Mapping[DocumentQuestion, date],
    supplied: Mapping[str, str],
) -> bool:
    """Check the entire answer set without identifying which field failed."""
    if not selected or set(supplied) != set(selected):
        return False
    matches = True
    for question in selected:
        try:
            actual = parse_answer(supplied[question])
            target = expected[question]
            matches &= hmac.compare_digest(actual.isoformat(), target.isoformat())
        except (VerificationFailure, KeyError):
            matches = False
    return matches


@dataclass(frozen=True, slots=True)
class FailureBudget:
    failures: int = 0
    window_started_at: datetime | None = None
    blocked_until: datetime | None = None

    def blocked(self, now: datetime) -> bool:
        return self.blocked_until is not None and utc(self.blocked_until) > utc(now)

    def fail(self, now: datetime) -> FailureBudget:
        """Fixed cooldown; rejected requests never extend a running lockout."""
        if self.blocked(now):
            return self
        expired = (
            self.window_started_at is None
            or utc(now) >= utc(self.window_started_at) + FAILURE_WINDOW
        )
        failures = 1 if expired else self.failures + 1
        started = now if expired else self.window_started_at
        return FailureBudget(
            failures=failures,
            window_started_at=started,
            blocked_until=now + FAILURE_WINDOW if failures >= MAX_FAILURES else None,
        )


@dataclass(frozen=True, slots=True)
class DisclosureEvidence:
    eligible: bool
    uniquely_resolved: bool
    otp_verified: bool
    passport_matched: bool
    questions_passed: bool
    authority_current: bool
    actor_authorized: bool
    claim_expires_at: datetime
    otp_required: bool = True


def require_disclosure(evidence: DisclosureEvidence, now: datetime) -> None:
    """Single authoritative prerequisite shared by normal and recovery claims."""
    if not (
        evidence.eligible
        and evidence.uniquely_resolved
        and (evidence.otp_verified or not evidence.otp_required)
        and evidence.passport_matched
        and evidence.questions_passed
        and evidence.authority_current
        and evidence.actor_authorized
        and utc(evidence.claim_expires_at) > utc(now)
    ):
        raise VerificationFailure("historical_access_unavailable")
