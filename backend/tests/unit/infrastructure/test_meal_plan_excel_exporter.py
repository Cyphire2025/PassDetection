from __future__ import annotations

import io
import uuid
from datetime import date, datetime
from zipfile import ZipFile

from openpyxl import load_workbook

from app.infrastructure.export.meal_plan_excel_exporter import (
    MealPlanExcelExporter,
    MealPlanExportEntry,
    _safe_excel_text,
)


def test_meal_plan_export_has_category_matrix_and_filterable_dish_list() -> None:
    chicken_id = uuid.uuid4()
    paneer_id = uuid.uuid4()
    entries = [
        MealPlanExportEntry(
            day_number=day,
            meal_type=meal_type,
            category_id=category_id,
            category_name=category_name,
            dish_name=f"{category_name} {day} {meal_type}",
        )
        for day in (1, 2)
        for meal_type in ("lunch", "dinner")
        for category_id, category_name in (
            (chicken_id, "Chicken"),
            (paneer_id, "Paneer"),
        )
    ]

    content = MealPlanExcelExporter().export(
        plan_name="Two Day Trip",
        trip_days=2,
        start_date=date(2026, 7, 27),
        selected_category_ids=[chicken_id, paneer_id],
        entries=entries,
    )

    with ZipFile(io.BytesIO(content)) as archive:
        assert not any(name.startswith("xl/tables/") for name in archive.namelist())

    workbook = load_workbook(io.BytesIO(content))
    assert workbook.sheetnames == ["Meal Plan", "Dish List"]
    schedule = workbook["Meal Plan"]
    assert schedule["A1"].value == "Two Day Trip"
    assert [schedule.cell(5, column).value for column in range(1, 6)] == [
        "Day",
        "Date",
        "Meal",
        "Chicken",
        "Paneer",
    ]
    assert [schedule.cell(6, column).value for column in range(1, 6)] == [
        "Day 1",
        datetime(2026, 7, 27),
        "Lunch",
        "Chicken 1 lunch",
        "Paneer 1 lunch",
    ]
    assert schedule.auto_filter.ref == "A5:E9"
    details = workbook["Dish List"]
    assert details.max_row == 9
    assert details.auto_filter.ref == "A1:F9"
    assert [details.cell(1, column).value for column in range(1, 7)] == [
        "Day",
        "Date",
        "Meal",
        "Category",
        "Dish",
        "Notes",
    ]


def test_excel_text_is_not_interpreted_as_a_formula() -> None:
    assert _safe_excel_text('=HYPERLINK("https://example.com")') == (
        '\'=HYPERLINK("https://example.com")'
    )
    assert _safe_excel_text("Butter Chicken") == "Butter Chicken"
    assert _safe_excel_text(None) is None
