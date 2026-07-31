"""Full-group filtering, duplicate clustering, sorting, and pagination."""

from __future__ import annotations

import calendar
import math
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from app.domain.value_objects.passport_fields import canonical_country_identity


@dataclass(frozen=True)
class SubmissionViewEntry:
    submission: Any
    duplicate_cluster_id: str | None
    duplicate_cluster_size: int
    duplicate_cluster_member_ids: tuple[uuid.UUID, ...]
    verification_confidence: float | None


@dataclass(frozen=True)
class ExpiryAlert:
    submission_id: uuid.UUID
    client_name: str
    client_email: str | None
    passport_number: str | None
    date_of_expiry: str
    status: str


@dataclass(frozen=True)
class SubmissionViewResult:
    items: tuple[SubmissionViewEntry, ...]
    ordered_submission_ids: tuple[uuid.UUID, ...]
    group_total: int
    total: int
    page: int
    page_size: int
    total_pages: int
    returned_count: int
    expiry_alerts: tuple[ExpiryAlert, ...]


def _normalized_tokens(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(token for token in re.split(r"[^\w]+", text) if token)


def _normalized_identifier(value: Any) -> str:
    return "".join(character for character in _normalized_tokens(value) if character.isalnum())


def _field_value(submission: Any, field: str) -> str:
    confirmed = submission.confirmed_fields or {}
    extracted = submission.extracted_fields or {}
    # An explicit reviewed blank (notably surname) is authoritative.
    if field in confirmed:
        value = confirmed.get(field)
    else:
        value = extracted.get(field)
    return str(value).strip() if value is not None else ""


def _passport_name(submission: Any) -> str:
    components = [
        _field_value(submission, "given_names"),
        _field_value(submission, "surname"),
    ]
    passport_name = _normalized_tokens(" ".join(component for component in components if component))
    if passport_name:
        return passport_name
    return _normalized_tokens(submission.client_name)


def _place_of_issue_identity(submission: Any) -> str:
    confirmed = submission.confirmed_fields or {}
    extracted = submission.extracted_fields or {}
    if "place_of_issue" in confirmed or "place_of_issue" in extracted:
        return _normalized_identifier(_field_value(submission, "place_of_issue"))

    # Preserve country-code/name equivalence for old records whose JSON used
    # the previous field. New records use the visibly printed place text.
    legacy_value = _field_value(submission, "issuing_country")
    return canonical_country_identity(legacy_value) if legacy_value else ""


def duplicate_identity_key(submission: Any) -> str | None:
    """Prefer passport+place of issue, with a cautious demographic fallback."""

    passport_number = _normalized_identifier(_field_value(submission, "passport_number"))
    place_of_issue = _place_of_issue_identity(submission)
    if passport_number and place_of_issue:
        return f"passport:{passport_number}:{place_of_issue}"

    name = _passport_name(submission)
    date_of_birth = _normalized_identifier(_field_value(submission, "date_of_birth"))
    nationality_value = _field_value(submission, "nationality")
    nationality = canonical_country_identity(nationality_value) if nationality_value else ""
    if name and date_of_birth and nationality:
        return f"fallback:{name}:{date_of_birth}:{nationality}"
    return None


def _cluster_id(member_ids: tuple[uuid.UUID, ...]) -> str:
    # Submission UUIDs are already response identifiers and avoid deriving a
    # correlatable token from passport or demographic PII.
    return f"dup_{member_ids[0].hex}"


def _verification_confidence(submission: Any) -> float | None:
    verification = submission.post_submission_verification
    verification_usable = True
    if isinstance(verification, dict):
        fields = verification.get("fields")
        if isinstance(fields, list):
            for field in fields:
                if not isinstance(field, dict):
                    continue
                confidence = field.get("confidence")
                if (
                    not isinstance(confidence, (int, float))
                    or isinstance(confidence, bool)
                    or confidence <= 0
                ):
                    continue
                observed_value = str(field.get("observed_value") or "").strip()
                reason_code = str(field.get("reason_code") or "").strip().casefold()
                if not observed_value or reason_code in {"unreadable", "missing_submitted_value"}:
                    verification_usable = False
                    break
        value = verification.get("confidence")
        if (
            verification_usable
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        ):
            return float(value)
    value = submission.overall_confidence
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    ):
        return float(value)
    return None


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
    # incomplete. Keep this pass linear in the bucket size: large incentive
    # groups can contain thousands of people with the same demographic
    # fallback, so comparing every pair would make each page request O(n^2).
    #
    # Blank-passport rows are intentionally kept separate when more than one
    # non-blank passport is present. Otherwise a single incomplete row could
    # transitively merge contradictory passport identities.
    for indexes in fallback_buckets.values():
        incomplete_by_passport: dict[str, list[int]] = {}
        blank_passport_indexes: list[int] = []
        nonblank_passports = {
            evidence[index][0] for index in indexes if evidence[index][0]
        }
        for index in indexes:
            passport_number, place_of_issue, _ = evidence[index]
            if passport_number and place_of_issue:
                continue
            if passport_number:
                incomplete_by_passport.setdefault(passport_number, []).append(index)
            else:
                blank_passport_indexes.append(index)

        for passport_indexes in incomplete_by_passport.values():
            anchor = passport_indexes[0]
            for index in passport_indexes[1:]:
                union(anchor, index)

        if blank_passport_indexes:
            blank_anchor = blank_passport_indexes[0]
            for index in blank_passport_indexes[1:]:
                union(blank_anchor, index)
            if (
                len(nonblank_passports) == 1
                and len(incomplete_by_passport) == 1
            ):
                passport_anchor = next(iter(incomplete_by_passport.values()))[0]
                union(passport_anchor, blank_anchor)

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


