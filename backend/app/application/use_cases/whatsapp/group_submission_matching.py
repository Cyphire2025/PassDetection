"""Deterministic identity comparison for WhatsApp recipients and submissions.

Exact contact and identifier evidence can assign a submission automatically.
Names remain useful evidence, but a name alone never creates an automatic
match. A submission is assigned to at most one logical recipient; collisions
and contradictory evidence are surfaced for staff review.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Iterable

from app.application.use_cases.whatsapp.contact_normalization import (
    clean_whatsapp_name,
    normalize_whatsapp_phone,
)

_EMAIL_KEYS = frozenset({"email", "email_address", "e_mail", "mail"})
_PASSPORT_KEYS = frozenset({"passport", "passport_no", "passport_number", "passportnumber"})
_STAFF_CODE_KEYS = frozenset(
    {
        "employee_code",
        "staff_code",
        "staff_id",
        "staffcode",
    }
)
_GIVEN_NAME_KEYS = frozenset({"first_name", "given_name", "given_names"})
_SURNAME_KEYS = frozenset({"family_name", "last_name", "surname"})
_NAME_KEYS = frozenset(
    {
        "client_name",
        "employee_name",
        "full_name",
        "name",
        "passenger_name",
        "recipient_name",
        "staff_name",
        "staffname",
    }
)
_PHONE_KEYS = frozenset(
    {
        "contact",
        "contact_number",
        "mobile",
        "mobile_number",
        "phone",
        "phone_number",
        "telephone",
        "whatsapp",
        "whatsapp_number",
    }
)
_STRONG_EVIDENCE_WEIGHTS = {
    "passport_number": 120,
    "staff_code": 110,
    "email": 100,
    "phone": 100,
}
_NAME_EVIDENCE_WEIGHT = 20


@dataclass(frozen=True)
class RecipientForComparison:
    id: uuid.UUID
    broadcast_id: uuid.UUID
    broadcast_name: str
    name: str | None
    phone: str | None
    updated_at: datetime
    imported_fields: dict[str, str] = field(default_factory=dict)


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


@dataclass(frozen=True)
class MatchEvidence:
    submission_id: uuid.UUID
    kind: str
    recipient_value: str
    submission_value: str
    weight: int


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

    @property
    def all_values(self) -> frozenset[str]:
        return (
            self.phones
            | self.emails
            | self.passport_numbers
            | self.staff_codes
            | self.names
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


def _normalized_key(value: object) -> str:
    text = str(value or "").strip().casefold()
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text)).strip("_")


def _normalized_name(value: object) -> str | None:
    cleaned = clean_whatsapp_name(value)
    if not cleaned:
        return None
    compatible = unicodedata.normalize("NFKC", cleaned).casefold()
    normalized = "".join(
        character if character.isalnum() else " " for character in compatible
    ).strip()
    return " ".join(normalized.split()) or None


def _normalized_email(value: object) -> str | None:
    text = str(value or "").strip().casefold()
    if not text or "@" not in text:
        return None
    local, separator, domain = text.partition("@")
    if not separator or not local or "." not in domain:
        return None
    return f"{local}@{domain}"


def _normalized_identifier(value: object) -> str | None:
    normalized = re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())
    return normalized or None


def _mapping_values(
    mapping: dict[str, object],
    keys: frozenset[str],
) -> list[object]:
    values: list[object] = []
    for raw_key, value in mapping.items():
        normalized = _normalized_key(raw_key)
        base_key = re.sub(r"_\d+$", "", normalized)
        if normalized in keys or base_key in keys:
            values.append(value)
    return values


def _normalized_values(
    values: Iterable[object],
    normalizer: object,
) -> frozenset[str]:
    normalized: set[str] = set()
    for value in values:
        item = normalizer(value)  # type: ignore[operator]
        if item:
            normalized.add(item)
    return frozenset(normalized)


def _passport_fields(submission: SubmissionForComparison) -> dict[str, object]:
    fields = dict(submission.extracted_fields or {})
    fields.update(submission.confirmed_fields or {})
    return fields


def _composed_names(mapping: dict[str, object]) -> list[str]:
    given_values = _mapping_values(mapping, _GIVEN_NAME_KEYS)
    surname_values = _mapping_values(mapping, _SURNAME_KEYS)
    names: list[str] = []
    for given in given_values or [""]:
        for surname in surname_values or [""]:
            combined = " ".join(part for part in (str(given).strip(), str(surname).strip()) if part)
            if combined:
                names.append(combined)
    return names


def _recipient_profile(
    recipients: tuple[RecipientForComparison, ...],
) -> _IdentityProfile:
    fields = [dict(recipient.imported_fields or {}) for recipient in recipients]
    return _IdentityProfile(
        phones=_normalized_values(
            [
                *(recipient.phone for recipient in recipients),
                *(value for mapping in fields for value in _mapping_values(mapping, _PHONE_KEYS)),
            ],
            normalize_whatsapp_phone,
        ),
        emails=_normalized_values(
            (value for mapping in fields for value in _mapping_values(mapping, _EMAIL_KEYS)),
            _normalized_email,
        ),
        passport_numbers=_normalized_values(
            (value for mapping in fields for value in _mapping_values(mapping, _PASSPORT_KEYS)),
            _normalized_identifier,
        ),
        staff_codes=_normalized_values(
            (value for mapping in fields for value in _mapping_values(mapping, _STAFF_CODE_KEYS)),
            _normalized_identifier,
        ),
        names=_normalized_values(
            [
                *(recipient.name for recipient in recipients),
                *(value for mapping in fields for value in _mapping_values(mapping, _NAME_KEYS)),
                *(name for mapping in fields for name in _composed_names(mapping)),
            ],
            _normalized_name,
        ),
    )


def _submission_profile(
    submission: SubmissionForComparison,
) -> _IdentityProfile:
    passport_fields = _passport_fields(submission)
    staff_fields = {
        **dict(submission.staff_metadata or {}),
        **passport_fields,
    }
    entered_names = _normalized_values([submission.name], _normalized_name)
    passport_names = _normalized_values(
        [
            *_mapping_values(passport_fields, _NAME_KEYS),
            *_composed_names(passport_fields),
        ],
        _normalized_name,
    )
    return _IdentityProfile(
        phones=_normalized_values(
            [submission.client_phone, submission.family_head_phone],
            normalize_whatsapp_phone,
        ),
        emails=_normalized_values(
            [submission.client_email, submission.family_head_email],
            _normalized_email,
        ),
        passport_numbers=_normalized_values(
            _mapping_values(passport_fields, _PASSPORT_KEYS),
            _normalized_identifier,
        ),
        staff_codes=_normalized_values(
            _mapping_values(staff_fields, _STAFF_CODE_KEYS),
            _normalized_identifier,
        ),
        names=entered_names | passport_names,
        entered_names=entered_names,
        passport_names=passport_names,
    )


def recipient_identity_evidence(
    recipients: Iterable[RecipientForComparison],
) -> IdentityEvidenceValues:
    """Return evidence normalized by the authoritative recipient matcher."""

    ordered = tuple(sorted(recipients, key=_recipient_sort_key))
    profile = _recipient_profile(ordered)
    return IdentityEvidenceValues(
        phones=profile.phones,
        emails=profile.emails,
        passport_numbers=profile.passport_numbers,
        staff_codes=profile.staff_codes,
        names=profile.names,
    )


def submission_identity_evidence(
    submission: SubmissionForComparison,
) -> IdentityEvidenceValues:
    """Return evidence normalized by the authoritative submission matcher."""

    profile = _submission_profile(submission)
    return IdentityEvidenceValues(
        phones=profile.phones,
        emails=profile.emails,
        passport_numbers=profile.passport_numbers,
        staff_codes=profile.staff_codes,
        names=profile.names,
    )


def _recipient_sort_key(recipient: RecipientForComparison) -> tuple[str, str]:
    return (str(recipient.broadcast_id), str(recipient.id))


def _submission_sort_key(
    submission: SubmissionForComparison,
) -> tuple[datetime, str]:
    return (_timestamp_key(submission.updated_at), str(submission.id))


def _timestamp_key(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _logical_recipients(
    recipients: list[RecipientForComparison],
) -> list[_LogicalRecipient]:
    groups: dict[str, list[RecipientForComparison]] = defaultdict(list)
    for recipient in recipients:
        normalized = normalize_whatsapp_phone(recipient.phone)
        key = normalized or f"invalid:{recipient.id}"
        groups[key].append(recipient)
    return [
        _LogicalRecipient(
            recipients=tuple(sorted(group, key=_recipient_sort_key)),
            profile=_recipient_profile(tuple(sorted(group, key=_recipient_sort_key))),
        )
        for _, group in sorted(groups.items())
    ]


def _evidence_item(
    *,
    submission_id: uuid.UUID,
    kind: str,
    recipient_values: frozenset[str],
    submission_values: frozenset[str],
    weight: int,
) -> MatchEvidence | None:
    shared = sorted(recipient_values & submission_values)
    if not shared:
        return None
    value = shared[0]
    return MatchEvidence(
        submission_id=submission_id,
        kind=kind,
        recipient_value=value,
        submission_value=value,
        weight=weight,
    )


def _pair_evidence(
    *,
    recipient_index: int,
    recipient: _LogicalRecipient,
    submission_index: int,
    submission: SubmissionForComparison,
    submission_profile: _IdentityProfile,
    unique_compound_names: frozenset[str],
) -> _PairEvidence | None:
    evidence = [
        item
        for item in (
            _evidence_item(
                submission_id=submission.id,
                kind="phone",
                recipient_values=recipient.profile.phones,
                submission_values=submission_profile.phones,
                weight=_STRONG_EVIDENCE_WEIGHTS["phone"],
            ),
            _evidence_item(
                submission_id=submission.id,
                kind="email",
                recipient_values=recipient.profile.emails,
                submission_values=submission_profile.emails,
                weight=_STRONG_EVIDENCE_WEIGHTS["email"],
            ),
            _evidence_item(
                submission_id=submission.id,
                kind="passport_number",
                recipient_values=recipient.profile.passport_numbers,
                submission_values=submission_profile.passport_numbers,
                weight=_STRONG_EVIDENCE_WEIGHTS["passport_number"],
            ),
            _evidence_item(
                submission_id=submission.id,
                kind="staff_code",
                recipient_values=recipient.profile.staff_codes,
                submission_values=submission_profile.staff_codes,
                weight=_STRONG_EVIDENCE_WEIGHTS["staff_code"],
            ),
            _evidence_item(
                submission_id=submission.id,
                kind="entered_name",
                recipient_values=recipient.profile.names,
                submission_values=submission_profile.entered_names,
                weight=_NAME_EVIDENCE_WEIGHT,
            ),
            _evidence_item(
                submission_id=submission.id,
                kind="passport_name",
                recipient_values=recipient.profile.names,
                submission_values=submission_profile.passport_names,
                weight=_NAME_EVIDENCE_WEIGHT,
            ),
        )
        if item is not None
    ]
    if not evidence:
        return None
    kinds = {item.kind for item in evidence}
    strong = bool(kinds & _STRONG_EVIDENCE_WEIGHTS.keys())
    name_intersection = (
        recipient.profile.names
        & submission_profile.entered_names
        & submission_profile.passport_names
    )
    unique_compound = bool(name_intersection & unique_compound_names)
    return _PairEvidence(
        recipient_index=recipient_index,
        submission_index=submission_index,
        evidence=tuple(sorted(evidence, key=lambda item: (-item.weight, item.kind))),
        score=sum(item.weight for item in evidence),
        auto_match=strong or unique_compound,
    )


def _unique_compound_names(
    recipients: list[_LogicalRecipient],
    submission_profiles: list[_IdentityProfile],
) -> frozenset[str]:
    recipient_frequency: dict[str, int] = defaultdict(int)
    submission_frequency: dict[str, int] = defaultdict(int)
    for recipient in recipients:
        for name in recipient.profile.names:
            recipient_frequency[name] += 1
    for profile in submission_profiles:
        for name in profile.entered_names & profile.passport_names:
            submission_frequency[name] += 1
    return frozenset(
        name
        for name, count in recipient_frequency.items()
        if count == 1 and submission_frequency.get(name) == 1
    )


def _submission_evidence_indexes(
    profiles: list[_IdentityProfile],
) -> tuple[
    dict[str, set[int]],
    dict[str, set[int]],
    dict[str, set[int]],
    dict[str, set[int]],
    dict[str, set[int]],
]:
    """Invert exact evidence once instead of scanning every recipient/submission pair."""

    phones: dict[str, set[int]] = defaultdict(set)
    emails: dict[str, set[int]] = defaultdict(set)
    passports: dict[str, set[int]] = defaultdict(set)
    staff_codes: dict[str, set[int]] = defaultdict(set)
    names: dict[str, set[int]] = defaultdict(set)
    for index, profile in enumerate(profiles):
        for value in profile.phones:
            phones[value].add(index)
        for value in profile.emails:
            emails[value].add(index)
        for value in profile.passport_numbers:
            passports[value].add(index)
        for value in profile.staff_codes:
            staff_codes[value].add(index)
        for value in profile.entered_names | profile.passport_names:
            names[value].add(index)
    return phones, emails, passports, staff_codes, names


def _candidate_submission_indexes(
    profile: _IdentityProfile,
    evidence_indexes: tuple[
        dict[str, set[int]],
        dict[str, set[int]],
        dict[str, set[int]],
        dict[str, set[int]],
        dict[str, set[int]],
    ],
) -> set[int]:
    candidates: set[int] = set()
    value_groups = (
        (profile.phones, evidence_indexes[0]),
        (profile.emails, evidence_indexes[1]),
        (profile.passport_numbers, evidence_indexes[2]),
        (profile.staff_codes, evidence_indexes[3]),
        (profile.names, evidence_indexes[4]),
    )
    for values, index in value_groups:
        for value in values:
            candidates.update(index.get(value, ()))
    return candidates


def _same_identity_basis(matches: list[_PairEvidence]) -> bool:
    if len(matches) < 2:
        return True
    evidence_sets = [
        {
            (item.kind, item.recipient_value)
            for item in match.evidence
            if item.kind in _STRONG_EVIDENCE_WEIGHTS
        }
        for match in matches
    ]
    common = set.intersection(*evidence_sets) if evidence_sets else set()
    return bool(common)


def _row_shared_fields(
    logical_recipient: _LogicalRecipient,
) -> tuple[RecipientFieldSet, ...]:
    return tuple(
        RecipientFieldSet(
            recipient_id=recipient.id,
            fields=dict(recipient.imported_fields or {}),
        )
        for recipient in logical_recipient.recipients
    )


def _recipient_row(
    *,
    logical_recipient: _LogicalRecipient,
    status: str,
    submissions: list[SubmissionForComparison],
    matches: list[_PairEvidence],
    candidate_submission_ids: set[uuid.UUID],
) -> SubmissionMatchRow:
    source_recipients = logical_recipient.recipients
    broadcast_pairs = sorted(
        {(recipient.broadcast_id, recipient.broadcast_name) for recipient in source_recipients},
        key=lambda item: (item[1].casefold(), str(item[0])),
    )
    recipient_names = tuple(
        sorted(
            {
                name
                for recipient in source_recipients
                if (name := clean_whatsapp_name(recipient.name))
            },
            key=str.casefold,
        )
    )
    ordered_submissions = sorted(submissions, key=_submission_sort_key)
    all_evidence = tuple(
        sorted(
            (item for match in matches for item in match.evidence),
            key=lambda item: (
                str(item.submission_id),
                -item.weight,
                item.kind,
            ),
        )
    )
    basis = "+".join(sorted({item.kind for item in all_evidence})) or None
    timestamps = [
        *(recipient.updated_at for recipient in source_recipients),
        *(submission.updated_at for submission in ordered_submissions),
    ]
    normalized_phone = next(
        iter(sorted(logical_recipient.profile.phones)),
        None,
    )
    confidence = (
        "high"
        if status in {"submitted", "multiple_submissions"}
        else "medium"
        if status == "needs_review"
        else "none"
    )
    return SubmissionMatchRow(
        status=status,
        match_basis=basis,
        normalized_phone=normalized_phone,
        recipient_ids=tuple(recipient.id for recipient in source_recipients),
        submission_ids=(
            tuple(submission.id for submission in ordered_submissions)
            if status in {"submitted", "multiple_submissions"}
            else ()
        ),
        broadcast_ids=tuple(item[0] for item in broadcast_pairs),
        broadcast_names=tuple(item[1] for item in broadcast_pairs),
        recipient_names=recipient_names,
        submission_names=tuple(submission.name for submission in ordered_submissions),
        updated_at=max(timestamps, key=_timestamp_key),
        confidence=confidence,
        match_evidence=all_evidence,
        candidate_submission_ids=tuple(sorted(candidate_submission_ids, key=str)),
        recipient_fields=_row_shared_fields(logical_recipient),
    )


def _unmatched_submission_row(
    submission: SubmissionForComparison,
    profile: _IdentityProfile,
) -> SubmissionMatchRow:
    return SubmissionMatchRow(
        status="unmatched_submission",
        match_basis=None,
        normalized_phone=next(iter(sorted(profile.phones)), None),
        recipient_ids=(),
        submission_ids=(submission.id,),
        broadcast_ids=(),
        broadcast_names=(),
        recipient_names=(),
        submission_names=(submission.name,),
        updated_at=submission.updated_at,
        confidence="none",
    )


def summarize_match_rows(
    rows: list[SubmissionMatchRow],
) -> SubmissionMatchSummary:
    """Summarize logical recipients and unassigned submission diagnostics."""

    recipient_rows = [row for row in rows if row.recipient_ids]
    matched_ids = {
        submission_id
        for row in recipient_rows
        if row.status in {"submitted", "multiple_submissions", "replacement"}
        for submission_id in row.submission_ids
    }
    needs_review_ids = {
        submission_id
        for row in recipient_rows
        if row.status == "needs_review"
        for submission_id in row.candidate_submission_ids
    }
    unmatched_ids = {
        submission_id
        for row in rows
        if row.status == "unmatched_submission"
        for submission_id in row.submission_ids
    }
    return SubmissionMatchSummary(
        total_recipients=len(recipient_rows),
        submitted_count=sum(
            row.status in {"submitted", "multiple_submissions", "replacement"}
            for row in recipient_rows
        ),
        not_submitted_count=sum(row.status == "not_submitted" for row in recipient_rows),
        multiple_submission_count=sum(
            row.status == "multiple_submissions" for row in recipient_rows
        ),
        matched_submission_count=len(matched_ids),
        needs_review_count=sum(row.status == "needs_review" for row in recipient_rows),
        needs_review_submission_count=len(needs_review_ids),
        unmatched_submission_count=len(unmatched_ids),
        replacement_count=sum(row.status == "replacement" for row in recipient_rows),
        rejected_upload_count=sum(row.status == "rejected_upload" for row in rows),
    )


def compare_group_submissions(
    recipients: list[RecipientForComparison],
    submissions: list[SubmissionForComparison],
) -> tuple[list[SubmissionMatchRow], SubmissionMatchSummary]:
    """Compare recipients and submissions with deterministic one-to-one ownership."""

    logical_recipients = _logical_recipients(recipients)
    ordered_submissions = sorted(submissions, key=_submission_sort_key)
    submission_profiles = [_submission_profile(submission) for submission in ordered_submissions]
    unique_names = _unique_compound_names(
        logical_recipients,
        submission_profiles,
    )
    evidence_indexes = _submission_evidence_indexes(submission_profiles)

    pairs: list[_PairEvidence] = []
    for recipient_index, recipient in enumerate(logical_recipients):
        candidate_indexes = _candidate_submission_indexes(
            recipient.profile,
            evidence_indexes,
        )
        for submission_index in sorted(candidate_indexes):
            submission = ordered_submissions[submission_index]
            profile = submission_profiles[submission_index]
            pair = _pair_evidence(
                recipient_index=recipient_index,
                recipient=recipient,
                submission_index=submission_index,
                submission=submission,
                submission_profile=profile,
                unique_compound_names=unique_names,
            )
            if pair:
                pairs.append(pair)

    pairs_by_recipient: dict[int, list[_PairEvidence]] = defaultdict(list)
    auto_pairs_by_submission: dict[int, list[_PairEvidence]] = defaultdict(list)
    for pair in pairs:
        pairs_by_recipient[pair.recipient_index].append(pair)
        if pair.auto_match:
            auto_pairs_by_submission[pair.submission_index].append(pair)

    assigned_pairs: dict[int, list[_PairEvidence]] = defaultdict(list)
    conflicted_pairs: dict[int, list[_PairEvidence]] = defaultdict(list)
    for submission_index, candidates in auto_pairs_by_submission.items():
        if len(candidates) == 1:
            assigned_pairs[candidates[0].recipient_index].append(candidates[0])
        else:
            # Any strong identity collision across logical recipients is
            # reviewable. Extra name evidence must never numerically override
            # a contradictory phone/email/passport/staff identifier.
            for candidate in candidates:
                conflicted_pairs[candidate.recipient_index].append(candidate)

    owned_submission_indexes = {
        pair.submission_index
        for recipient_pairs in assigned_pairs.values()
        for pair in recipient_pairs
    }
    rows: list[SubmissionMatchRow] = []
    assigned_submission_indexes: set[int] = set()
    candidate_submission_indexes: set[int] = set()
    for recipient_index, recipient in enumerate(logical_recipients):
        assigned = sorted(
            assigned_pairs.get(recipient_index, []),
            key=lambda pair: _submission_sort_key(ordered_submissions[pair.submission_index]),
        )
        potential = pairs_by_recipient.get(recipient_index, [])
        potential = [
            pair
            for pair in potential
            if (pair.submission_index not in owned_submission_indexes or pair in assigned)
        ]
        conflicts = conflicted_pairs.get(recipient_index, [])
        candidate_indexes = {
            pair.submission_index for pair in potential if not pair.auto_match or pair in conflicts
        }
        assigned_indexes = {pair.submission_index for pair in assigned}

        contradictory_assignments = len(assigned) > 1 and not _same_identity_basis(assigned)
        if contradictory_assignments:
            status = "needs_review"
            candidate_indexes.update(assigned_indexes)
            candidate_submission_indexes.update(assigned_indexes)
            candidate_submission_indexes.update(candidate_indexes)
            row_pairs = assigned + [pair for pair in potential if pair not in assigned]
            row_submissions = [ordered_submissions[index] for index in sorted(candidate_indexes)]
        elif assigned:
            assigned_submission_indexes.update(assigned_indexes)
            candidate_indexes = set()
            status = "multiple_submissions" if len(assigned) > 1 else "submitted"
            row_pairs = assigned
            row_submissions = [ordered_submissions[pair.submission_index] for pair in assigned]
        elif potential:
            status = "needs_review"
            candidate_indexes.update(pair.submission_index for pair in potential)
            candidate_submission_indexes.update(candidate_indexes)
            row_pairs = potential
            row_submissions = [ordered_submissions[index] for index in sorted(candidate_indexes)]
        else:
            status = "not_submitted"
            row_pairs = []
            row_submissions = []

        rows.append(
            _recipient_row(
                logical_recipient=recipient,
                status=status,
                submissions=row_submissions,
                matches=row_pairs,
                candidate_submission_ids={
                    ordered_submissions[index].id for index in candidate_indexes
                },
            )
        )

    for submission_index, (submission, profile) in enumerate(
        zip(ordered_submissions, submission_profiles, strict=True)
    ):
        if (
            submission_index not in assigned_submission_indexes
            and submission_index not in candidate_submission_indexes
        ):
            rows.append(_unmatched_submission_row(submission, profile))

    return rows, summarize_match_rows(rows)


def filter_and_sort_match_rows(
    rows: list[SubmissionMatchRow],
    *,
    status: str,
    sort_by: str,
    sort_order: str,
) -> list[SubmissionMatchRow]:
    filtered = rows if status == "all" else [row for row in rows if row.status == status]

    def name_key(row: SubmissionMatchRow) -> str | None:
        values = row.recipient_names or row.submission_names
        return values[0].casefold() if values else None

    def phone_key(row: SubmissionMatchRow) -> str | None:
        return row.normalized_phone

    def status_key(row: SubmissionMatchRow) -> str:
        return row.status

    def broadcast_key(row: SubmissionMatchRow) -> str | None:
        return row.broadcast_names[0].casefold() if row.broadcast_names else None

    key_functions = {
        "name": name_key,
        "phone": phone_key,
        "status": status_key,
        "broadcast": broadcast_key,
        "updated_at": lambda row: row.updated_at,
    }
    key_function = key_functions[sort_by]
    populated = [row for row in filtered if key_function(row) is not None]
    missing = [row for row in filtered if key_function(row) is None]
    populated.sort(
        key=lambda row: (
            key_function(row),
            str(row.recipient_ids),
            str(row.submission_ids),
        ),
        reverse=sort_order == "desc",
    )
    missing.sort(key=lambda row: (str(row.recipient_ids), str(row.submission_ids)))
    return populated + missing
