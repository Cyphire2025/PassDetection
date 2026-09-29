"""Resume observations of durable operations without redispatching their effects."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.types import ToolAnnotations

from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.core.config.settings import Settings
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository, AuditResult
from app.presentation.mcp.invocation import mark_invocation_audited


def register_operation_tools(server: MCPServer, app: FastAPI, settings: Settings) -> None:
    @server.tool(annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False), meta={"capability": "original_operation_capability"})
    async def inspect_operation(operation_id: UUID) -> dict[str, Any]:
        """Resume a saved operation by ID and inspect its current progress and created entities.

        The current connection must belong to the original active superadmin and
        still grant the operation's capability. A revoked original connection does
        not prevent an authorized replacement connection from observing its own
        saved work. Inspection never reexecutes or retries the business action.
        """
        token = get_access_token()
        outcome: AuditResult
        async with app.state.mcp_session_factory() as session:
            try:
                if token is None:
                    raise MCPAuthError("invalid_token", 401)
                result = await MCPOperationService(session, settings, list(app.state.mcp_operations.values())).inspect(
                    access_token=token.token, operation_id=operation_id)
                outcome = "success"
            except MCPAuthError:
                await session.rollback()
                result = {"error": "access_denied", "message": "The connection no longer authorizes this operation."}
                outcome = "denied"
            except MCPOperationError:
                await session.rollback()
                result = {"error": "operation_unavailable", "message": "This operation is not available to this connection or release."}
                outcome = "blocked"
            except Exception:
                await session.rollback()
                result = {"error": "operation_failed", "message": "The operation could not be inspected. Use its audit ID for diagnosis."}
                outcome = "failed"
            audit = await AuditLogRepository(session).record(
                action="mcp.tool.inspect_operation", entity_type="mcp_operation",
                entity_id=str(operation_id), user_id=UUID(token.subject) if token and token.subject else None,
                result=outcome)
            await session.commit()
            mark_invocation_audited()
            result.update(audit_id=str(audit.id), environment=settings.app_env,
                          revision=settings.app_revision, observed_at=datetime.now(UTC).isoformat(),
                          completeness="complete" if outcome == "success" else "unavailable")
            return result
