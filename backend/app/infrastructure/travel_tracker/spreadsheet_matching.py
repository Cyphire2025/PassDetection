"""Conservative group-local ID/passport/name matching with duplicate accounting."""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from app.application.dtos.travel_tracker import TrackerImportPreview, TrackerImportRow, TrackerTrack
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.travel_tracker.spreadsheet_values import (
    field_values,
    full_name,
    normalized_name,
    normalized_passport,
    text_value,
)


def match_rows(
    records: list[dict[str, Any]],
    passengers: list[PassportSubmissionModel],
    *,
    track: TrackerTrack,
    marked: bool,
) -> TrackerImportPreview:
    by_id = {str(passenger.id): passenger for passenger in passengers}
    by_passport: dict[str, dict[uuid.UUID, PassportSubmissionModel]] = defaultdict(dict)
    by_name: dict[str, dict[uuid.UUID, PassportSubmissionModel]] = defaultdict(dict)
    for passenger in passengers:
        fields = field_values(passenger)
        normalized_number = normalized_passport(fields.get("passport_number"))
        if normalized_number:
            by_passport[normalized_number][passenger.id] = passenger
        for alias_name in (
            full_name(passenger),
            " ".join(str(fields.get(key) or "").strip() for key in ("given_names", "surname")),
        ):
            if normalized_name(alias_name):
                by_name[normalized_name(alias_name)][passenger.id] = passenger
    result: list[TrackerImportRow] = []
    matched_ids: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for record in records:
        supplied_id = str(record.get("id") or "").strip()
        name = text_value(record.get("name"))
        passport = text_value(record.get("passport"))
        row = TrackerImportRow(
            row_number=record["row_number"],
            name=name,
            passport_number=passport,
            status="unmatched",
            reason="No passenger has this exact name in this group.",
        )
        candidates: list[PassportSubmissionModel] = []
        if any(
            str(record.get(key) or "").lstrip().startswith("=")
            for key in ("id", "name", "passport")
        ):
            row.reason = "Identity cells must contain text, not spreadsheet formulas."
        elif supplied_id:
            try:
                resolved_id = str(uuid.UUID(supplied_id))
            except ValueError:
                resolved_id = ""
            candidate = by_id.get(resolved_id)
            if candidate is not None and (
                not passport
                or normalized_passport(passport)
                == normalized_passport(field_values(candidate).get("passport_number"))
            ):
                candidates = [candidate]
                row.reason = "Matched Passenger ID."
            else:
                row.reason = (
                    "Passenger ID is missing from this group or conflicts with the passport number."
                )
        elif passport:
            candidates = list(by_passport.get(normalized_passport(passport), {}).values())
            row.reason = (
                "Matched passport number."
                if candidates
                else "Passport number was not found in this group."
            )
        elif name:
            candidates = list(by_name.get(normalized_name(name), {}).values())
            if candidates:
                row.reason = "Matched exact unique name."
        if len(candidates) > 1:
            row.status = "ambiguous"
            row.reason = "Multiple passengers match. Add a Passenger ID or unique Passport Number."
        elif len(candidates) == 1:
            passenger = candidates[0]
            row.passenger_id, row.passenger_name = passenger.id, full_name(passenger)
            if passenger.id in seen:
                row.status, row.reason = (
                    "duplicate",
                    "This passenger already appears in the update list.",
                )
            else:
                row.status = "matched"
                seen.add(passenger.id)
                matched_ids.append(passenger.id)
        result.append(row)
    counts = {
        kind: sum(row.status == kind for row in result)
        for kind in ("matched", "ambiguous", "unmatched", "duplicate")
    }
    return TrackerImportPreview(
        track=track,
        marked=marked,
        total_rows=len(result),
        matched_count=counts["matched"],
        ambiguous_count=counts["ambiguous"],
        unmatched_count=counts["unmatched"],
        duplicate_count=counts["duplicate"],
        passenger_ids=matched_ids,
        rows=result,
    )
