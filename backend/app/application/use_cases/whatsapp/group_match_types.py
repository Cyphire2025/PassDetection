"""Immutable roster comparison inputs, evidence and result projections."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class RecipientForComparison:
    id: uuid.UUID
    broadcast_id: uuid.UUID
    broadcast_name: str
    name: str | None
    phone: str | None
    updated_at: datetime
    imported_fields: dict[str, str] = field(default_factory=dict)
    # ``None`` preserves the historical phone/email/passport/staff/name policy.
    # A non-empty tuple is the explicit policy configured on this broadcast
    # link and uses OR semantics across the selected fields.
    matching_field_keys: tuple[str, ...] | None = None


@dataclass(frozen=True)
class SubmissionForComparison:
    id: uuid.UUID
    name: str
    client_phone: str | None
    family_head_phone: str | None
    updated_at: datetime
    client_email: str | None = None
    family_head_email: str | None = None
    confirmed_fields: dict[str, object] = field(default_factory=dict)
    extracted_fields: dict[str, object] = field(default_factory=dict)
    staff_metadata: dict[str, object] = field(default_factory=dict)
    custom_answers: tuple[Mapping[str, object], ...] = ()
    custom_detail_answers: tuple[Mapping[str, object], ...] = ()
    departure_city: str | None = None
    nearest_domestic_airport: str | None = None
    family_relation: str | None = None
    family_gender: str | None = None
    family_head_name: str | None = None
    has_public_collection_contact: bool = False


@dataclass(frozen=True)
class MatchEvidence:
    submission_id: uuid.UUID
    kind: str
    recipient_value: str
    submission_value: str
    weight: int
    # ``None`` denotes legacy/synthetic evidence whose historical semantics
    # are preserved. Selected-field evidence is explicit: only a unique value
    # from a private-grade field is safe for sensitive delivery decisions.
    private_identity_confirmed: bool | None = None


@dataclass(frozen=True)
class RecipientFieldSet:
    recipient_id: uuid.UUID
    fields: dict[str, str]


@dataclass(frozen=True)
class SubmissionMatchRow:
    status: str
    match_basis: str | None
    normalized_phone: str | None
    recipient_ids: tuple[uuid.UUID, ...]
    submission_ids: tuple[uuid.UUID, ...]
    broadcast_ids: tuple[uuid.UUID, ...]
    broadcast_names: tuple[str, ...]
    recipient_names: tuple[str, ...]
    submission_names: tuple[str, ...]
    updated_at: datetime
    confidence: str = "none"
    match_evidence: tuple[MatchEvidence, ...] = ()
    candidate_submission_ids: tuple[uuid.UUID, ...] = ()
    recipient_fields: tuple[RecipientFieldSet, ...] = ()
    resolution_id: uuid.UUID | None = None
    duplicate_submission_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True)
class SubmissionMatchSummary:
    total_recipients: int
    submitted_count: int
    not_submitted_count: int
    multiple_submission_count: int
    matched_submission_count: int
    needs_review_count: int = 0
    needs_review_submission_count: int = 0
    unmatched_submission_count: int = 0
    replacement_count: int = 0
    rejected_upload_count: int = 0


@dataclass(frozen=True)
class _IdentityProfile:
    phones: frozenset[str] = frozenset()
    emails: frozenset[str] = frozenset()
    passport_numbers: frozenset[str] = frozenset()
    staff_codes: frozenset[str] = frozenset()
    names: frozenset[str] = frozenset()
    entered_names: frozenset[str] = frozenset()
    passport_names: frozenset[str] = frozenset()
    selected_fields: Mapping[str, frozenset[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class IdentityEvidenceValues:
    """Normalized values that can connect one member of a matching cluster.

    The public projection deliberately mirrors the exact comparison
    normalizers.  Targeted mobile reconciliation uses it to discover the
    complete connected component before running the authoritative matcher;
    it does not implement a second matching policy.
    """

    phones: frozenset[str] = frozenset()
    emails: frozenset[str] = frozenset()
    passport_numbers: frozenset[str] = frozenset()
    staff_codes: frozenset[str] = frozenset()
    names: frozenset[str] = frozenset()
    selected_fields: Mapping[str, frozenset[str]] = field(default_factory=dict)

    @property
    def all_values(self) -> frozenset[str]:
        selected = frozenset(value for values in self.selected_fields.values() for value in values)
        return (
            self.phones
            | self.emails
            | self.passport_numbers
            | self.staff_codes
            | self.names
            | selected
        )


@dataclass(frozen=True)
class _LogicalRecipient:
    recipients: tuple[RecipientForComparison, ...]
    profile: _IdentityProfile


@dataclass(frozen=True)
class _PairEvidence:
    recipient_index: int
    submission_index: int
    evidence: tuple[MatchEvidence, ...]
    score: int
    auto_match: bool
