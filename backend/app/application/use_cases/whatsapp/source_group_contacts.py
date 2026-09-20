"""Map passport names and explicit WhatsApp contacts without granting OTP authority."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from app.application.mobile.passenger_phone_authority import authoritative_submission_phone
from app.application.use_cases.whatsapp.contact_normalization import normalize_whatsapp_phone
from app.domain.value_objects.client_collection_provenance import (
    CLIENT_COLLECTION_SUBMITTED_KEY,
    CLIENT_COLLECTION_SUBMITTED_VALUE,
)

EXCLUDED_REASONS = (
    "missing_phone", "invalid_phone", "unverified_phone", "missing_name",
    "name_too_long", "duplicate_phone",
)


def _explicit_imported_phone(metadata: Mapping[str, Any]) -> tuple[str | None, bool]:
    """Accept only the labelled column; generic imported phone fields are excluded."""
    values = {
        str(value).strip()
        for key, value in metadata.items()
        if re.fullmatch(
            r"verifiedwhatsappnumbers?(?:[2-9][0-9]*)?",
            re.sub(r"[^a-z0-9]", "", str(key).casefold()),
        )
        and str(value or "").strip()
    }
    if not values:
        return None, False
    normalized = {normalize_whatsapp_phone(value) for value in values}
    if len(normalized) != 1 or None in normalized:
        return None, True
    return normalized.pop(), True


def _has_collection_contact(submission: Any) -> bool:
    metadata = submission.staff_metadata or {}
    if metadata.get(CLIENT_COLLECTION_SUBMITTED_KEY) == CLIENT_COLLECTION_SUBMITTED_VALUE:
        return True
    confidence = getattr(submission, "confidence_score", None) or {}
    known_import = confidence.get("source") == "excel_import" or str(
        getattr(submission, "image_s3_key", "") or ""
    ).startswith("excel-imports/")
    return getattr(submission, "client_reviewed_at", None) is not None and not known_import


def build_source_contacts(
    group_id: uuid.UUID, group_name: str, submissions: Sequence[Any],
) -> dict[str, Any]:
    """Build a deterministic snapshot from stored data, never from browser contacts."""
    recipients: list[dict[str, Any]] = []
    excluded = dict.fromkeys(EXCLUDED_REASONS, 0)
    seen: set[str] = set()
    for submission in submissions:
        fields = submission.confirmed_fields or submission.extracted_fields or {}
        # Match the export's reviewed-over-extracted precedence. Do not infer a
        # missing passport name from a generic uploader or roster contact name.
        name = " ".join(
            " ".join(str(fields.get(key) or "").split())
            for key in ("given_names", "surname")
        ).strip()
        phone = authoritative_submission_phone(submission)
        metadata = submission.staff_metadata or {}
        if phone is None:
            if _has_collection_contact(submission):
                excluded["invalid_phone" if submission.client_phone else "missing_phone"] += 1
                continue
            phone, has_explicit_column = _explicit_imported_phone(metadata)
            if phone is None:
                reason = "invalid_phone" if has_explicit_column else (
                    "unverified_phone" if submission.client_phone else "missing_phone"
                )
                excluded[reason] += 1
                continue
        if not name:
            excluded["missing_name"] += 1
            continue
        if len(name) > 100:
            excluded["name_too_long"] += 1
            continue
        if phone in seen:
            excluded["duplicate_phone"] += 1
            continue
        seen.add(phone)
        recipients.append({
            "name": name,
            "phone_number": phone,
            "imported_fields": {
                "name": name,
                "given_names": str(fields.get("given_names") or "").strip(),
                "surname": str(fields.get("surname") or "").strip(),
                "phone_number": phone,
            },
        })
    snapshot = {
        "source_group_id": str(group_id),
        "source_group_name": group_name,
        "total_submissions": len(submissions),
        "recipient_count": len(recipients),
        "recipients": recipients,
        "excluded_count": sum(excluded.values()),
        "excluded_counts": excluded,
    }
    revision = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    return {**snapshot, "preview_revision": revision}
