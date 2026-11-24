"""Bind the canonical menu rules for shared additive creation commands."""

from __future__ import annotations

from app.application.use_cases.menu.create_menu import MenuCreationSupport

from .menu_common import (
    _category_scope,
    _normalized_name,
    _require_current_category_revisions,
    _require_current_revision,
    _utcnow,
)
from .menu_planner import _generate_or_422, _meal_plan_entries, _planner_categories
from .menu_queries import (
    _ensure_category_name_available,
    _ensure_dish_name_available,
    _get_category,
)


def menu_creation_support() -> MenuCreationSupport:
    """Fixed website rules for the shared additive creation use cases."""
    return MenuCreationSupport(
        _normalized_name=_normalized_name,
        _ensure_category_name_available=_ensure_category_name_available,
        _category_scope=_category_scope,
        _get_category=_get_category,
        _require_current_revision=_require_current_revision,
        _ensure_dish_name_available=_ensure_dish_name_available,
        _utcnow=_utcnow,
        _planner_categories=_planner_categories,
        _require_current_category_revisions=_require_current_category_revisions,
        _generate_or_422=_generate_or_422,
        _meal_plan_entries=_meal_plan_entries,
    )
