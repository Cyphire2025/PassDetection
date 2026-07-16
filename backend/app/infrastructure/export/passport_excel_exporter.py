"""
Passport Excel Exporter
=======================
Generates agency-ready XLSX files from confirmed passport submissions.
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.table import Table, TableStyleInfo

from app.domain.entities.entities import PassportSubmission


class PassportExcelExporter:
    HEADERS = [
        "Group",
        "Destination",
        "Travel Date",
        "Return Date",
        "Client Name",
        "Email",
        "Phone",
        "Nearest International Airport",
        "Base City",
        "Staff Code",
        "Meal Preference",
        "Status",
        "Surname",
        "Given Names",
        "Passport Number",
        "Nationality",
        "Issuing Country",
        "Date of Birth",
        "Date of Expiry",
        "Sex",
        "Confidence",
        "Submitted At",
        "Reviewed At",
    ]

    def export_group(
        self,
        submissions: list[PassportSubmission],
        *,
        group_name: str,
        group_details: dict[uuid.UUID, dict[str, str | None]] | None = None,
    ) -> bytes:
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Passport Submissions"

        worksheet["A1"] = f"Passport Export - {group_name}"
        worksheet["A1"].font = Font(bold=True, size=14)
        worksheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(self.HEADERS))
        worksheet["A2"] = f"Generated at {datetime.utcnow().isoformat(timespec='seconds')}Z"
        worksheet["A2"].font = Font(color="64748B")
        worksheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(self.HEADERS))

        worksheet.append([])
        worksheet.append(self.HEADERS)
        header_row = 4
        for cell in worksheet[header_row]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1D4ED8")
            cell.alignment = Alignment(horizontal="center")

        for submission in submissions:
            fields = submission.confirmed_fields or submission.extracted_fields or {}
            details = (group_details or {}).get(submission.group_id, {})
            worksheet.append(
                [
                    details.get("name") or group_name,
                    details.get("destination"),
                    details.get("travel_date"),
                    details.get("return_date"),
                    submission.client_name,
                    submission.client_email,
                    submission.client_phone,
                    submission.departure_city,
                    fields.get("base_city"),
                    fields.get("staff_code"),
                    fields.get("meal_preference"),
                    submission.status.value,
                    fields.get("surname"),
                    fields.get("given_names"),
                    fields.get("passport_number"),
                    fields.get("nationality"),
                    fields.get("issuing_country"),
                    fields.get("date_of_birth"),
                    fields.get("date_of_expiry"),
                    fields.get("sex"),
                    submission.overall_confidence,
                    submission.created_at.isoformat() if submission.created_at else None,
                    submission.client_reviewed_at.isoformat() if submission.client_reviewed_at else None,
                ]
            )

        if submissions:
            last_column = worksheet.cell(row=header_row, column=len(self.HEADERS)).column_letter
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

        widths = [24, 22, 16, 16, 24, 28, 18, 28, 20, 18, 18, 18, 20, 24, 20, 16, 18, 16, 16, 10, 14, 28, 28]
        for index, width in enumerate(widths, start=1):
            worksheet.column_dimensions[worksheet.cell(row=4, column=index).column_letter].width = width

        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()
