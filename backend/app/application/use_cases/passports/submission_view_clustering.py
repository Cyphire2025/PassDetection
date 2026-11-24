"""Roster view clustering with explicit projection boundaries."""

from __future__ import annotations

from typing import Any

from app.domain.value_objects.passport_fields import canonical_country_identity

from .submission_view_fields import (
    _cluster_id,
    _field_value,
    _normalized_identifier,
    _passport_name,
    _place_of_issue_identity,
    _verification_confidence,
)
from .submission_view_types import SubmissionViewEntry


def _build_blocks(
    submissions: list[Any],
) -> list[list[SubmissionViewEntry]]:
    if not submissions:
        return []
    parents = list(range(len(submissions)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    evidence: list[tuple[str, str, str | None]] = []
    primary_indexes: dict[str, int] = {}
    fallback_buckets: dict[str, list[int]] = {}
    for index, submission in enumerate(submissions):
        passport_number = _normalized_identifier(_field_value(submission, "passport_number"))
        place_of_issue = _place_of_issue_identity(submission)
        primary = (
            f"{passport_number}:{place_of_issue}" if passport_number and place_of_issue else None
        )
        name = _passport_name(submission)
        birth = _normalized_identifier(_field_value(submission, "date_of_birth"))
        nationality_value = _field_value(submission, "nationality")
        nationality = canonical_country_identity(nationality_value) if nationality_value else ""
        fallback = f"{name}:{birth}:{nationality}" if name and birth and nationality else None
        evidence.append((passport_number, place_of_issue, fallback))
        if primary:
            previous = primary_indexes.setdefault(primary, index)
            union(previous, index)
        if fallback:
            fallback_buckets.setdefault(fallback, []).append(index)

    # Fallback clustering is limited to rows whose primary identity is
    # incomplete. A complete row can join a place-missing row only when the
    # passport number and demographic fallback both corroborate.
    for indexes in fallback_buckets.values():
        # Partition incomplete evidence in linear time. Equal passport numbers
        # form a component; an unnumbered row connects the incomplete components
        # exactly as the former pairwise algorithm did. Complete primary rows
        # still need the corroboration below, preserving conflict boundaries.
        incomplete_by_passport: dict[str, list[int]] = {}
        for index in indexes:
            passport_number, place, _ = evidence[index]
            if not (passport_number and place):
                incomplete_by_passport.setdefault(passport_number, []).append(index)
        for incomplete_members in incomplete_by_passport.values():
            for index in incomplete_members[1:]:
                union(incomplete_members[0], index)
        unnumbered = incomplete_by_passport.get("")
        if unnumbered:
            for incomplete_members in incomplete_by_passport.values():
                union(unnumbered[0], incomplete_members[0])

        # A place-missing row may bridge to a complete primary row only
        # when this corroborated passport+fallback bucket contains exactly
        # one complete place. Never bridge conflicting complete places.
        by_passport: dict[str, list[int]] = {}
        for index in indexes:
            passport_number, _, _ = evidence[index]
            if passport_number:
                by_passport.setdefault(passport_number, []).append(index)
        for passport_indexes in by_passport.values():
            complete_places = {
                evidence[index][1] for index in passport_indexes if evidence[index][1]
            }
            if len(complete_places) == 1:
                anchor = passport_indexes[0]
                for index in passport_indexes[1:]:
                    union(anchor, index)

    grouped: dict[int, list[Any]] = {}
    for index, submission in enumerate(submissions):
        grouped.setdefault(find(index), []).append(submission)
    blocks: list[list[SubmissionViewEntry]] = []
    for members in grouped.values():
        ordered_members = sorted(members, key=lambda item: str(item.id))
        member_ids = tuple(member.id for member in ordered_members)
        is_duplicate = len(ordered_members) > 1
        cluster_id = _cluster_id(member_ids) if is_duplicate else None
        blocks.append(
            [
                SubmissionViewEntry(
                    submission=member,
                    duplicate_cluster_id=cluster_id,
                    duplicate_cluster_size=len(ordered_members),
                    duplicate_cluster_member_ids=member_ids,
                    verification_confidence=_verification_confidence(member),
                )
                for member in ordered_members
            ]
        )
    return blocks
