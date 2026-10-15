"""Revision-aware deltas for a bounded group export checkpoint.

O(n + b) time/space for at most 5,000 current/baseline submissions. Hashes contain
no document contents and cumulative checkpoints make chained downloads stable.
Legacy checkpoints fall back to source update time, never import order.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.application.use_cases.passports.excel_snapshot import snapshot_digest
from app.domain.entities.entities import PassportSubmission


@dataclass(frozen=True, slots=True)
class ExportChanges:
    revisions: dict[str, str]
    rows: list[dict[str, str]]

    @property
    def included_ids(self) -> set[uuid.UUID]:
        return {uuid.UUID(row["submission_id"]) for row in self.rows if row["change"] != "removed"}


SUBMISSION_REVISION_FIELDS = (
    "client_name", "client_phone", "client_email", "confirmed_fields", "extracted_fields",
    "extraction_revision", "status", "departure_city", "nearest_domestic_airport",
    "custom_answers", "custom_detail_answers", "image_s3_key", "passport_back_s3_key",
    "passport_cover_s3_key", "passport_back_cover_s3_key", "passport_photo_s3_key",
)


def submission_revision(submission: object) -> str:
    return snapshot_digest({field: getattr(submission, field, None) for field in SUBMISSION_REVISION_FIELDS})


def export_changes(submissions: list[PassportSubmission], baseline: Any | None,
                   *, revisions: dict[str, str] | None = None) -> ExportChanges:
    revisions = revisions if revisions is not None else {str(row.id): submission_revision(row) for row in submissions}
    prior_ids = {str(value) for value in baseline.snapshot_submission_ids} if baseline else set()
    metadata = getattr(baseline, "artifact_metadata", None) or {}
    previous = metadata.get("submission_revisions", {})
    if not isinstance(previous, dict):
        raise ValueError("Invalid export revision checkpoint")
    rows: list[dict[str, str]] = []
    for submission in submissions:
        key = str(submission.id)
        old = previous.get(key)
        if key not in prior_ids:
            change = "added"
        elif isinstance(old, str):
            if old == revisions[key]:
                continue
            change = "changed"
        else:
            updated = getattr(submission, "updated_at", None)
            prepared = getattr(baseline, "created_at", None)
            if not isinstance(updated, datetime) or not isinstance(prepared, datetime):
                continue
            if updated.replace(tzinfo=updated.tzinfo or UTC) <= prepared.replace(tzinfo=prepared.tzinfo or UTC):
                continue
            change = "changed"
        rows.append({"submission_id": key, "change": change,
                     "previous_revision": old if isinstance(old, str) else "legacy", "revision": revisions[key]})
    for key in sorted(prior_ids - revisions.keys()):
        rows.append({"submission_id": key, "change": "removed",
                     "previous_revision": str(previous.get(key, "legacy")), "revision": ""})
    return ExportChanges(revisions, rows)
