"""One audited read boundary; callbacks never receive request-supplied authority."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPAuthorizationService, MCPPrincipal
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.export_capacity import ExportCapacityBusy
from app.application.mcp.operations import (
    MCPDatabaseOperation,
    MCPOperationError,
    MCPOperationService,
)
from app.application.mcp.read_access import require_read_sections
from app.core.config.settings import Settings
from app.domain.mcp_policy import MCPToolPolicy
from app.domain.mcp_read_sections import READ_TOOL_SECTIONS
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository, AuditResult

_audited: ContextVar[bool] = ContextVar("mcp_invocation_audited", default=False)


def mark_invocation_audited() -> None:
    _audited.set(True)


def failure_category(error: Exception) -> str:
    """Keep a static diagnostic cause without exception text, SQL, paths or arguments."""
    if isinstance(error, SQLAlchemyError):
        return "database_error"
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, OSError):
        return "io_error"
    return "operation_failed"


class MCPInputError(ValueError):
    """Only raise with code-owned public messages, never provider/database text."""

    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


class InvocationAuditMiddleware:
    """Record schema/unknown-tool failures which never enter the business wrapper."""

    def __init__(self, app: FastAPI):
        self.app = app

    async def __call__(
        self, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        if ctx.method != "tools/call":
            return await call_next(ctx)
        marker = _audited.set(False)
        try:
            return await call_next(ctx)
        finally:
            try:
                if not _audited.get():
                    token = get_access_token()
                    # Never store raw names or arguments: an unknown name can itself
                    # be attacker-controlled document text or a credential.
                    claims = token.claims if token and token.claims else {}
                    async with self.app.state.mcp_session_factory() as session:
                        await AuditLogRepository(session).record(
                            action="mcp.tool.invalid_request",
                            entity_type="mcp_connection",
                            entity_id=claims.get("grant_id"),
                            user_id=UUID(token.subject) if token and token.subject else None,
                            result="denied",
                            metadata={"reason": "unsupported_or_invalid_tool_request"},
                        )
                        await session.commit()
            finally:
                _audited.reset(marker)


async def invoke_read(
    app: FastAPI,
    settings: Settings,
    policy: MCPToolPolicy,
    operation: Callable[[AsyncSession, MCPPrincipal], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    policy.validate()
    if policy.effects != frozenset({"read"}):
        raise ValueError("Read invocation cannot execute mutation policies")
    token = get_access_token()
    principal: MCPPrincipal | None = None
    result: dict[str, Any]
    outcome: AuditResult
    diagnostic: str | None = None
    async with app.state.mcp_session_factory() as session:
        try:
            if token is None:
                raise MCPAuthError("invalid_token", 401)
            authorization = MCPAuthorizationService(session, settings)
            if settings.mcp.read_only_mode:
                # Hold the global control lock before token/grant writes, through
                # the read and audit commit. Pause and section saves serialize
                # against in-flight reads using the worker's control-first order.
                await authorization.require_enabled(lock=True)
            principal = await authorization.verify_access(
                token.token,
                policy.capability.value,
            )
            if settings.mcp.read_only_mode:
                await require_read_sections(session, policy.name)
            result = await operation(session, principal)
        except MCPAuthError as exc:
            await session.rollback()
            outcome = "denied"
            diagnostic = "authorization_denied"
            result = {
                "error": "access_denied",
                "message": "The connection no longer authorizes this operation.",
            }
            if settings.mcp.read_only_mode and policy.name in READ_TOOL_SECTIONS:
                result["required_sections"] = sorted(READ_TOOL_SECTIONS[policy.name])
                if exc.error == "read_section_denied":
                    diagnostic = "read_section_denied"
                    result["message"] = "MCP reading is disabled for one or more sections needed by this tool. Review Codex access."
        except MCPInputError as exc:
            await session.rollback()
            outcome = "blocked"
            diagnostic = "business_input"
            result = {"error": exc.code, "message": exc.message, "requires_input": True}
        except Exception as exc:
            # Do not return database/provider exceptions, args, credentials or document contents.
            await session.rollback()
            outcome = "failed"
            diagnostic = failure_category(exc)
            result = {
                "error": "operation_failed",
                "message": "The operation failed. Use its audit ID for diagnosis.",
            }
        else:
            outcome = "success"
        result.update(environment=settings.app_env, revision=settings.app_revision,
                      observed_at=datetime.now(UTC).isoformat())
        result.setdefault("completeness", "unavailable" if outcome != "success" else "complete")
        audit = await AuditLogRepository(session).record(
            action=f"mcp.tool.{policy.name}",
            entity_type="mcp_connection",
            entity_id=str(principal.grant_id) if principal else None,
            user_id=principal.user_id if principal else None,
            result=outcome,
            metadata={"capability": policy.capability.value, "failure_category": diagnostic},
        )
        result["audit_id"] = str(audit.id)
        await session.commit()
        _audited.set(True)
    return result


async def invoke_operation(
    app: FastAPI, settings: Settings, definition: MCPDatabaseOperation,
    *, idempotency_key: str, payload: dict[str, Any],
) -> dict[str, Any]:
    """Commit one explicitly registered business operation and its invocation audit.

    The saved receipt is immutable across retries; observation/audit metadata
    describes this call separately. Provider dispatch does not belong here.
    """
    definition.policy.validate()
    token = get_access_token()
    receipt: dict[str, Any] | None = None
    outcome: AuditResult
    diagnostic: str | None = None
    async with app.state.mcp_session_factory() as session:
        try:
            if token is None:
                raise MCPAuthError("invalid_token", 401)
            receipt = await MCPOperationService(session, settings, [definition]).execute(
                access_token=token.token, operation_name=definition.policy.name,
                idempotency_key=idempotency_key, payload=payload)
            result: dict[str, Any] = {"receipt": receipt, "completeness": "complete"}
            outcome = "success"
        except MCPAuthError:
            await session.rollback()
            outcome = "denied"
            diagnostic = "authorization_denied"
            result = {"error": "access_denied", "message": "The connection no longer authorizes this operation."}
        except MCPOperationError as exc:
            await session.rollback()
            outcome = "blocked"
            diagnostic = "business_input"
            messages = {
                "invalid_notification_acknowledgement": "Select exactly one notification ID from your personal feed.",
                "notification_unavailable": "The notification is no longer available in your personal feed.",
                "notification_busy": "The notification is being updated. Retry the same notification and idempotency key.",
                "idempotency_conflict": "This retry key belongs to different input. Inspect the earlier operation before continuing.",
                "invalid_idempotency_key": "Provide a stable retry key of 16 to 256 characters.",
                "operation_receipt_unavailable": "The saved receipt is unavailable. Diagnose this operation before retrying.",
                "client_details_changed_or_unavailable": "Inspect the current client details and revision before applying these corrections again.",
                "client_details_delivery_pending": "A private delivery is pending for this submission. Check its outcome before correcting client details.",
                "invalid_client_details": "Inspect the editable fields and choices, then provide only documented, nonempty corrections.",
                "invalid_whatsapp_plan": "Use the saved WhatsApp plan identifier and its exact preview hash.",
                "whatsapp_plan_hash_mismatch": "The preview hash does not match this saved plan. Inspect the exact plan before confirming.",
                "whatsapp_plan_expired_or_closed": "This plan has expired or is closed. Inspect its status before preparing a new message.",
                "whatsapp_plan_changed": "The audience, message or eligibility changed. Prepare and review a new exact preview before sending.",
                "whatsapp_service_unavailable": "WhatsApp service setup is unavailable. This is not missing recipient or message information. This attempt queued no messages; retain its retry key and ask an administrator to check the service setup.",
                "whatsapp_plan_audience_unavailable": "The selected audience is unavailable. Inspect the current broadcast and choose eligible recipients.",
                "invalid_contact_broadcast": "Review broadcast details, support contacts and opt-in.",
                "invalid_contact_mapping": "Choose existing worksheets and distinct one-based phone/name columns.",
                "contact_name_too_long": "Recipient names must be 100 characters or fewer; correct the source workbook.",
                "contact_import_capacity_exceeded": "The selected data exceeds recipient or 500 rejected-row limits; no rows were imported.",
                "contact_import_empty": "The selected mapping contains no contacts.",
                "contact_opt_in_required": "Confirm recipient WhatsApp opt-in before creation.",
                "contact_upload_unavailable": "The original connection's workbook is unavailable or expired.",
                "contact_upload_already_used": "This workbook already created a broadcast; retry its original operation key.",
                "contact_preview_changed": "Review a fresh preview and supply its unchanged SHA-256.",
                "invalid_gc_push_plan": "Use the saved GC push plan ID and its exact reviewed preview hash.",
                "gc_push_plan_hash_mismatch": "The hash does not match this saved GC push plan. Inspect the exact saved preview before confirming.",
                "gc_push_plan_expired_or_closed": "This GC push plan is expired or closed. Prepare a fresh preview; this attempt queued no sends.",
                "gc_push_plan_changed": "The draft, audience or device targets changed. Prepare and review a fresh exact preview before confirming.",
                "gc_push_audience_unavailable": "Choose 1 to 10 active groups, 1 to 100 people and no more than 300 eligible device targets under current policy.",
            }
            result = {"error": exc.code if exc.code in messages else "operation_blocked",
                      "message": messages.get(exc.code, "The operation could not be applied. Use its audit ID for diagnosis.")}
        except ExportCapacityBusy:
            await session.rollback()
            outcome = "blocked"
            diagnostic = "export_capacity_busy"
            result = {
                "error": "export_busy",
                "message": "Export capacity is busy. Retry the identical request with its original retry key, or resume its saved operation ID later.",
            }
        except MCPInputError as exc:
            await session.rollback()
            outcome = "blocked"
            diagnostic = "business_input"
            result = {"error": exc.code, "message": exc.message, "requires_input": True}
        except Exception as exc:
            await session.rollback()
            outcome = "failed"
            diagnostic = failure_category(exc)
            result = {"error": "operation_failed", "message": "The operation failed. Use its audit ID for diagnosis."}
        claims = token.claims if token and token.claims else {}
        audit = await AuditLogRepository(session).record(
            action=f"mcp.tool.{definition.policy.name}", entity_type="mcp_operation",
            entity_id=receipt["operation_id"] if receipt else None,
            user_id=UUID(token.subject) if token and token.subject else None,
            result=outcome,
            metadata={"capability": definition.policy.capability.value, "connection_id": claims.get("grant_id"),
                      "failure_category": diagnostic})
        await session.commit()
        _audited.set(True)
        result.update(audit_id=str(audit.id), environment=settings.app_env,
                      revision=settings.app_revision, observed_at=datetime.now(UTC).isoformat())
        result.setdefault("completeness", "unavailable")
        return result
