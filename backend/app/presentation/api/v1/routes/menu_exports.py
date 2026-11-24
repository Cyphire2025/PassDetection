"""Tenant-authorized saved meal-plan workbook download."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.session import get_db_session
from app.infrastructure.export.meal_plan_excel_exporter import MealPlanExcelExporter
from app.presentation.api.v1.response_contracts import XLSX, binary_responses
from app.presentation.api.v1.routes.menu_export_support import render_meal_plan_workbook
from app.presentation.dependencies.auth import require_role

from .menu_common import MENU_ROLES, _agency_scope, _excel_filename
from .menu_queries import _get_plan

router = APIRouter()


@router.get(
    "/plans/{plan_id}/export.xlsx",
    summary="Export a saved meal plan to Excel",
    response_class=Response,
    responses=binary_responses(XLSX),
)
async def export_meal_plan(
    plan_id: uuid.UUID,
    current_user: User = Depends(require_role(MENU_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    agency_id = _agency_scope(current_user)
    plan = await _get_plan(session, plan_id, agency_id, include_entries=True)
    content = await render_meal_plan_workbook(plan, exporter=MealPlanExcelExporter())
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": (f'attachment; filename="{_excel_filename(plan.name)}"')},
    )
