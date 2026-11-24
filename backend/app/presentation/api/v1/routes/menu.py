"""Menu route composition and preserved canonical helper import contracts."""

from fastapi import APIRouter

from app.infrastructure.export.meal_plan_excel_exporter import (
    MealPlanExcelExporter as MealPlanExcelExporter,
)
from app.infrastructure.export.meal_plan_excel_exporter import (
    MealPlanExportEntry as MealPlanExportEntry,
)

from .menu_categories import (
    create_menu_category as create_menu_category,
)
from .menu_categories import (
    delete_menu_category as delete_menu_category,
)
from .menu_categories import router as _menu_categories_router
from .menu_categories import (
    update_menu_category as update_menu_category,
)
from .menu_common import MENU_ROLES as MENU_ROLES
from .menu_common import (
    _agency_scope as _agency_scope,
)
from .menu_common import (
    _audit as _audit,
)
from .menu_common import (
    _category_scope as _category_scope,
)
from .menu_common import (
    _excel_filename as _excel_filename,
)
from .menu_common import (
    _normalized_name as _normalized_name,
)
from .menu_common import (
    _normalized_revision as _normalized_revision,
)
from .menu_common import (
    _plan_scope as _plan_scope,
)
from .menu_common import (
    _require_current_category_revisions as _require_current_category_revisions,
)
from .menu_common import (
    _require_current_revision as _require_current_revision,
)
from .menu_common import (
    _utcnow as _utcnow,
)
from .menu_creation_support import menu_creation_support as menu_creation_support
from .menu_dishes import (
    create_menu_dish as create_menu_dish,
)
from .menu_dishes import (
    delete_menu_dish as delete_menu_dish,
)
from .menu_dishes import router as _menu_dishes_router
from .menu_dishes import (
    update_menu_dish as update_menu_dish,
)
from .menu_exports import export_meal_plan as export_meal_plan
from .menu_exports import router as _menu_exports_router
from .menu_plan_entries import router as _menu_plan_entries_router
from .menu_plan_entries import update_meal_plan_entry as update_meal_plan_entry
from .menu_planner import (
    _generate_or_422 as _generate_or_422,
)
from .menu_planner import (
    _meal_plan_entries as _meal_plan_entries,
)
from .menu_planner import (
    _planner_categories as _planner_categories,
)
from .menu_plans import (
    delete_meal_plan as delete_meal_plan,
)
from .menu_plans import (
    generate_meal_plan as generate_meal_plan,
)
from .menu_plans import (
    regenerate_meal_plan as regenerate_meal_plan,
)
from .menu_plans import router as _menu_plans_router
from .menu_plans import (
    update_meal_plan as update_meal_plan,
)
from .menu_presenters import (
    _category_response as _category_response,
)
from .menu_presenters import (
    _dish_response as _dish_response,
)
from .menu_presenters import (
    _entry_response as _entry_response,
)
from .menu_presenters import (
    _plan_response as _plan_response,
)
from .menu_queries import (
    _ensure_category_name_available as _ensure_category_name_available,
)
from .menu_queries import (
    _ensure_dish_name_available as _ensure_dish_name_available,
)
from .menu_queries import (
    _get_category as _get_category,
)
from .menu_queries import (
    _get_dish as _get_dish,
)
from .menu_queries import (
    _get_plan as _get_plan,
)
from .menu_workspace import get_menu_workspace as get_menu_workspace
from .menu_workspace import router as _menu_workspace_router

router = APIRouter()

# The workspace keeps the original empty local path; the outer API adds /menu.
# FastAPI rejects include_router on an empty path without that outer prefix.
router.routes.extend(_menu_workspace_router.routes)

router.include_router(_menu_categories_router)

router.include_router(_menu_dishes_router)

router.include_router(_menu_plans_router)

router.include_router(_menu_plan_entries_router)

router.include_router(_menu_exports_router)
