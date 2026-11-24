"""Compatibility imports and resource routers for GC administration."""

from fastapi import APIRouter

from app.core.security.mobile_jwt import hash_mobile_lookup as hash_mobile_lookup
from app.presentation.api.v1.routes.gc_app_group_directory import (
    list_gc_agencies as list_gc_agencies,
)
from app.presentation.api.v1.routes.gc_app_group_directory import (
    router as _gc_app_group_directory_router,
)
from app.presentation.api.v1.routes.gc_app_group_directory import (
    search_gc_groups as search_gc_groups,
)
from app.presentation.api.v1.routes.gc_app_group_settings import (
    _group_access_response as _group_access_response,
)
from app.presentation.api.v1.routes.gc_app_group_settings import (
    configure_gc_group_access as configure_gc_group_access,
)
from app.presentation.api.v1.routes.gc_app_group_settings import (
    configure_gc_group_my_photos_feature as configure_gc_group_my_photos_feature,
)
from app.presentation.api.v1.routes.gc_app_group_settings import (
    get_gc_group_access as get_gc_group_access,
)
from app.presentation.api.v1.routes.gc_app_group_settings import (
    refresh_mobile_passenger_identities as refresh_mobile_passenger_identities,
)
from app.presentation.api.v1.routes.gc_app_group_settings import (
    router as _gc_app_group_settings_router,
)
from app.presentation.api.v1.routes.gc_app_manager_access import (
    replace_client_manager_groups as replace_client_manager_groups,
)
from app.presentation.api.v1.routes.gc_app_manager_access import (
    reset_client_manager_password as reset_client_manager_password,
)
from app.presentation.api.v1.routes.gc_app_manager_access import (
    revoke_client_manager_sessions as revoke_client_manager_sessions,
)
from app.presentation.api.v1.routes.gc_app_manager_access import (
    router as _gc_app_manager_access_router,
)
from app.presentation.api.v1.routes.gc_app_manager_creation import (
    create_client_manager as create_client_manager,
)
from app.presentation.api.v1.routes.gc_app_manager_creation import (
    router as _gc_app_manager_creation_router,
)
from app.presentation.api.v1.routes.gc_app_manager_directory import (
    list_client_manager_audit as list_client_manager_audit,
)
from app.presentation.api.v1.routes.gc_app_manager_directory import (
    list_client_manager_sessions as list_client_manager_sessions,
)
from app.presentation.api.v1.routes.gc_app_manager_directory import (
    list_client_managers as list_client_managers,
)
from app.presentation.api.v1.routes.gc_app_manager_directory import (
    router as _gc_app_manager_directory_router,
)
from app.presentation.api.v1.routes.gc_app_manager_profile import (
    delete_client_manager as delete_client_manager,
)
from app.presentation.api.v1.routes.gc_app_manager_profile import (
    force_client_manager_password_change as force_client_manager_password_change,
)
from app.presentation.api.v1.routes.gc_app_manager_profile import (
    router as _gc_app_manager_profile_router,
)
from app.presentation.api.v1.routes.gc_app_manager_profile import (
    set_client_manager_status as set_client_manager_status,
)
from app.presentation.api.v1.routes.gc_app_manager_profile import (
    update_client_manager as update_client_manager,
)
from app.presentation.api.v1.routes.gc_app_manager_support import (
    _manager_group_map as _manager_group_map,
)
from app.presentation.api.v1.routes.gc_app_manager_support import (
    _validate_manager_groups as _validate_manager_groups,
)
from app.presentation.api.v1.routes.gc_app_organizations import (
    create_client_organization as create_client_organization,
)
from app.presentation.api.v1.routes.gc_app_organizations import (
    delete_client_organization as delete_client_organization,
)
from app.presentation.api.v1.routes.gc_app_organizations import (
    list_client_organizations as list_client_organizations,
)
from app.presentation.api.v1.routes.gc_app_organizations import (
    router as _gc_app_organizations_router,
)
from app.presentation.api.v1.routes.gc_app_organizations import (
    search_client_organizations as search_client_organizations,
)
from app.presentation.api.v1.routes.gc_app_scope import (
    GC_ADMIN_ROLES as GC_ADMIN_ROLES,
)
from app.presentation.api.v1.routes.gc_app_scope import (
    MobileAudience as MobileAudience,
)
from app.presentation.api.v1.routes.gc_app_scope import (
    _audit as _audit,
)
from app.presentation.api.v1.routes.gc_app_scope import (
    _client_manager_duplicate_message as _client_manager_duplicate_message,
)
from app.presentation.api.v1.routes.gc_app_scope import (
    _client_manager_response as _client_manager_response,
)
from app.presentation.api.v1.routes.gc_app_scope import (
    _client_manager_status as _client_manager_status,
)
from app.presentation.api.v1.routes.gc_app_scope import (
    _get_client_manager as _get_client_manager,
)
from app.presentation.api.v1.routes.gc_app_scope import (
    _get_group as _get_group,
)
from app.presentation.api.v1.routes.gc_app_scope import (
    _get_group_access as _get_group_access,
)
from app.presentation.api.v1.routes.gc_app_scope import (
    _get_organization as _get_organization,
)
from app.presentation.api.v1.routes.gc_app_scope import (
    _integrity_constraint_name as _integrity_constraint_name,
)
from app.presentation.api.v1.routes.gc_app_scope import (
    _organization_response as _organization_response,
)
from app.presentation.api.v1.routes.gc_app_scope import (
    _organization_status as _organization_status,
)
from app.presentation.api.v1.routes.gc_app_scope import (
    _require_revision as _require_revision,
)
from app.presentation.api.v1.routes.gc_app_scope import (
    _tenant_id as _tenant_id,
)
from app.presentation.api.v1.routes.gc_app_sessions import (
    _revoke_group_mobile_sessions as _revoke_group_mobile_sessions,
)
from app.presentation.api.v1.routes.gc_app_sessions import (
    _revoke_mobile_sessions as _revoke_mobile_sessions,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ClientManagerAssignedGroupResponse as ClientManagerAssignedGroupResponse,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ClientManagerAssignmentRequest as ClientManagerAssignmentRequest,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ClientManagerCreateRequest as ClientManagerCreateRequest,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ClientManagerForcePasswordChangeRequest as ClientManagerForcePasswordChangeRequest,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ClientManagerPageResponse as ClientManagerPageResponse,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ClientManagerPasswordResetRequest as ClientManagerPasswordResetRequest,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ClientManagerResponse as ClientManagerResponse,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ClientManagerSessionPageResponse as ClientManagerSessionPageResponse,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ClientManagerStatusRequest as ClientManagerStatusRequest,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ClientManagerUpdateRequest as ClientManagerUpdateRequest,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ClientOrganizationCreateRequest as ClientOrganizationCreateRequest,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ClientOrganizationPageResponse as ClientOrganizationPageResponse,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ClientOrganizationResponse as ClientOrganizationResponse,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    GCAgencyPageResponse as GCAgencyPageResponse,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    GCAgencyResponse as GCAgencyResponse,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    GCAppAuditPageResponse as GCAppAuditPageResponse,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    GCGroupAccessResponse as GCGroupAccessResponse,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    GCGroupAccessUpdateRequest as GCGroupAccessUpdateRequest,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    GCGroupSearchAccess as GCGroupSearchAccess,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    GCGroupSearchItem as GCGroupSearchItem,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    GCGroupSearchPageResponse as GCGroupSearchPageResponse,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    GCMyPhotosFeatureUpdateRequest as GCMyPhotosFeatureUpdateRequest,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    PassengerIdentityReconciliationResponse as PassengerIdentityReconciliationResponse,
)

router = APIRouter()
router.include_router(_gc_app_group_directory_router)
router.include_router(_gc_app_group_settings_router)
router.include_router(_gc_app_organizations_router)
router.include_router(_gc_app_manager_directory_router)
router.include_router(_gc_app_manager_creation_router)
router.include_router(_gc_app_manager_profile_router)
router.include_router(_gc_app_manager_access_router)
