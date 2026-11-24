"""Dashboard MCP routing: original management, MFA, CSRF and registration order."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.presentation.dependencies.auth import require_recent_mfa
from app.presentation.dependencies.csrf import require_cookie_csrf
from app.presentation.dependencies.mcp import require_mcp_management
from app.presentation.mcp.management_audit import MCPManagementAuditRoute

from .mcp_admin_authorization import approve_connection_request as approve_connection_request
from .mcp_admin_authorization import authorize as authorize
from .mcp_admin_authorization import connection_requests as connection_requests
from .mcp_admin_authorization import control as control
from .mcp_admin_authorization import reject_connection_request as reject_connection_request
from .mcp_admin_connections import connection_payload as connection_payload
from .mcp_admin_connections import connections as connections
from .mcp_admin_connections import delete_connection as delete_connection
from .mcp_admin_connections import revoke as revoke
from .mcp_admin_connections import set_connection_access as set_connection_access
from .mcp_admin_connections import update_connection as update_connection
from .mcp_admin_context import _settings as _settings
from .mcp_admin_files import router as files_router
from .mcp_admin_reads import activity as activity
from .mcp_admin_reads import inventory as inventory
from .mcp_admin_reads import operations as operations
from .mcp_admin_reads import overview as overview
from .mcp_permissions import router as permissions_router

router = APIRouter(
    dependencies=[Depends(require_mcp_management)], route_class=MCPManagementAuditRoute
)
router.include_router(files_router)
router.include_router(permissions_router)
_mutations = [Depends(require_cookie_csrf), Depends(require_recent_mfa)]


# Apply the original decorators directly to the original handler identities.
overview = router.get("")(overview)
connections = router.get("/connections")(connections)
connection_requests = router.get("/connection-requests")(connection_requests)
approve_connection_request = router.post(
    "/connection-requests/{request_id}/approve", dependencies=_mutations
)(approve_connection_request)
reject_connection_request = router.post(
    "/connection-requests/{request_id}/reject", dependencies=_mutations
)(reject_connection_request)
authorize = router.post("/authorize", dependencies=_mutations)(authorize)
control = router.put("/control", dependencies=_mutations)(control)
revoke = router.post("/connections/{connection_id}/revoke", dependencies=_mutations)(revoke)
set_connection_access = router.patch(
    "/connections/{connection_id}/access", dependencies=_mutations
)(set_connection_access)
delete_connection = router.delete("/connections/{connection_id}", dependencies=_mutations)(
    delete_connection
)
update_connection = router.patch("/connections/{connection_id}", dependencies=_mutations)(
    update_connection
)
activity = router.get("/activity")(activity)
inventory = router.get("/inventory")(inventory)
operations = router.get("/operations")(operations)
