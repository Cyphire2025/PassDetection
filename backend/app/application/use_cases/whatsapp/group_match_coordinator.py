"""Resolve indexed roster evidence with deterministic ownership and review rules."""

from __future__ import annotations

import uuid
from collections import defaultdict

from app.application.use_cases.whatsapp.group_match_evidence import (
    _candidate_submission_indexes,
    _duplicate_submission_ids,
    _pair_evidence,
    _same_identity_basis,
    _submission_evidence_indexes,
    _unique_compound_names,
)
from app.application.use_cases.whatsapp.group_match_profiles import (
    _logical_recipients,
    _submission_profile,
    _submission_sort_key,
)
from app.application.use_cases.whatsapp.group_match_rows import (
    _recipient_row,
    _unmatched_submission_row,
    summarize_match_rows,
)
from app.application.use_cases.whatsapp.group_match_types import (
    RecipientForComparison,
    SubmissionForComparison,
    SubmissionMatchRow,
    SubmissionMatchSummary,
    _PairEvidence,
)
from app.application.use_cases.whatsapp.group_submission_policy import (
    selected_field_value_uniqueness,
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
    unique_selected, roster_unique_selected = selected_field_value_uniqueness(
        (recipient.profile.selected_fields for recipient in logical_recipients),
        (profile.selected_fields for profile in submission_profiles),
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
                unique_selected_values=unique_selected,
                roster_unique_selected_values=roster_unique_selected,
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

        selected_party = any(
            item.kind in recipient.profile.selected_fields
            and (item.kind, item.recipient_value) in roster_unique_selected
            for pair in assigned for item in pair.evidence
        )
        unresolved_selected_candidates = any(
            pair.submission_index in candidate_indexes
            and any(
                item.kind in recipient.profile.selected_fields
                and item.kind not in {"name", "phone_number"}
                for item in pair.evidence
            )
            for pair in potential
        )
        contradictory_assignments = (
            len(assigned) > 1 and not selected_party and not _same_identity_basis(assigned)
        )
        duplicate_ids: tuple[uuid.UUID, ...] = ()
        if contradictory_assignments or (assigned and unresolved_selected_candidates):
            status = "needs_review"
            candidate_indexes.update(assigned_indexes)
            candidate_submission_indexes.update(assigned_indexes)
            candidate_submission_indexes.update(candidate_indexes)
            row_pairs = assigned + [pair for pair in potential if pair not in assigned]
            row_submissions = [ordered_submissions[index] for index in sorted(candidate_indexes)]
        elif assigned:
            assigned_submission_indexes.update(assigned_indexes)
            candidate_indexes = set()
            row_pairs = assigned
            row_submissions = [ordered_submissions[pair.submission_index] for pair in assigned]
            duplicate_ids = _duplicate_submission_ids(row_submissions)
            status = "multiple_submissions" if duplicate_ids else "submitted"
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
                duplicate_submission_ids=duplicate_ids,
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