def _matches_search(entry: SubmissionViewEntry, search: str) -> bool:
    submission = entry.submission
    values: list[Any] = [
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
    needle = _normalized_tokens(search)
    return any(
        needle in _normalized_tokens(value)
        for value in values
        if isinstance(value, (str, int, float))
    )


def _status_matches(entry: SubmissionViewEntry, submission_filter: str) -> bool:
    if submission_filter == "all":
        return True
    status_map = {
        "pending_ai": "submitted",
        "ai_approved": "ai_approved",
        "needs_review": "needs_review",
        "staff_approved": "staff_approved",
    }
    return bool(entry.submission.status == status_map.get(submission_filter))


def _sort_value(entry: SubmissionViewEntry, sort_by: str) -> Any:
    if sort_by == "name":
        return _normalized_tokens(entry.submission.client_name) or None
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
            _normalized_tokens(entry.submission.client_name),
            str(entry.submission.id),
        ),
    )
    populated = [entry for entry in entries if _sort_value(entry, sort_by) is not None]
    missing = [entry for entry in entries if _sort_value(entry, sort_by) is None]
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
    populated = [block for block in ordered_blocks if _sort_value(block[0], sort_by) is not None]
    missing = [block for block in ordered_blocks if _sort_value(block[0], sort_by) is None]
    populated.sort(
        key=lambda block: _sort_value(block[0], sort_by),
        reverse=sort_order == "desc",
    )
    return populated + missing


def _paginate_blocks(
    blocks: list[list[SubmissionViewEntry]],
    page_size: int,
) -> list[list[SubmissionViewEntry]]:
    pages: list[list[SubmissionViewEntry]] = []
    current: list[SubmissionViewEntry] = []
    for block in blocks:
        if current and len(current) + len(block) > page_size:
            pages.append(current)
            current = []
        current.extend(block)
        if len(current) >= page_size:
            pages.append(current)
            current = []
    if current:
        pages.append(current)
    return pages


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _expiry_alerts(
    submissions: list[Any],
    *,
    today: date,
    travel_date: date | None,
) -> tuple[ExpiryAlert, ...]:
    warning_date = _add_months(travel_date or today, 6)
    alerts: list[ExpiryAlert] = []
    for submission in submissions:
        expiry_text = _field_value(submission, "date_of_expiry")
        try:
            expiry = date.fromisoformat(expiry_text)
        except (TypeError, ValueError):
            continue
        is_expired = expiry < today
        if not is_expired and expiry > warning_date:
            continue
        alerts.append(
            ExpiryAlert(
                submission_id=submission.id,
                client_name=submission.client_name,
                client_email=submission.client_email,
                passport_number=(_field_value(submission, "passport_number") or None),
                date_of_expiry=expiry.isoformat(),
                status="expired" if is_expired else "near_expiry",
            )
        )
    return tuple(
        sorted(
            alerts,
            key=lambda alert: (
                alert.date_of_expiry,
                _normalized_tokens(alert.client_name),
                str(alert.submission_id),
            ),
        )
    )


def build_submission_view(
    submissions: list[Any],
    *,
    submission_filter: str,
    sort_by: str,
    sort_order: str,
    search: str | None,
    page: int,
    page_size: int,
    today: date | None = None,
    travel_date: date | None = None,
) -> SubmissionViewResult:
    """Apply full-group identity logic before filters and block pagination."""

    blocks = _build_blocks(submissions)
    normalized_search = (search or "").strip()
    if normalized_search:
        blocks = [
            block
            for block in blocks
            if any(_matches_search(entry, normalized_search) for entry in block)
        ]

    if submission_filter == "duplicates":
        blocks = [block for block in blocks if block[0].duplicate_cluster_id is not None]
    elif submission_filter != "all":
        # Search may select a whole cluster, but status filters remain
        # truthful at member level while retaining full cluster metadata.
        blocks = [
            matching
            for block in blocks
            if (matching := [entry for entry in block if _status_matches(entry, submission_filter)])
        ]

    blocks = _sort_blocks(blocks, sort_by=sort_by, sort_order=sort_order)
    ordered_submission_ids = tuple(
        entry.submission.id
        for block in blocks
        for entry in block
    )
    total = sum(len(block) for block in blocks)
    pages = _paginate_blocks(blocks, page_size)
    page_items = pages[page - 1] if page <= len(pages) else []
    return SubmissionViewResult(
        items=tuple(page_items),
        ordered_submission_ids=ordered_submission_ids,
        group_total=len(submissions),
        total=total,
        page=page,
        page_size=page_size,
        total_pages=len(pages),
        returned_count=len(page_items),
        expiry_alerts=_expiry_alerts(
            submissions,
            today=today or datetime.now(tz=UTC).date(),
            travel_date=travel_date,
        ),
    )
