"""Safe denied-management outcomes, persisted after request transaction cleanup."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging.logger import get_logger
from app.domain.exceptions.exceptions import (
    AuthenticationError,
    AuthorizationError,
    StepUpRequiredError,
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository, AuditResult

logger = get_logger(__name__)

# Only these code-owned endpoint names identify an administration operation.
_OPERATIONS = {
    "get_read_access": "read_access",
    "set_read_access": "read_access",
    "get_permissions": "permissions",
    "set_permissions": "permissions",
    "set_connection_permissions": "connection_permissions",
    "overview": "overview",
    "connections": "connections",
    "authorize": "authorize",
    "control": "control",
    "revoke": "revoke",
    "delete_connection": "delete_connection",
    "update_connection": "update_connection",
    "set_connection_access": "connection_access",
    "connection_requests": "connection_requests",
    "approve_connection_request": "request_approve",
    "reject_connection_request": "request_reject",
    "activity": "activity",
    "inventory": "inventory",
    "operations": "operations",
    "artifacts": "artifacts",
}
_REASONS = {
    400: "invalid_request",
    401: "authentication_required",
    403: "access_denied",
    404: "record_unavailable",
    409: "state_conflict",
    422: "invalid_request",
    429: "rate_limited",
    503: "service_unavailable",
}


def _exception_outcome(error: Exception) -> tuple[int, str]:
    if isinstance(error, StepUpRequiredError):
        return 403, "recent_mfa_required"
    if isinstance(error, AuthenticationError):
        return 401, "authentication_required"
    if isinstance(error, AuthorizationError):
        return 403, "access_denied"
    if isinstance(error, RequestValidationError):
        return 422, "invalid_request"
    if isinstance(error, HTTPException):
        return error.status_code, _REASONS.get(error.status_code, "request_rejected")
    return 500, "operation_failed"


def _identifier(value: object) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    if not isinstance(value, str) or len(value) != 36:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


async def _persist(scope: Scope, operation: str, status: int, reason: str) -> None:
    state = scope.get("state", {})
    claims = state.get("auth_claims", {})
    actor = _identifier(claims.get("sub")) if isinstance(claims, dict) else None
    connection = _identifier(scope.get("path_params", {}).get("connection_id"))
    approval_request = _identifier(scope.get("path_params", {}).get("request_id")) if operation in {"request_approve", "request_reject"} else None
    result: AuditResult = "failed" if status >= 500 else "denied" if status in {401, 403} else "blocked"
    factory = getattr(scope["app"].state, "mcp_management_audit_session_factory", AsyncSessionFactory)
    async with factory() as session:
        await AuditLogRepository(session).record(
            action="mcp.management_rejected",
            entity_type="mcp_connection_request" if approval_request else "mcp_control" if operation in {"control", "read_access", "permissions"} else "mcp_connection",
            entity_id=str(approval_request or connection) if approval_request or connection else None,
            user_id=actor,
            result=result,
            metadata={"operation": operation, "reason": reason, "http_status": status},
        )
        await session.commit()


async def _record(scope: Scope, operation: str, status: int, reason: str) -> None:
    try:
        # Separate session: never commit a rejected handler's pending business data.
        # Bound audit availability without replacing the original HTTP outcome.
        async with asyncio.timeout(3):
            await _persist(scope, operation, status, reason)
    except Exception:
        logger.error("mcp_management_audit_unavailable", operation=operation)


class _ManagementAuditApp:
    def __init__(self, app: ASGIApp, operation: str):
        self.app, self.operation = app, operation

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        status = 200

        async def observe(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, observe)
        except Exception as error:
            status, reason = _exception_outcome(error)
            await _record(scope, self.operation, status, reason)
            raise
        else:
            if status >= 400:
                outcome = scope.get("mcp_management_audit_outcome")
                reason = outcome[1] if outcome and outcome[0] == status else _REASONS.get(status, "request_rejected")
                await _record(scope, self.operation, status, reason)


class MCPManagementAuditRoute(APIRoute):
    """Wrap the route ASGI app, outside its request dependency exit stacks.

    Existing successful/role-denial audits remain authoritative. This adds one
    fixed per-operation failure outcome, including returned OAuth error responses.
    It does not decode credentials, inspect bodies or change authorization.
    The response may already have started when this separate audit commits.
    An unavailable audit store preserves the rejection and emits a fixed event;
    that outage does not provide a guaranteed durable audit record.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        operation = _OPERATIONS.get(getattr(self.endpoint, "__name__", ""))
        if operation is not None:
            self.app = _ManagementAuditApp(self.app, operation)

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def observe_exception(request: Request) -> Response:
            try:
                return await handler(request)
            except Exception as error:
                # FastAPI can translate this before its ASGI app returns. Save
                # only the static classification; write after dependency cleanup.
                request.scope["mcp_management_audit_outcome"] = _exception_outcome(error)
                raise

        return observe_exception
