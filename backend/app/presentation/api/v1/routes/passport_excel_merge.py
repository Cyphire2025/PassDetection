"""Explicit Excel field merging and trusted client-contact provenance preservation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import TypeVar

from app.application.mobile.passenger_phone_authority import authoritative_submission_phone
from app.domain.value_objects.client_collection_provenance import (
    mark_client_collection_submitted,
    strip_client_collection_provenance,
)
from app.domain.value_objects.passport_fields import (
    reconcile_confirmed_with_extraction,
)
from app.domain.value_objects.phone_number import phone_numbers_equal
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.imports.passport_excel_importer import ImportedPassportRow

_FieldValue = TypeVar("_FieldValue")


def _merge_excel_fields(
    existing: Mapping[str, _FieldValue] | None,
    imported: Mapping[str, _FieldValue],
) -> dict[str, _FieldValue] | None:
    if not existing:
        return dict(imported) or None
    merged = dict(existing)
    for key, value in imported.items():
        if value not in (None, "") or key == "surname":
            merged[key] = value
    return merged


def _apply_passport_excel_row_to_submission(
    submission: PassportSubmissionModel,
    row: ImportedPassportRow,
    *,
    now: datetime,
) -> None:
    saved_metadata = _preserve_existing_collection_contact(submission, row.client_phone)
    submission.client_name = row.client_name
    if row.client_email is not None:
        submission.client_email = row.client_email
    if row.client_phone is not None:
        submission.client_phone = row.client_phone
    if row.departure_city is not None:
        submission.departure_city = row.departure_city
    if row.nearest_domestic_airport is not None:
        submission.nearest_domestic_airport = row.nearest_domestic_airport
    submission.staff_metadata = {
        **saved_metadata,
        **strip_client_collection_provenance(row.staff_metadata),
    } or None
    merged_confirmed_fields = _merge_excel_fields(
        submission.confirmed_fields,
        row.confirmed_fields,
    )
    merged_extracted_fields = _merge_excel_fields(
        submission.extracted_fields,
        row.confirmed_fields,
    )
    submission.extracted_fields = merged_extracted_fields
    submission.confirmed_fields, submission.extraction_conflicts = (
        reconcile_confirmed_with_extraction(
            merged_confirmed_fields,
            merged_extracted_fields or {},
        )
    )
    submission.confidence_score = {
        **(submission.confidence_score or {}),
        "source": "excel_import",
        "row_number": row.row_number,
        "source_sheet": row.worksheet_name,
        "updated_from_excel": True,
    }
    submission.overall_confidence = (
        submission.overall_confidence
        if submission.overall_confidence is not None
        else (1.0 if row.confirmed_fields else None)
    )
    submission.updated_at = now


def _preserve_existing_collection_contact(
    submission: PassportSubmissionModel,
    imported_phone: str | None,
) -> dict[str, str]:
    metadata = submission.staff_metadata or {}
    if imported_phone is not None and not phone_numbers_equal(
        submission.client_phone, imported_phone
    ):
        return strip_client_collection_provenance(metadata)
    # Compatibility conversion is based only on the trusted pre-import row.
    # Preserve an already-authoritative legacy contact when Excel edits other
    # fields; the import's own metadata can never establish this provenance.
    if getattr(
        submission, "client_reviewed_at", None
    ) is not None and authoritative_submission_phone(submission):
        return mark_client_collection_submitted(metadata)
    return dict(metadata)
