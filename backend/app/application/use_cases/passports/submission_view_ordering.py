"""Roster view ordering with explicit projection boundaries."""

from __future__ import annotations

from typing import Any

from .submission_view_fields import _display_name, _normalized_tokens
from .submission_view_types import SubmissionViewEntry


def _matches_search(entry: SubmissionViewEntry, search: str) -> bool:
    return _matches_normalized_search(entry, _normalized_tokens(search))


def _matches_normalized_search(entry: SubmissionViewEntry, needle: str) -> bool:
    submission = entry.submission
    values: list[Any] = [
        getattr(submission, "display_name", None),
        submission.client_name,
        submission.client_email,
        submission.client_phone,
        submission.family_head_name,
        submission.family_head_email,
        submission.family_head_phone,
        submission.departure_city,
    ]
    values.extend((submission.confirmed_fields or {}).values())
    values.extend((submission.extracted_fields or {}).values())
    values.extend((getattr(submission, "staff_metadata", None) or {}).values())
    return any(
        needle in _normalized_tokens(value)
        for value in values
        if isinstance(value, (str, int, float))
    )


def _status_matches(entry: SubmissionViewEntry, submission_filter: str) -> bool:
    if submission_filter == "all":
        return True
    if submission_filter == "document_follow_up":
        return bool(getattr(entry.submission, "document_follow_up", False))
    status_map = {
        "pending_ai": "submitted",
        "ai_approved": "ai_approved",
        "needs_review": "needs_review",
        "staff_approved": "staff_approved",
    }
    return bool(entry.submission.status == status_map.get(submission_filter))


def _sort_value(entry: SubmissionViewEntry, sort_by: str) -> Any:
    if sort_by == "name":
        return _normalized_tokens(_display_name(entry.submission)) or None
    if sort_by == "verification_confidence":
        return entry.verification_confidence
    return entry.submission.updated_at


def _sort_entries(
    entries: list[SubmissionViewEntry],
    *,
    sort_by: str,
    sort_order: str,
) -> list[SubmissionViewEntry]:
    # Tie breakers remain ascending regardless of the primary direction.
    entries = sorted(
        entries,
        key=lambda entry: (
            _normalized_tokens(_display_name(entry.submission)),
            str(entry.submission.id),
        ),
    )
    populated: list[SubmissionViewEntry] = []
    missing: list[SubmissionViewEntry] = []
    for entry in entries:
        if _sort_value(entry, sort_by) is None:
            missing.append(entry)
        else:
            populated.append(entry)
    populated.sort(
        key=lambda entry: _sort_value(entry, sort_by),
        reverse=sort_order == "desc",
    )
    return populated + missing


def _sort_blocks(
    blocks: list[list[SubmissionViewEntry]],
    *,
    sort_by: str,
    sort_order: str,
) -> list[list[SubmissionViewEntry]]:
    ordered_blocks = [
        _sort_entries(list(block), sort_by=sort_by, sort_order=sort_order) for block in blocks
    ]
    ordered_blocks.sort(
        key=lambda block: block[0].duplicate_cluster_id or str(block[0].submission.id)
    )
    populated: list[list[SubmissionViewEntry]] = []
    missing: list[list[SubmissionViewEntry]] = []
    for block in ordered_blocks:
        if _sort_value(block[0], sort_by) is None:
            missing.append(block)
        else:
            populated.append(block)
    populated.sort(
        key=lambda block: _sort_value(block[0], sort_by),
        reverse=sort_order == "desc",
    )
    return populated + missing
