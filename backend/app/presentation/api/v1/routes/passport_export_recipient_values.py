"""Unambiguous imported recipient values, contact and zone projection."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Literal

from app.application.use_cases.whatsapp.group_submission_matching import (
    SubmissionMatchRow,
)
from app.domain.entities.entities import PassportSubmission

_WHATSAPP_EMAIL_IMPORTED_KEYS = (
    "email",
    "email_id",
    "email_address",
    "e_mail",
    "mail",
)

_WHATSAPP_PHONE_IMPORTED_KEYS = (
    "phone_number",
    "phone",
    "mobile",
    "mobile_number",
    "whatsapp",
    "whatsapp_number",
    "contact",
    "contact_number",
)


def _normalized_imported_field_key(value: str) -> str:
    return "_".join(
        part
        for part in "".join(
            character.casefold() if character.isalnum() else " " for character in value
        ).split()
        if part
    )


def _imported_zone_name(fields: Mapping[str, object]) -> str | None:
    for key, value in fields.items():
        if _normalized_imported_field_key(str(key)) not in {
            "zone_name",
            "zonename",
            "zone",
        }:
            continue
        normalized = " ".join(str(value or "").strip().split())
        if normalized and normalized.casefold() not in {"null", "none", "n/a", "na"}:
            return normalized
    return None


def _export_zone_names_from_match_rows(
    submissions: list[PassportSubmission],
    rows_by_group: dict[uuid.UUID, list[SubmissionMatchRow]],
) -> dict[uuid.UUID, str]:
    resolved: dict[uuid.UUID, str] = {}
    submissions_by_group: dict[uuid.UUID, list[PassportSubmission]] = {}
    for submission in submissions:
        submissions_by_group.setdefault(submission.group_id, []).append(submission)

    for group_id, group_submissions in submissions_by_group.items():
        rows = rows_by_group.get(group_id, [])
        submissions_by_id = {submission.id: submission for submission in group_submissions}
        for row in rows:
            if row.status not in {
                "submitted",
                "multiple_submissions",
                "replacement",
            }:
                continue
            zones_by_key: dict[str, str] = {}
            for field_set in row.recipient_fields:
                zone_name = _imported_zone_name(field_set.fields)
                if zone_name:
                    zones_by_key.setdefault(zone_name.casefold(), zone_name)
            if not zones_by_key:
                continue
            for submission_id in row.submission_ids:
                if len(zones_by_key) == 1:
                    resolved[submission_id] = next(iter(zones_by_key.values()))
                    continue
                matched_submission = submissions_by_id.get(submission_id)
                stored_zone = _imported_zone_name(
                    matched_submission.staff_metadata or {}
                    if matched_submission is not None
                    else {}
                )
                if stored_zone and stored_zone.casefold() in zones_by_key:
                    resolved[submission_id] = zones_by_key[stored_zone.casefold()]
    return resolved


def _recipient_export_value(
    row: SubmissionMatchRow,
    *keys: str,
) -> str | None:
    values_by_key: dict[str, str] = {}
    accepted_keys = {_normalized_imported_field_key(key) for key in keys}
    for field_set in sorted(row.recipient_fields, key=lambda item: str(item.recipient_id)):
        for raw_key, raw_value in field_set.fields.items():
            if _normalized_imported_field_key(str(raw_key)) not in accepted_keys:
                continue
            value = " ".join(str(raw_value or "").strip().split())
            if not value or value.casefold() in {"null", "none", "n/a", "na"}:
                continue
            values_by_key.setdefault(value.casefold(), value)
    if len(values_by_key) == 1:
        return next(iter(values_by_key.values()))
    # Conflicting imported identities must not be silently assigned to a
    # random zone/person. Leave the ambiguous field empty for staff review.
    return None


def _recipient_old_given_name(row: SubmissionMatchRow) -> str | None:
    """Return the best unambiguous WhatsApp name for one matched recipient."""

    given_names = _recipient_export_value(
        row,
        "given_names",
        "given_name",
        "first_name",
    )
    if given_names:
        return given_names

    recipient_names_by_key = {
        normalized.casefold(): normalized
        for name in row.recipient_names
        if (normalized := " ".join(str(name or "").strip().split()))
    }
    if len(recipient_names_by_key) == 1:
        return next(iter(recipient_names_by_key.values()))

    imported_name = _recipient_export_value(
        row,
        "name",
        "full_name",
        "client_name",
        "passenger_name",
        "recipient_name",
        "staff_name",
        "employee_name",
    )
    if imported_name:
        return imported_name

    return _recipient_export_value(
        row,
        "surname",
        "last_name",
        "family_name",
    )


def _export_whatsapp_contacts(
    submissions: list[PassportSubmission],
    rows_by_group: dict[uuid.UUID, list[SubmissionMatchRow]],
) -> dict[uuid.UUID, dict[str, str | None]]:
    """Resolve matched broadcast contacts without mixing them with upload data."""

    candidates: dict[uuid.UUID, dict[str, dict[str, str]]] = {
        submission.id: {"email": {}, "phone": {}} for submission in submissions
    }

    def add_candidate(
        submission_id: uuid.UUID,
        field: Literal["email", "phone"],
        value: str | None,
    ) -> None:
        normalized = " ".join(str(value or "").strip().split())
        if (
            not normalized
            or normalized.casefold() in {"null", "none", "n/a", "na"}
            or submission_id not in candidates
        ):
            return
        candidates[submission_id][field].setdefault(normalized.casefold(), normalized)

    for rows in rows_by_group.values():
        for row in rows:
            if row.status not in {
                "submitted",
                "multiple_submissions",
                "replacement",
            }:
                continue
            email = _recipient_export_value(
                row,
                *_WHATSAPP_EMAIL_IMPORTED_KEYS,
            )
            phone = row.normalized_phone or _recipient_export_value(
                row,
                *_WHATSAPP_PHONE_IMPORTED_KEYS,
            )
            for submission_id in row.submission_ids:
                add_candidate(submission_id, "email", email)
                add_candidate(submission_id, "phone", phone)

    contacts: dict[uuid.UUID, dict[str, str | None]] = {}
    for submission_id, fields in candidates.items():
        contacts[submission_id] = {
            field: next(iter(values.values())) if len(values) == 1 else None
            for field, values in fields.items()
        }
    return contacts
