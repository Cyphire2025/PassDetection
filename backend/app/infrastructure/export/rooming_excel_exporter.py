"""Hotel-facing XLSX rooming list exporter."""

from __future__ import annotations

import io
from datetime import datetime, timezone

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.table import Table, TableStyleInfo


class RoomingExcelExporter:
    headers = [
        "Room Number",
        "Room Type",
        "Allocation Tag",
        "Guest Name",
        "Passport Sex",
        "Passenger Tag",
        "Special Requests",
        "Passenger Roommate Notes",
        "Room Notes",
    ]

    def export_hotel(self, *, group_name: str, hotel, rooms: list, passenger_by_id: dict, preferences: dict) -> bytes:  # type: ignore[no-untyped-def]
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Rooming List"

        worksheet["A1"] = f"Rooming List - {hotel.hotel_name}"
        worksheet["A1"].font = Font(bold=True, size=15)
        worksheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(self.headers))
        worksheet["A2"] = f"Group: {group_name}"
        worksheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(self.headers))
        dates = ""
        if hotel.check_in_date or hotel.check_out_date:
            dates = f"{hotel.check_in_date or ''} to {hotel.check_out_date or ''}"
        worksheet["A3"] = f"City: {hotel.city or '-'}   Stay: {dates or '-'}"
        worksheet.merge_cells(start_row=3, start_column=1, end_row=3, end_column=len(self.headers))
        worksheet["A4"] = f"Generated: {datetime.now(tz=timezone.utc).strftime('%d %b %Y %H:%M UTC')}"
        worksheet.merge_cells(start_row=4, start_column=1, end_row=4, end_column=len(self.headers))

        worksheet.append([])
        worksheet.append(self.headers)
        header_row = 6
        for cell in worksheet[header_row]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1D4ED8")
            cell.alignment = Alignment(horizontal="center", vertical="center")

        row_count = 0
        for room, assignments in rooms:
            if not assignments:
                worksheet.append([room.room_number, room.room_type.title(), room.allocation_tag.title(), "Unoccupied", None, None, None, None, room.roommate_notes])
                row_count += 1
                continue
            for assignment in assignments:
                passenger = passenger_by_id[assignment.passenger_id]
                preference = preferences.get(assignment.passenger_id)
                fields = passenger.confirmed_fields or passenger.extracted_fields or {}
                worksheet.append(
                    [
                        room.room_number,
                        room.room_type.title(),
                        room.allocation_tag.title(),
                        passenger.client_name,
                        fields.get("sex"),
                        preference.allocation_tag.title() if preference else "Unspecified",
                        ", ".join(preference.special_requests or []) if preference else None,
                        preference.roommate_notes if preference else None,
                        room.roommate_notes,
                    ]
                )
                row_count += 1

        if row_count:
            table = Table(displayName="HotelRoomingList", ref=f"A{header_row}:I{header_row + row_count}")
            table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True, showColumnStripes=False)
            worksheet.add_table(table)

        for column, width in enumerate([16, 14, 18, 30, 14, 18, 24, 36, 36], start=1):
            worksheet.column_dimensions[worksheet.cell(row=header_row, column=column).column_letter].width = width
        worksheet.sheet_view.showGridLines = False
        worksheet.page_setup.orientation = "landscape"
        worksheet.page_setup.fitToWidth = 1
        worksheet.page_setup.fitToHeight = 0
        worksheet.sheet_properties.pageSetUpPr.fitToPage = True
        worksheet.freeze_panes = None
        worksheet.sheet_view.pane = None

        for row in worksheet.iter_rows(min_row=header_row, max_row=header_row + row_count):
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)

        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    def export_checkins(self, *, group_name: str, hotel_name: str, passengers: list) -> bytes:  # type: ignore[no-untyped-def]
        headers = ["Group Name", "Hotel Name", "Room No", "Room Type", "Passenger Name", "Checked in", "Key Issued", "Welcome Kit/Letter Issued", "Remarks"]
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Hotel Check-in"
        worksheet.append(headers)
        for cell in worksheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="047857")
            cell.alignment = Alignment(horizontal="center")
        for item in passengers:
            worksheet.append([group_name, hotel_name, item.room_number, item.room_type.title(), item.passenger_name, "Yes" if item.checked_in else "No", "Yes" if item.key_issued else "No", "Yes" if item.welcome_letter_issued else "No", item.remarks])
        if passengers:
            table = Table(displayName="HotelCheckins", ref=f"A1:I{len(passengers) + 1}")
            table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium4", showRowStripes=True, showColumnStripes=False)
            worksheet.add_table(table)
        for index, width in enumerate([26, 26, 14, 14, 30, 14, 14, 28, 42], start=1):
            worksheet.column_dimensions[worksheet.cell(row=1, column=index).column_letter].width = width
        worksheet.freeze_panes = "A2"
        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()
