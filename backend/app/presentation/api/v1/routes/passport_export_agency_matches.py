"""Unambiguous agency/dealership matching and effective export projection."""

from __future__ import annotations

import unicodedata
import uuid
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import cache
from typing import Any

from app.application.use_cases.whatsapp.group_submission_matching import (
    SubmissionMatchRow,
)
from app.domain.entities.entities import PassportSubmission
from app.presentation.api.v1.routes.passport_export_recipient_values import (
    _WHATSAPP_EMAIL_IMPORTED_KEYS,
    _WHATSAPP_PHONE_IMPORTED_KEYS,
    _recipient_export_value,
    _recipient_old_given_name,
)

_AGENCY_MATCH_SIMILARITY_THRESHOLD = 0.90


@dataclass(frozen=True)
class _AgencyExportMatches:
    rows_by_submission: dict[uuid.UUID, SubmissionMatchRow]
    matched_recipient_ids: frozenset[uuid.UUID]


def _normalized_agency_match_value(value: Any) -> str:
    compatible = unicodedata.normalize("NFKC", str(value or "")).casefold()
    compatible = compatible.replace("&", " and ")
    normalized = "".join(character if character.isalnum() else " " for character in compatible)
    return " ".join(normalized.split())


def _agency_match_similarity(left: Any, right: Any) -> float:
    return _normalized_agency_match_similarity(
        _normalized_agency_match_value(left), _normalized_agency_match_value(right)
    )


def _normalized_agency_match_similarity(normalized_left: str, normalized_right: str) -> float:
    if not normalized_left or not normalized_right:
        return 0.0
    compact_left = normalized_left.replace(" ", "")
    compact_right = normalized_right.replace(" ", "")
    if compact_left == compact_right:
        return 1.0
    if min(len(compact_left), len(compact_right)) < 4:
        return 0.0
    maximum_possible = (
        2 * min(len(compact_left), len(compact_right)) / (len(compact_left) + len(compact_right))
    )
    if maximum_possible < _AGENCY_MATCH_SIMILARITY_THRESHOLD:
        return 0.0
    return SequenceMatcher(
        None,
        compact_left,
        compact_right,
        autojunk=False,
    ).ratio()


def _submission_agency_dealership_name(
    submission: PassportSubmission,
) -> str | None:
    fields = dict(submission.extracted_fields or {})
    fields.update(submission.confirmed_fields or {})
    value = fields.get("agency_dealership_name") or (submission.staff_metadata or {}).get(
        "agency_dealership_name"
    )
    normalized = " ".join(str(value or "").strip().split())
    return normalized or None


def _export_agency_matches(
    submissions: list[PassportSubmission],
    rows_by_group: dict[uuid.UUID, list[SubmissionMatchRow]],
    agency_match_field: str,
) -> _AgencyExportMatches:
    """Resolve one unambiguous WhatsApp row per submitted agency value."""

    # One export owns this cache. Keep both original normalization passes;
    # compatibility Unicode normalization need not be assumed idempotent.
    @cache
    def normalized_value(value: str | None) -> str:
        return _normalized_agency_match_value(value)

    normalized_field = agency_match_field.removeprefix("whatsapp:")
    if not normalized_field or normalized_field == agency_match_field:
        return _AgencyExportMatches({}, frozenset())

    candidates_by_group: dict[
        uuid.UUID,
        list[tuple[str, SubmissionMatchRow]],
    ] = {}
    exact_rows_by_group: dict[
        uuid.UUID,
        dict[str, list[SubmissionMatchRow]],
    ] = {}
    for group_id, rows in rows_by_group.items():
        for row in rows:
            if not row.recipient_ids:
                continue
            imported_agency = _recipient_export_value(row, normalized_field)
            normalized_agency = normalized_value(imported_agency)
            if not normalized_agency:
                continue
            candidates_by_group.setdefault(group_id, []).append((normalized_agency, row))
            exact_rows_by_group.setdefault(group_id, {}).setdefault(
                normalized_agency.replace(" ", ""),
                [],
            ).append(row)

    rows_by_submission: dict[uuid.UUID, SubmissionMatchRow] = {}
    matched_recipient_ids: set[uuid.UUID] = set()
    for submission in submissions:
        agency_name = _submission_agency_dealership_name(submission)
        if not agency_name:
            continue

        normalized_agency = normalized_value(agency_name)
        exact_rows = exact_rows_by_group.get(submission.group_id, {}).get(
            normalized_agency.replace(" ", ""),
            [],
        )
        if exact_rows:
            best_rows = exact_rows
        else:
            scored_rows = [
                (score, row)
                for candidate, row in candidates_by_group.get(
                    submission.group_id,
                    [],
                )
                if (
                    score := _normalized_agency_match_similarity(
                        normalized_value(normalized_agency),
                        normalized_value(candidate),
                    )
                )
                >= _AGENCY_MATCH_SIMILARITY_THRESHOLD
            ]
            if not scored_rows:
                continue
            best_score = max(score for score, _ in scored_rows)
            best_rows = [row for score, row in scored_rows if abs(score - best_score) < 1e-12]
        if len(best_rows) != 1:
            # Duplicate agency values can refer to different people. Never
            # choose one arbitrarily and copy the wrong roster details.
            continue
        matched_row = best_rows[0]
        rows_by_submission[submission.id] = matched_row
        matched_recipient_ids.update(matched_row.recipient_ids)

    return _AgencyExportMatches(
        rows_by_submission=rows_by_submission,
        matched_recipient_ids=frozenset(matched_recipient_ids),
    )


