"""Deterministic roster matching result rows, counts and ordering."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime

from app.application.use_cases.whatsapp.contact_normalization import (
    clean_whatsapp_name,
    normalize_whatsapp_phone,
)
from app.application.use_cases.whatsapp.group_match_profiles import (
    _submission_sort_key,
    _timestamp_key,
)
from app.application.use_cases.whatsapp.group_match_types import (
    RecipientFieldSet,
    SubmissionForComparison,
    SubmissionMatchRow,
    SubmissionMatchSummary,
    _IdentityProfile,
    _LogicalRecipient,
    _PairEvidence,
)


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
    duplicate_submission_ids: tuple[uuid.UUID, ...] = (),
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
    # The matching profile intentionally omits unselected phone evidence for an
    # explicit policy. Row display and delivery diagnostics still need the
    # actual normalized roster destination without making it match evidence.
    normalized_phone = next(
        iter(
            sorted(
                {
                    phone
                    for recipient in source_recipients
                    if (phone := normalize_whatsapp_phone(recipient.phone))
                }
            )
        ),
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
        duplicate_submission_ids=duplicate_submission_ids,
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

    key_functions: dict[
        str,
        Callable[[SubmissionMatchRow], str | datetime | None],
    ] = {
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
