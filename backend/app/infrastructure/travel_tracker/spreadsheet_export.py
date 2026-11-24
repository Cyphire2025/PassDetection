"""Formula-safe complete tracker workbook projection and write-only rendering."""

from __future__ import annotations

import io
import json
import re
from typing import Any

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.travel_tracker_model import TravelTrackerModel
from app.infrastructure.travel_tracker.spreadsheet_values import (
    MAX_COLUMNS,
    TrackerSpreadsheetError,
    field_values,
    full_name,
)


def _safe(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, str):
        value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value)[:32767]
        if value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
    return value


def build_export(
    group: ClientGroupModel, rows: list[tuple[PassportSubmissionModel, TravelTrackerModel | None]]
) -> bytes:
    """Include fixed contact/trip details and every collected/imported data field."""
    headers = [
        "Passenger ID",
        "Full Name",
        "Group",
        "Destination",
        "Travel Date",
        "Return Date",
        "Package",
        "Email",
        "Phone",
        "Departure City",
        "Nearest Domestic Airport",
        "Submission Status",
        "Visa Applied",
        "Flight Booked",
        "Visa Updated At",
        "Flight Updated At",
        "Visa Updated By",
        "Flight Updated By",
        "Family Relation",
        "Family Head Name",
        "Relation With Qualifier",
    ]
    passport_keys = sorted({key for passenger, _ in rows for key in field_values(passenger)})
    # Passport Number remains recognizable by round-trip identity matching.
    passport_headers = {
        key: " ".join(word.title() for word in key.split("_")) for key in passport_keys
    }
    metadata_keys = sorted(
        {
            key
            for passenger, _ in rows
            for key in (passenger.staff_metadata or {})
            if not key.startswith("_")
        }
    )
    custom_questions = {
        str(item.get("id")): str(item.get("label") or item.get("question") or item.get("id"))
        for item in (group.custom_questions or [])
    }
    custom_details = {
        str(item.get("id")): str(item.get("label") or item.get("id"))
        for item in (group.custom_details or [])
    }
    for passenger, _ in rows:
        for answer in passenger.custom_answers or []:
            custom_questions.setdefault(
                str(answer.get("question_id")),
                str(answer.get("label") or answer.get("question_id")),
            )
        for detail_answer in passenger.custom_detail_answers or []:
            custom_details.setdefault(
                str(detail_answer.get("detail_id")),
                str(detail_answer.get("label") or detail_answer.get("detail_id")),
            )
    headers += [passport_headers[key] for key in passport_keys]
    headers += ["Imported: " + key for key in metadata_keys]
    headers += ["Question: " + label for label in custom_questions.values()]
    headers += ["Detail: " + label for label in custom_details.values()]
    if len(headers) > MAX_COLUMNS:
        raise TrackerSpreadsheetError(
            "The roster has too many detail columns for one export (maximum 256)."
        )
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Travel Tracker")
    sheet.freeze_panes = "C2"
    for index, header in enumerate(headers, 1):
        sheet.column_dimensions[get_column_letter(index)].width = min(38, max(18, len(header) + 3))

    styled_headers = []
    for value in headers:
        cell = WriteOnlyCell(sheet, value=_safe(value))
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="153A56")
        styled_headers.append(cell)
    sheet.append(styled_headers)
    for passenger, tracker in rows:
        fields = field_values(passenger)
        answers = {
            str(answer.get("question_id")): answer.get("value")
            for answer in passenger.custom_answers or []
        }
        details = {
            str(answer.get("detail_id")): answer.get("value")
            for answer in passenger.custom_detail_answers or []
        }
        values = [
            str(passenger.id),
            full_name(passenger),
            group.name,
            group.destination,
            group.travel_date,
            group.return_date,
            group.package_name,
            passenger.client_email,
            passenger.client_phone,
            passenger.departure_city,
            passenger.nearest_domestic_airport,
            passenger.status,
            bool(tracker and tracker.visa_applied),
            bool(tracker and tracker.flight_booked),
            tracker.visa_updated_at.isoformat() if tracker and tracker.visa_updated_at else None,
            tracker.flight_updated_at.isoformat()
            if tracker and tracker.flight_updated_at
            else None,
            str(tracker.visa_updated_by) if tracker and tracker.visa_updated_by else None,
            str(tracker.flight_updated_by) if tracker and tracker.flight_updated_by else None,
            passenger.family_relation,
            passenger.family_head_name,
            passenger.qualifier_relation_label,
        ]
        values += [fields.get(key) for key in passport_keys]
        values += [(passenger.staff_metadata or {}).get(key) for key in metadata_keys]
        values += [answers.get(key) for key in custom_questions]
        values += [details.get(key) for key in custom_details]
        sheet.append([_safe(value) for value in values])
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(1, len(rows) + 1)}"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
