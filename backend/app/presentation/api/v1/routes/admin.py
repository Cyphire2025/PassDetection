"""Administrative HTTP router and stable endpoint imports."""

from fastapi import APIRouter

from app.infrastructure.database.session import get_db_session as get_db_session
from app.presentation.api.v1.routes.admin_account_scope import (
    REMOVED_GROUP_STATUSES as REMOVED_GROUP_STATUSES,
)
from app.presentation.api.v1.routes.admin_account_scope import _manager_scope as _manager_scope
from app.presentation.api.v1.routes.admin_account_scope import _staff_scope as _staff_scope
from app.presentation.api.v1.routes.admin_account_views import _group_response as _group_response
from app.presentation.api.v1.routes.admin_account_views import (
    _manager_response as _manager_response,
)
from app.presentation.api.v1.routes.admin_account_views import (
    _validated_credential_state as _validated_credential_state,
)
from app.presentation.api.v1.routes.admin_deletion_queries import _delete_by_ids as _delete_by_ids
from app.presentation.api.v1.routes.admin_deletion_queries import (
    _delete_entity_rows as _delete_entity_rows,
)
from app.presentation.api.v1.routes.admin_deletion_queries import (
    _delete_whatsapp_broadcast_data as _delete_whatsapp_broadcast_data,
)
from app.presentation.api.v1.routes.admin_deletion_queries import (
    _WhatsAppPurgeCounts as _WhatsAppPurgeCounts,
)
from app.presentation.api.v1.routes.admin_group_access import (
    assign_manager_groups as assign_manager_groups,
)
from app.presentation.api.v1.routes.admin_group_access import (
    assign_staff_groups as assign_staff_groups,
)
from app.presentation.api.v1.routes.admin_group_access import list_admin_groups as list_admin_groups
from app.presentation.api.v1.routes.admin_group_access import (
    list_staff_for_access as list_staff_for_access,
)
from app.presentation.api.v1.routes.admin_group_access import router as admin_group_access_router
from app.presentation.api.v1.routes.admin_manager_delete_replay import (
    _previous_manager_delete_result as _previous_manager_delete_result,
)
from app.presentation.api.v1.routes.admin_manager_delete_replay import (
    _PreviousManagerDelete as _PreviousManagerDelete,
)
from app.presentation.api.v1.routes.admin_manager_deletion import delete_manager as delete_manager
from app.presentation.api.v1.routes.admin_manager_deletion import (
    router as admin_manager_deletion_router,
)
from app.presentation.api.v1.routes.admin_passport_purge import (
    PASSPORT_PURGE_INLINE_CLEANUP_MAX_OBJECTS as PASSPORT_PURGE_INLINE_CLEANUP_MAX_OBJECTS,
)
from app.presentation.api.v1.routes.admin_passport_purge import (
    purge_passport_data as purge_passport_data,
)
from app.presentation.api.v1.routes.admin_passport_purge import (
    router as admin_passport_purge_router,
)
from app.presentation.api.v1.routes.admin_platform_settings import (
    DEFAULT_PLATFORM_SETTINGS as DEFAULT_PLATFORM_SETTINGS,
)
from app.presentation.api.v1.routes.admin_platform_settings import (
    PLATFORM_SETTINGS_REVISION_CONFLICT as PLATFORM_SETTINGS_REVISION_CONFLICT,
)
from app.presentation.api.v1.routes.admin_platform_settings import (
    _load_platform_settings as _load_platform_settings,
)
from app.presentation.api.v1.routes.admin_platform_settings import (
    _platform_settings_revision_conflict as _platform_settings_revision_conflict,
)
from app.presentation.api.v1.routes.admin_platform_settings import (
    _same_platform_settings_revision as _same_platform_settings_revision,
)
from app.presentation.api.v1.routes.admin_platform_settings import (
    get_platform_settings as get_platform_settings,
)
from app.presentation.api.v1.routes.admin_platform_settings import (
    router as admin_platform_settings_router,
)
from app.presentation.api.v1.routes.admin_platform_settings import (
    update_platform_settings as update_platform_settings,
)
from app.presentation.api.v1.routes.admin_retention import get_admin_overview as get_admin_overview
from app.presentation.api.v1.routes.admin_retention import (
    get_group_passport_retention as get_group_passport_retention,
)
from app.presentation.api.v1.routes.admin_retention import router as admin_retention_router
from app.presentation.api.v1.routes.admin_workforce import create_manager as create_manager
from app.presentation.api.v1.routes.admin_workforce import list_managers as list_managers
from app.presentation.api.v1.routes.admin_workforce import router as admin_workforce_router

router = APIRouter()
router.include_router(admin_retention_router)
router.include_router(admin_workforce_router)
router.include_router(admin_platform_settings_router)
router.include_router(admin_group_access_router)
router.include_router(admin_manager_deletion_router)
router.include_router(admin_passport_purge_router)
