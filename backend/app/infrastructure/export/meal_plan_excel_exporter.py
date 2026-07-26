"""Readable XLSX export for saved category-complete meal plans."""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.table import Table, TableStyleInfo

MEAL_ORDER = {"lunch": 0, "dinner": 1}


@dataclass(frozen=True, slots=True)
class MealPlanExportEntry:
    day_number: int
    meal_type: str
    category_id: uuid.UUID | None
    category_name: str
    dish_name: str
    notes: str | None = None


def _safe_excel_text(value: str | None) -> str | None:
    """Prevent user-entered labels from being interpreted as formulas."""

    if value is None:
        return None
    if value.startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value


class MealPlanExcelExporter:
    """Create a matrix view plus a filterable dish-detail worksheet."""

    def export(
        self,
        *,
        plan_name: str,
        trip_days: int,
        start_date: date | None,
        selected_category_ids: list[uuid.UUID],
        entries: list[MealPlanExportEntry],
    ) -> bytes:
        ordered_entries = sorted(
            entries,
            key=lambda entry: (
                entry.day_number,
                MEAL_ORDER.get(entry.meal_type, 99),
                entry.category_name.casefold(),
                str(entry.category_id or ""),
            ),
        )
        categories = self._ordered_categories(
            ordered_entries,
            selected_category_ids=selected_category_ids,
        )

        workbook = Workbook()
        self._build_matrix_sheet(
            workbook.active,
            plan_name=plan_name,
            trip_days=trip_days,
            start_date=start_date,
            categories=categories,
            entries=ordered_entries,
        )
        detail_sheet = workbook.create_sheet("Dish List")
        self._build_detail_sheet(
            detail_sheet,
            start_date=start_date,
            entries=ordered_entries,
        )

        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    @staticmethod
    def _ordered_categories(
        entries: list[MealPlanExportEntry],
        *,
        selected_category_ids: list[uuid.UUID],
    ) -> list[tuple[str, str]]:
        category_names: dict[str, str] = {}
        for entry in entries:
            key = (
                str(entry.category_id)
                if entry.category_id
                else (f"snapshot:{entry.category_name.casefold()}")
            )
            category_names.setdefault(key, entry.category_name)

        ordered_keys = [
            str(category_id)
            for category_id in selected_category_ids
            if str(category_id) in category_names
        ]
        ordered_keys.extend(
            key
            for key in sorted(
                category_names,
                key=lambda item: (category_names[item].casefold(), item),
            )
            if key not in ordered_keys
        )
        return [(key, category_names[key]) for key in ordered_keys]

    @staticmethod
    def _build_matrix_sheet(
        worksheet,  # type: ignore[no-untyped-def]
        *,
        plan_name: str,
        trip_days: int,
        start_date: date | None,
        categories: list[tuple[str, str]],
        entries: list[MealPlanExportEntry],
    ) -> None:
        worksheet.title = "Meal Plan"
        column_count = 3 + len(categories)
        worksheet["A1"] = _safe_excel_text(plan_name)
        worksheet["A1"].font = Font(bold=True, size=16, color="0F172A")
        worksheet.merge_cells(
            start_row=1,
            start_column=1,
            end_row=1,
            end_column=max(1, column_count),
        )
        worksheet["A2"] = (
            f"{trip_days} day{'s' if trip_days != 1 else ''} | "
            f"{trip_days * 2} meals | {len(entries)} unique dishes"
        )
        worksheet.merge_cells(
            start_row=2,
            start_column=1,
            end_row=2,
            end_column=max(1, column_count),
        )
        worksheet["A3"] = (
            f"Trip starts: {start_date.strftime('%d %b %Y')}"
            if start_date
            else "Trip start date: Not set"
        )
        worksheet.merge_cells(
            start_row=3,
            start_column=1,
            end_row=3,
            end_column=max(1, column_count),
        )

        header_row = 5
        headers = ["Day", "Date", "Meal", *[name for _, name in categories]]
        worksheet.append([])
        worksheet.append([_safe_excel_text(header) for header in headers])
        for cell in worksheet[header_row]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1D4ED8")
            cell.alignment = Alignment(horizontal="center", vertical="center")

        entry_lookup = {
            (
                entry.day_number,
                entry.meal_type,
                str(entry.category_id)
                if entry.category_id
                else f"snapshot:{entry.category_name.casefold()}",
            ): entry
            for entry in entries
        }
        for day_number in range(1, trip_days + 1):
            meal_date = start_date + timedelta(days=day_number - 1) if start_date else None
            for meal_type in ("lunch", "dinner"):
                worksheet.append(
                    [
                        f"Day {day_number}",
                        meal_date,
                        meal_type.title(),
                        *[
                            _safe_excel_text(
                                entry_lookup.get((day_number, meal_type, category_key)).dish_name
                            )
                            if entry_lookup.get((day_number, meal_type, category_key))
                            else None
                            for category_key, _ in categories
                        ],
                    ]
                )

        last_row = header_row + (trip_days * 2)
        if last_row > header_row:
            table = Table(
                displayName="MealPlanSchedule",
                ref=f"A{header_row}:{worksheet.cell(header_row, column_count).column_letter}{last_row}",
            )
            table.tableStyleInfo = TableStyleInfo(
                name="TableStyleMedium2",
                showRowStripes=True,
                showColumnStripes=False,
            )
            worksheet.add_table(table)

        widths = [13, 15, 13, *([26] * len(categories))]
        for column, width in enumerate(widths, start=1):
            worksheet.column_dimensions[
                worksheet.cell(row=header_row, column=column).column_letter
            ].width = width
        for row in worksheet.iter_rows(min_row=header_row, max_row=last_row):
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        for cell in worksheet["B"][header_row:]:
            cell.number_format = "dd mmm yyyy"
        worksheet.freeze_panes = "A6"
        worksheet.sheet_view.showGridLines = False
        worksheet.auto_filter.ref = (
            f"A{header_row}:{worksheet.cell(last_row, column_count).coordinate}"
        )
        worksheet.page_setup.orientation = "landscape"
        worksheet.page_setup.fitToWidth = 1
        worksheet.page_setup.fitToHeight = 0
        worksheet.sheet_properties.pageSetUpPr.fitToPage = True

    @staticmethod
    def _build_detail_sheet(
        worksheet,  # type: ignore[no-untyped-def]
        *,
        start_date: date | None,
        entries: list[MealPlanExportEntry],
    ) -> None:
        headers = ["Day", "Date", "Meal", "Category", "Dish", "Notes"]
        worksheet.append(headers)
        for cell in worksheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="047857")
            cell.alignment = Alignment(horizontal="center", vertical="center")

        for entry in entries:
            meal_date = start_date + timedelta(days=entry.day_number - 1) if start_date else None
            worksheet.append(
                [
                    f"Day {entry.day_number}",
                    meal_date,
                    entry.meal_type.title(),
                    _safe_excel_text(entry.category_name),
                    _safe_excel_text(entry.dish_name),
                    _safe_excel_text(entry.notes),
                ]
            )

        last_row = 1 + len(entries)
        if entries:
            table = Table(
                displayName="MealPlanDishList",
                ref=f"A1:F{last_row}",
            )
            table.tableStyleInfo = TableStyleInfo(
                name="TableStyleMedium4",
                showRowStripes=True,
                showColumnStripes=False,
            )
            worksheet.add_table(table)
        for column, width in enumerate([13, 15, 13, 22, 30, 40], start=1):
            worksheet.column_dimensions[
                worksheet.cell(row=1, column=column).column_letter
            ].width = width
        for row in worksheet.iter_rows(min_row=1, max_row=last_row):
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        for cell in worksheet["B"][1:]:
            cell.number_format = "dd mmm yyyy"
        worksheet.freeze_panes = "A2"
        worksheet.sheet_view.showGridLines = False
