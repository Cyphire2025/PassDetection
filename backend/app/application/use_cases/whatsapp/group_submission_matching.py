"""Deterministic comparison of linked WhatsApp recipients and submissions.

Names are intentionally display-only. Identity matching is limited to the
canonical phone normalization used by WhatsApp contact import.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from app.application.use_cases.whatsapp.contact_normalization import (
    clean_whatsapp_name,
    normalize_whatsapp_phone,
)


@dataclass(frozen=True)
class RecipientForComparison:
    id: uuid.UUID
    broadcast_id: uuid.UUID
    broadcast_name: str
    name: str | None
    phone: str | None
    updated_at: datetime


@dataclass(frozen=True)
class SubmissionForComparison:
    id: uuid.UUID
    name: str
    client_phone: str | None
    family_head_phone: str | None
    updated_at: datetime


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


@dataclass(frozen=True)
class SubmissionMatchSummary:
    total_recipients: int
    submitted_count: int
    not_submitted_count: int
    multiple_submission_count: int
    matched_submission_count: int


def summarize_match_rows(
    rows: list[SubmissionMatchRow],
) -> SubmissionMatchSummary:
    """Summarize an already-selected set of logical recipient rows."""

    return SubmissionMatchSummary(
        total_recipients=len(rows),
        submitted_count=sum(
            row.status in {"submitted", "multiple_submissions"}
            for row in rows
        ),
        not_submitted_count=sum(
            row.status == "not_submitted" for row in rows
        ),
        multiple_submission_count=sum(
            row.status == "multiple_submissions" for row in rows
        ),
        matched_submission_count=len(
            {
                submission_id
                for row in rows
                for submission_id in row.submission_ids
            }
        ),
    )


def _recipient_sort_key(recipient: RecipientForComparison) -> tuple[str, str]:
    return (str(recipient.broadcast_id), str(recipient.id))


def _submission_sort_key(
    submission: SubmissionForComparison,
) -> tuple[datetime, str]:
    return (submission.updated_at, str(submission.id))


def compare_group_submissions(
    recipients: list[RecipientForComparison],
    submissions: list[SubmissionForComparison],
) -> tuple[list[SubmissionMatchRow], SubmissionMatchSummary]:
    """Build one logical-recipient row per canonical phone.

    A WhatsApp phone repeated across linked broadcasts remains one logical
    recipient while every source broadcast and recipient row is retained.
    Submission phone fields are re-normalized here, including bare Indian
    ten-digit values, and both member and family-head phone fields participate.
    """

    recipient_groups: dict[str, list[RecipientForComparison]] = defaultdict(list)
    for recipient in recipients:
        normalized = normalize_whatsapp_phone(recipient.phone)
        # Invalid legacy recipient rows cannot be merged safely.
        key = normalized or f"invalid:{recipient.id}"
        recipient_groups[key].append(recipient)

    submissions_by_phone: dict[str, list[SubmissionForComparison]] = defaultdict(list)
    for submission in submissions:
        phones = {
            normalized
            for value in (submission.client_phone, submission.family_head_phone)
            if (normalized := normalize_whatsapp_phone(value))
        }
        for phone in phones:
            submissions_by_phone[phone].append(submission)

    rows: list[SubmissionMatchRow] = []
    for phone_key in sorted(recipient_groups):
        logical_recipients = sorted(
            recipient_groups[phone_key], key=_recipient_sort_key
        )
        normalized_phone = (
            None if phone_key.startswith("invalid:") else phone_key
        )
        matched = sorted(
            {
                submission.id: submission
                for submission in submissions_by_phone.get(
                    normalized_phone or "", []
                )
            }.values(),
            key=_submission_sort_key,
        )
        if not matched:
            row_status = "not_submitted"
        elif len(matched) == 1:
            row_status = "submitted"
        else:
            row_status = "multiple_submissions"

        recipient_names = tuple(
            sorted(
                {
                    name
                    for recipient in logical_recipients
                    if (name := clean_whatsapp_name(recipient.name))
                },
                key=str.casefold,
            )
        )
        broadcast_pairs = sorted(
            {
                (recipient.broadcast_id, recipient.broadcast_name)
                for recipient in logical_recipients
            },
            key=lambda item: (item[1].casefold(), str(item[0])),
        )
        updated_at = max(
            [
                recipient.updated_at for recipient in logical_recipients
            ]
            + [submission.updated_at for submission in matched]
        )
        rows.append(
            SubmissionMatchRow(
                status=row_status,
                match_basis="phone" if matched else None,
                normalized_phone=normalized_phone,
                recipient_ids=tuple(
                    recipient.id for recipient in logical_recipients
                ),
                submission_ids=tuple(submission.id for submission in matched),
                broadcast_ids=tuple(item[0] for item in broadcast_pairs),
                broadcast_names=tuple(item[1] for item in broadcast_pairs),
                recipient_names=recipient_names,
                submission_names=tuple(
                    submission.name for submission in matched
                ),
                updated_at=updated_at,
            )
        )

    return rows, summarize_match_rows(rows)


def filter_and_sort_match_rows(
    rows: list[SubmissionMatchRow],
    *,
    status: str,
    sort_by: str,
    sort_order: str,
) -> list[SubmissionMatchRow]:
    filtered = rows if status == "all" else [
        row for row in rows if row.status == status
    ]

    def name_key(row: SubmissionMatchRow) -> str | None:
        values = row.recipient_names or row.submission_names
        return values[0].casefold() if values else None

    def phone_key(row: SubmissionMatchRow) -> str | None:
        return row.normalized_phone

    def status_key(row: SubmissionMatchRow) -> str:
        return row.status

    def broadcast_key(row: SubmissionMatchRow) -> str | None:
        return (
            row.broadcast_names[0].casefold()
            if row.broadcast_names
            else None
        )

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
        key=lambda row: (key_function(row), str(row.recipient_ids), str(row.submission_ids)),
        reverse=sort_order == "desc",
    )
    missing.sort(key=lambda row: (str(row.recipient_ids), str(row.submission_ids)))
    return populated + missing
