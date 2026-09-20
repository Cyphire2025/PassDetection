"""Map passport names and explicit WhatsApp contacts without granting OTP authority."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from typing import Any

from app.application.mobile.passenger_phone_authority import authoritative_submission_phone
from app.application.use_cases.whatsapp.imported_broadcast_phone import (
    explicit_imported_broadcast_phone,
    has_public_collection_contact,
    raw_explicit_imported_broadcast_phone,
)

EXCLUDED_REASONS = (
    "missing_phone", "invalid_phone", "unverified_phone", "missing_name",
    "name_too_long", "duplicate_phone",
)


def _raw_source_phone(submission: Any) -> str:
    if has_public_collection_contact(submission):
        return str(submission.client_phone or "").strip()
    raw_phone, has_explicit_column = raw_explicit_imported_broadcast_phone(
        submission.staff_metadata or {},
    )
    return raw_phone if has_explicit_column else str(submission.client_phone or "").strip()


def build_source_contacts(
    group_id: uuid.UUID, group_name: str, submissions: Sequence[Any], *, import_only: bool = False,
) -> dict[str, Any]:
    """Retain every traveller row while creating one delivery destination per phone."""
    recipients: list[dict[str, Any]] = []
    contacts: list[dict[str, Any]] = []
    excluded = dict.fromkeys(EXCLUDED_REASONS, 0)
    seen: set[str] = set()
    shared_phone_count = 0
    for index, submission in enumerate(submissions):
        fields = submission.confirmed_fields or submission.extracted_fields or {}
        # Match the export's reviewed-over-extracted precedence. Do not infer a
        # missing passport name from a generic uploader or roster contact name.
        name = " ".join(
            " ".join(str(fields.get(key) or "").split())
            for key in ("given_names", "surname")
        ).strip()
        phone = authoritative_submission_phone(submission)
        metadata = submission.staff_metadata or {}
        issue: str | None = None
        if phone is None:
            if has_public_collection_contact(submission):
                issue = "invalid_phone" if submission.client_phone else "missing_phone"
            else:
                phone, has_explicit_column = explicit_imported_broadcast_phone(metadata)
                if phone is None:
                    issue = "invalid_phone" if has_explicit_column else (
                        "unverified_phone" if submission.client_phone else "missing_phone"
                    )
        if not issue and not name:
            issue = "missing_name"
        if not issue and len(name) > 100:
            issue = "name_too_long"
        raw_phone = _raw_source_phone(submission)
        imported_fields = {
            "name": name,
            "given_names": str(fields.get("given_names") or "").strip(),
            "surname": str(fields.get("surname") or "").strip(),
            "phone_number": phone or raw_phone,
        }
        contacts.append({
            "source_submission_id": str(getattr(submission, "id", uuid.uuid5(group_id, f"row:{index}"))),
            "name": name,
            "phone_number": raw_phone,
            "normalized_phone_number": phone,
            "issue": issue,
            "imported_fields": imported_fields,
        })
        if issue:
            excluded[issue] += 1
            continue
        assert phone is not None
        if phone in seen:
            shared_phone_count += 1
            continue
        seen.add(phone)
        recipients.append({
            "name": name,
            "phone_number": phone,
            "imported_fields": imported_fields,
        })
    snapshot = {
        "source_group_id": str(group_id),
        "source_group_name": group_name,
        "source_import_only": import_only,
        "total_submissions": len(submissions),
        "recipient_count": len(recipients),
        "recipients": recipients,
        "contacts": contacts,
        "shared_phone_count": shared_phone_count,
        "needs_attention_count": sum(excluded.values()),
        "excluded_count": sum(excluded.values()),
        "excluded_counts": excluded,
    }
    revision = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    return {**snapshot, "preview_revision": revision}
