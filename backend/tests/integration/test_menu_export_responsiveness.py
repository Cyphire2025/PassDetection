"""An authenticated XLSX request must leave the event loop responsive."""

from __future__ import annotations

import asyncio
import threading
import uuid

import pytest

from app.infrastructure.database.menu_models import MealPlanEntryModel, MealPlanModel
from app.infrastructure.database.models import AgencyModel, UserModel
from app.presentation.api.v1.routes import menu
from tests.dashboard_session_fixtures import issue_dashboard_access


@pytest.mark.asyncio
async def test_authenticated_meal_export_allows_event_loop_progress_during_native_render(
    client,
    db_session,
    monkeypatch,
):
    agency_id, user_id, plan_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db_session.add(
        AgencyModel(id=agency_id, name="Synthetic meal export", email=f"{agency_id}@example.test")
    )
    await db_session.flush()
    db_session.add(
        UserModel(
            id=user_id,
            agency_id=agency_id,
            email=f"{user_id}@example.test",
            full_name="Synthetic operator",
            hashed_password="unused",
            role="agency_admin",
            is_active=True,
        )
    )
    db_session.add(
        MealPlanModel(
            id=plan_id,
            agency_id=agency_id,
            name="Saved snapshot plan",
            trip_days=1,
            selected_category_ids=[],
            generation_seed=1,
        )
    )
    await db_session.flush()
    db_session.add_all(
        [
            MealPlanEntryModel(
                plan_id=plan_id,
                day_number=1,
                meal_type=meal,
                dish_name=f"Synthetic {meal}",
                category_name="Saved category",
            )
            for meal in ("lunch", "dinner")
        ]
    )
    await db_session.commit()
    token, _ = await issue_dashboard_access(
        db_session,
        user_id=user_id,
        role="agency_admin",
        agency_id=agency_id,
    )
    started, progressed = threading.Event(), threading.Event()
    progress_during_render = []
    loop = asyncio.get_running_loop()

    def render(_self, **_kwargs):
        started.set()
        progress_during_render.append(progressed.wait(timeout=0.75))
        return b"PK-synthetic-workbook"

    def observe_loop():
        if started.wait(timeout=3):
            loop.call_soon_threadsafe(progressed.set)

    monkeypatch.setattr(menu.MealPlanExcelExporter, "export", render)
    observer = threading.Thread(target=observe_loop)
    observer.start()
    try:
        response = await client.get(
            f"/api/v1/menu/plans/{plan_id}/export.xlsx",
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        progressed.set()
        observer.join(timeout=3)

    assert not observer.is_alive()
    assert response.status_code == 200, response.text
    assert response.content == b"PK-synthetic-workbook"
    assert progress_during_render == [True]