def _export_effective_whatsapp_matches(
    agency_matches: _AgencyExportMatches,
    rows_by_group: dict[uuid.UUID, list[SubmissionMatchRow]],
) -> _AgencyExportMatches:
    """Prefer agency matches, then use each submission's existing WhatsApp match."""

    fallback_rows: dict[uuid.UUID, SubmissionMatchRow] = {}
    ambiguous_submission_ids: set[uuid.UUID] = set()
    for rows in rows_by_group.values():
        for row in rows:
            if row.status not in {
                "submitted",
                "multiple_submissions",
                "replacement",
            }:
                continue
            for submission_id in row.submission_ids:
                if submission_id in ambiguous_submission_ids:
                    continue
                existing = fallback_rows.get(submission_id)
                if existing is None:
                    fallback_rows[submission_id] = row
                elif existing is not row:
                    fallback_rows.pop(submission_id, None)
                    ambiguous_submission_ids.add(submission_id)

    rows_by_submission = {
        **fallback_rows,
        **agency_matches.rows_by_submission,
    }
    matched_recipient_ids = set(agency_matches.matched_recipient_ids)
    for row in rows_by_submission.values():
        matched_recipient_ids.update(row.recipient_ids)
    return _AgencyExportMatches(
        rows_by_submission=rows_by_submission,
        matched_recipient_ids=frozenset(matched_recipient_ids),
    )


def _apply_agency_export_matches(
    matches: _AgencyExportMatches,
    selected_fields: list[dict[str, str | bool]],
    agency_match_field: str,
    *,
    additional_values: dict[uuid.UUID, dict[str, str | None]],
    whatsapp_contacts: dict[uuid.UUID, dict[str, str | None]],
    zone_names: dict[uuid.UUID, str],
) -> dict[uuid.UUID, dict[str, str | None]]:
    """Fill WhatsApp-derived export data from each submission's effective row."""

    previous_names: dict[uuid.UUID, dict[str, str | None]] = {}
    normalized_match_field = agency_match_field.removeprefix("whatsapp:")
    for submission_id, row in matches.rows_by_submission.items():
        row_values = additional_values.setdefault(submission_id, {})
        row_values[agency_match_field] = _recipient_export_value(
            row,
            normalized_match_field,
        )
        for field in selected_fields:
            key = str(field["key"])
            if key == agency_match_field:
                continue
            if key.startswith("whatsapp:"):
                row_values[key] = _recipient_export_value(
                    row,
                    key.removeprefix("whatsapp:"),
                )
            elif key == "zone_name":
                zone_names.pop(submission_id, None)
                zone_name = _recipient_export_value(
                    row,
                    "zone_name",
                    "zonename",
                    "zone",
                )
                if zone_name:
                    zone_names[submission_id] = zone_name

        whatsapp_contacts[submission_id] = {
            "email": _recipient_export_value(
                row,
                *_WHATSAPP_EMAIL_IMPORTED_KEYS,
            ),
            "phone": (
                row.normalized_phone
                or _recipient_export_value(
                    row,
                    *_WHATSAPP_PHONE_IMPORTED_KEYS,
                )
            ),
        }
        previous_names[submission_id] = {
            "given_names": _recipient_old_given_name(row),
        }
    return previous_names


_AgencyExportMatches.__module__ = "app.presentation.api.v1.routes.passport_export_support"
