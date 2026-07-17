"""
Passport Excel Exporter
=======================
Generates agency-ready XLSX files from confirmed passport submissions.
"""

from __future__ import annotations

import io
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import pycountry
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.table import Table, TableStyleInfo

from app.domain.entities.entities import PassportSubmission


@dataclass(frozen=True)
class _ExportColumn:
    header: str
    width: int
    enabled_flag: str | None = None
    number_format: str | None = None


_EXCEL_DATE_NUMBER_FORMAT = "DD.MM.YYYY"
_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_COLUMNS = (
    _ExportColumn("Group", 24),
    _ExportColumn("Destination", 22),
    _ExportColumn("Travel Date", 16, number_format=_EXCEL_DATE_NUMBER_FORMAT),
    _ExportColumn("Return Date", 16, number_format=_EXCEL_DATE_NUMBER_FORMAT),
    _ExportColumn("Client Name", 24),
    _ExportColumn("Email", 28),
    _ExportColumn("Phone", 18),
    _ExportColumn(
        "Nearest International Airport",
        28,
        "nearest_international_airport_enabled",
    ),
    _ExportColumn(
        "Nearest Domestic Airport",
        26,
        "ask_nearest_domestic_airport",
    ),
    _ExportColumn("Base City", 20, "base_city_enabled"),
    _ExportColumn("Staff Code", 18, "staff_code_enabled"),
    _ExportColumn("Meal Preference", 18, "meal_preference_enabled"),
    _ExportColumn("Surname", 20),
    _ExportColumn("Given Names", 24),
    _ExportColumn("Passport Number", 20),
    _ExportColumn("Nationality", 22),
    _ExportColumn("Date of Birth", 16, number_format=_EXCEL_DATE_NUMBER_FORMAT),
    _ExportColumn("Date of Issue", 16, number_format=_EXCEL_DATE_NUMBER_FORMAT),
    _ExportColumn("Date of Expiry", 16, number_format=_EXCEL_DATE_NUMBER_FORMAT),
    _ExportColumn("Sex", 10),
)

_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _safe_xlsx_value(value: Any) -> Any:
    """Keep untrusted text from being interpreted as an Excel formula."""

    if not isinstance(value, str):
        return value
    if value.lstrip().startswith(_FORMULA_PREFIXES):
        return f"'{value}"
    return value


def _uppercase(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).upper()


def _excel_date_value(value: Any) -> Any:
    """Convert canonical dates to native Excel dates without losing legacy text."""

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return value
    normalized = value.strip()
    if not _ISO_DATE_PATTERN.fullmatch(normalized):
        return value
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return value


def _gender_display_value(value: Any) -> str | None:
    """Normalize recognized passport sex values without mutating stored data."""

    if value in (None, ""):
        return None
    normalized = " ".join(str(value).strip().split()).casefold()
    if normalized in {"m", "male"}:
        return "Male"
    if normalized in {"f", "female"}:
        return "Female"
    # Do not invent a binary value for an unsupported or non-binary document
    # marker. Returning the trimmed source is safer than silently misgendering
    # the traveller while still normalizing every supported legacy value.
    return " ".join(str(value).strip().split()) or None


def _country_display_name(value: Any) -> str | None:
    if value in (None, ""):
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    try:
        country = pycountry.countries.lookup(normalized)
    except LookupError:
        return normalized
    return str(getattr(country, "common_name", country.name))


class PassportExcelExporter:
    HEADERS = [column.header for column in _COLUMNS]

    def export_group(
        self,
        submissions: list[PassportSubmission],
        *,
        group_name: str,
        group_details: dict[uuid.UUID, dict[str, str | bool | None]] | None = None,
    ) -> bytes:
        columns = self._enabled_columns(submissions, group_details)
        headers = [column.header for column in columns]
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Passport Submissions"

        worksheet["A1"] = f"Passport Export - {group_name}"
        worksheet["A1"].font = Font(bold=True, size=14)
        worksheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
        generated_at = datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        worksheet["A2"] = f"Generated at {generated_at}"
        worksheet["A2"].font = Font(color="64748B")
        worksheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(headers))

        worksheet.append([])
        worksheet.append(headers)
        header_row = 4
        for cell in worksheet[header_row]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1D4ED8")
            cell.alignment = Alignment(horizontal="center")

        for submission in submissions:
            fields = submission.confirmed_fields or submission.extracted_fields or {}
            staff_metadata = submission.staff_metadata or {}
            details = (group_details or {}).get(submission.group_id, {})
            values = {
                "Group": details.get("name") or group_name,
                "Destination": details.get("destination"),
                "Travel Date": details.get("travel_date"),
                "Return Date": details.get("return_date"),
                "Client Name": submission.client_name,
                "Email": submission.client_email,
                "Phone": submission.client_phone,
                "Nearest International Airport": submission.departure_city,
                "Nearest Domestic Airport": submission.nearest_domestic_airport,
                "Base City": fields.get("base_city") or staff_metadata.get("base_city"),
                "Staff Code": fields.get("staff_code") or staff_metadata.get("staff_code"),
                "Meal Preference": (
                    fields.get("meal_preference") or staff_metadata.get("meal_preference")
                ),
                "Surname": _uppercase(fields.get("surname")),
                "Given Names": _uppercase(fields.get("given_names")),
                "Passport Number": fields.get("passport_number"),
                "Nationality": _country_display_name(fields.get("nationality")),
                "Date of Birth": fields.get("date_of_birth"),
                "Date of Issue": fields.get("date_of_issue"),
                "Date of Expiry": fields.get("date_of_expiry"),
                "Sex": _gender_display_value(fields.get("sex")),
            }
            row_values = []
            for column in columns:
                value = values[column.header]
                if column.number_format:
                    value = _excel_date_value(value)
                row_values.append(_safe_xlsx_value(value))
            worksheet.append(row_values)
            row_index = worksheet.max_row
            for column_index, column in enumerate(columns, start=1):
                cell = worksheet.cell(row=row_index, column=column_index)
                if column.number_format and isinstance(cell.value, (date, datetime)):
                    cell.number_format = column.number_format

        if submissions:
            last_column = worksheet.cell(row=header_row, column=len(headers)).column_letter
            table_ref = f"A{header_row}:{last_column}{header_row + len(submissions)}"
            table = Table(displayName="PassportSubmissions", ref=table_ref)
            table.tableStyleInfo = TableStyleInfo(
                name="TableStyleMedium2",
                showFirstColumn=False,
                showLastColumn=False,
                showRowStripes=True,
                showColumnStripes=False,
            )
            worksheet.add_table(table)

        for index, column in enumerate(columns, start=1):
            column_letter = worksheet.cell(row=header_row, column=index).column_letter
            worksheet.column_dimensions[column_letter].width = column.width

        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    @staticmethod
    def _enabled_columns(
        submissions: list[PassportSubmission],
        group_details: dict[uuid.UUID, dict[str, str | bool | None]] | None,
    ) -> list[_ExportColumn]:
        if group_details is None:
            return list(_COLUMNS)

        submitted_group_ids = {submission.group_id for submission in submissions}
        relevant_details = [
            details
            for group_id, details in group_details.items()
            if not submitted_group_ids or group_id in submitted_group_ids
        ]
        if not relevant_details:
            return list(_COLUMNS)

        return [
            column
            for column in _COLUMNS
            if column.enabled_flag is None
            or any(bool(details.get(column.enabled_flag, True)) for details in relevant_details)
        ]
