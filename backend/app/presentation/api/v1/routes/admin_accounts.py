"""Managed-account HTTP composition and stable callable/request imports."""

from fastapi import APIRouter

from app.presentation.api.v1.routes.managed_account_creation import (
    create_staff_account as create_staff_account,
)
from app.presentation.api.v1.routes.managed_account_creation import (
    router as managed_account_creation_router,
)
from app.presentation.api.v1.routes.managed_account_credentials import (
    reset_managed_account_mfa as reset_managed_account_mfa,
)
from app.presentation.api.v1.routes.managed_account_credentials import (
    reset_managed_account_password as reset_managed_account_password,
)
from app.presentation.api.v1.routes.managed_account_credentials import (
    revoke_managed_account_sessions as revoke_managed_account_sessions,
)
from app.presentation.api.v1.routes.managed_account_credentials import (
    router as managed_account_credentials_router,
)
from app.presentation.api.v1.routes.managed_account_mutations import (
    delete_managed_account as delete_managed_account,
)
from app.presentation.api.v1.routes.managed_account_mutations import (
    router as managed_account_mutations_router,
)
from app.presentation.api.v1.routes.managed_account_mutations import (
    set_managed_account_status as set_managed_account_status,
)
from app.presentation.api.v1.routes.managed_account_queries import (
    list_managed_accounts as list_managed_accounts,
)
from app.presentation.api.v1.routes.managed_account_queries import (
    list_staff_accounts as list_staff_accounts,
)
from app.presentation.api.v1.routes.managed_account_queries import (
    router as managed_account_queries_router,
)
from app.presentation.api.v1.routes.managed_account_scope import (
    ACCOUNT_ADMIN_ROLES as ACCOUNT_ADMIN_ROLES,
)
from app.presentation.api.v1.routes.managed_account_scope import (
    LISTED_ACCOUNT_ROLES as LISTED_ACCOUNT_ROLES,
)
from app.presentation.api.v1.routes.managed_account_scope import MANAGED_ROLES as MANAGED_ROLES
from app.presentation.api.v1.routes.managed_account_scope import (
    STAFF_ADMIN_ROLES as STAFF_ADMIN_ROLES,
)
from app.presentation.api.v1.routes.managed_account_scope import (
    _get_manageable_account as _get_manageable_account,
)
from app.presentation.api.v1.routes.managed_account_sessions import (
    _deactivate_coordinator_assignments as _deactivate_coordinator_assignments,
)
from app.presentation.api.v1.routes.managed_account_sessions import (
    _fence_coordinator_mobile_sessions as _fence_coordinator_mobile_sessions,
)
from app.presentation.api.v1.routes.managed_account_sessions import (
    _fence_dashboard_sessions as _fence_dashboard_sessions,
)
from app.presentation.api.v1.routes.managed_account_values import (
    _account_response as _account_response,
)
from app.presentation.api.v1.routes.managed_account_values import (
    _audit_account_action as _audit_account_action,
)
from app.presentation.api.v1.routes.managed_account_values import (
    _validated_credential_state as _validated_credential_state,
)
from app.presentation.api.v1.schemas.operations_schemas import (
    CreateStaffRequest as CreateStaffRequest,
)
from app.presentation.api.v1.schemas.operations_schemas import (
    DeleteManagedAccountResponse as DeleteManagedAccountResponse,
)
from app.presentation.api.v1.schemas.operations_schemas import (
    ManagedAccountResponse as ManagedAccountResponse,
)
from app.presentation.api.v1.schemas.operations_schemas import (
    ResetManagedAccountPasswordRequest as ResetManagedAccountPasswordRequest,
)
from app.presentation.api.v1.schemas.operations_schemas import (
    SetManagedAccountStatusRequest as SetManagedAccountStatusRequest,
)

router = APIRouter()
# This collection retains its original empty path until the application mounts
# facade under /admin/accounts. FastAPI rejects including it with an empty prefix.
router.routes.extend(managed_account_queries_router.routes)
router.include_router(managed_account_creation_router)
router.include_router(managed_account_credentials_router)
router.include_router(managed_account_mutations_router)
