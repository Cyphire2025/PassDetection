"""Detach saved meal-plan data before cancellation-safe native workbook rendering."""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from typing import TypedDict

from app.infrastructure.database.menu_models import MealPlanModel
from app.infrastructure.documents.storage_transfers import run_bounded_storage_operations
from app.infrastructure.export.meal_plan_excel_exporter import (
    MealPlanExcelExporter,
    MealPlanExportEntry,
)


class _MealPlanWorkbookArguments(TypedDict):
    plan_name: str
    trip_days: int
    start_date: date | None
    selected_category_ids: list[uuid.UUID]
    entries: list[MealPlanExportEntry]


async def render_meal_plan_workbook(
    plan: MealPlanModel,
    *,
    exporter: MealPlanExcelExporter,
) -> bytes:
    # Read every ORM value on the request loop. The native worker receives only
    # strings, dates, UUIDs and frozen entry snapshots, never a live ORM session.
    arguments: _MealPlanWorkbookArguments = {
        "plan_name": plan.name,
        "trip_days": plan.trip_days,
        "start_date": plan.start_date,
        "selected_category_ids": [
            uuid.UUID(str(category_id)) for category_id in plan.selected_category_ids
        ],
        "entries": [
            MealPlanExportEntry(
                day_number=entry.day_number,
                meal_type=entry.meal_type,
                category_id=entry.category_id,
                category_name=entry.category_name,
                dish_name=entry.dish_name,
                notes=entry.notes,
            )
            for entry in plan.entries
        ],
    }
    results = await run_bounded_storage_operations(
        [lambda: asyncio.to_thread(exporter.export, **arguments)],
        concurrency=1,
    )
    return results[0]
