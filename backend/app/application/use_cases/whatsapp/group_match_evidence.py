"""Indexed exact comparison evidence and strict private-identity eligibility."""

from __future__ import annotations

import uuid
from collections import defaultdict

from app.application.use_cases.whatsapp.group_match_fields import (
    _NAME_EVIDENCE_WEIGHT,
    _PASSPORT_KEYS,
    _PRIVATE_SELECTED_FIELD_KEYS,
    _SELECTED_FIELD_EVIDENCE_WEIGHT,
    _STRONG_EVIDENCE_WEIGHTS,
)
from app.application.use_cases.whatsapp.group_match_normalization import (
    _mapping_values,
    _normalized_date,
    _normalized_identifier,
    _normalized_values,
)
from app.application.use_cases.whatsapp.group_match_profiles import _passport_fields
from app.application.use_cases.whatsapp.group_match_types import (
    MatchEvidence,
    SubmissionForComparison,
    _IdentityProfile,
    _LogicalRecipient,
    _PairEvidence,
)
from app.application.use_cases.whatsapp.group_submission_policy import (
    duplicate_passport_submission_ids,
)


def _evidence_item(
    *,
    submission_id: uuid.UUID,
    kind: str,
    recipient_values: frozenset[str],
    submission_values: frozenset[str],
    weight: int,
    preferred_values: frozenset[str] = frozenset(),
    association_values: frozenset[str] = frozenset(),
    private_identity_kind: bool | None = None,
) -> MatchEvidence | None:
    shared = sorted(recipient_values & submission_values)
    if not shared:
        return None
    # Evidence stores one representative value. For selected fields, prefer a
    # value that is unique on both sides so the persisted explanation reflects
    # the value that actually made the pair safe to auto-assign.
    association_value = next((item for item in shared if item in association_values), shared[0])
    value = next((item for item in shared if item in preferred_values), association_value)
    return MatchEvidence(
        submission_id=submission_id,
        kind=kind,
        recipient_value=value,
        submission_value=value,
        weight=weight,
        private_identity_confirmed=(
            None
            if private_identity_kind is None
            else private_identity_kind and value in preferred_values
        ),
    )


def _pair_evidence(
    *,
    recipient_index: int,
    recipient: _LogicalRecipient,
    submission_index: int,
    submission: SubmissionForComparison,
    submission_profile: _IdentityProfile,
    unique_compound_names: frozenset[str],
    unique_selected_values: frozenset[tuple[str, str]],
    roster_unique_selected_values: frozenset[tuple[str, str]],
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
    for field_key, recipient_values in sorted(recipient.profile.selected_fields.items()):
        unique_values = frozenset(
            value for value in recipient_values if (field_key, value) in unique_selected_values
        )
        item = _evidence_item(
            submission_id=submission.id,
            kind=field_key,
            recipient_values=recipient_values,
            submission_values=submission_profile.selected_fields.get(
                field_key,
                frozenset(),
            ),
            weight=_SELECTED_FIELD_EVIDENCE_WEIGHT,
            preferred_values=unique_values,
            association_values=frozenset(
                value for value in recipient_values
                if (field_key, value) in roster_unique_selected_values
            ),
            private_identity_kind=field_key in _PRIVATE_SELECTED_FIELD_KEYS,
        )
        if item is not None:
            evidence.append(item)
    if not evidence:
        return None
    # A selected heading may canonicalize to a legacy evidence name such as
    # ``email`` or ``staff_code``. Determine legacy strength from its dedicated
    # profile, not the display kind. Roster association may use roster-only
    # uniqueness; private evidence above still requires uniqueness on both sides.
    strong = any(
        (
            bool(recipient.profile.phones & submission_profile.phones),
            bool(recipient.profile.emails & submission_profile.emails),
            bool(recipient.profile.passport_numbers & submission_profile.passport_numbers),
            bool(recipient.profile.staff_codes & submission_profile.staff_codes),
        )
    )
    selected = any(
        item.kind in recipient.profile.selected_fields
        and (
            (item.kind, item.recipient_value) in unique_selected_values
            or (item.kind, item.recipient_value) in roster_unique_selected_values
        )
        for item in evidence
    )
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
        auto_match=strong or selected or unique_compound,
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
    dict[str, dict[str, set[int]]],
]:
    """Invert exact evidence once instead of scanning every recipient/submission pair."""

    phones: dict[str, set[int]] = defaultdict(set)
    emails: dict[str, set[int]] = defaultdict(set)
    passports: dict[str, set[int]] = defaultdict(set)
    staff_codes: dict[str, set[int]] = defaultdict(set)
    names: dict[str, set[int]] = defaultdict(set)
    selected_fields: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
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
        for field_key, values in profile.selected_fields.items():
            for value in values:
                selected_fields[field_key][value].add(index)
    return phones, emails, passports, staff_codes, names, selected_fields


def _duplicate_submission_ids(
    submissions: list[SubmissionForComparison],
) -> tuple[uuid.UUID, ...]:
    identities: list[tuple[uuid.UUID, frozenset[str], str | None]] = []
    for submission in submissions:
        fields = _passport_fields(submission)
        passports = _normalized_values(
            _mapping_values(fields, _PASSPORT_KEYS), _normalized_identifier,
        )
        birth_dates = _normalized_values([fields.get("date_of_birth")], _normalized_date)
        identities.append((submission.id, passports, next(iter(birth_dates), None)))
    return duplicate_passport_submission_ids(identities)


def _candidate_submission_indexes(
    profile: _IdentityProfile,
    evidence_indexes: tuple[
        dict[str, set[int]],
        dict[str, set[int]],
        dict[str, set[int]],
        dict[str, set[int]],
        dict[str, set[int]],
        dict[str, dict[str, set[int]]],
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
    for field_key, values in profile.selected_fields.items():
        index = evidence_indexes[5].get(field_key, {})
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
            or item.weight == _SELECTED_FIELD_EVIDENCE_WEIGHT
        }
        for match in matches
    ]
    common = set.intersection(*evidence_sets) if evidence_sets else set()
    return bool(common)
