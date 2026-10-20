"""Signed-in assistant access to the shared, audited MCP tool registry.

External OAuth connections and global permissions are never changed. Invocation
uses a private first-party authority; discovery is observational and creates none.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.types import Tool
from sqlalchemy import delete, select

from app.application.assistant.contracts import AssistantError
from app.application.mcp.assistant_authority import (
    ensure_assistant_authority,
    validate_assistant_authority,
)
from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError, new_credential, utc
from app.core.config.settings import get_settings
from app.domain.assistant_identity import ASSISTANT_CLIENT_ID
from app.domain.entities.entities import User, UserRole
from app.infrastructure.assistant.settings_store import load_snapshot
from app.infrastructure.database.mcp_models import MCPGrantModel, MCPTokenModel
from app.infrastructure.database.session import AsyncSessionFactory
from app.presentation.assistant.reads import fresh_actor
from app.presentation.mcp.permission_listing import tool_access_snapshot

MCP_TOOLS = [
    {"type": "function", "name": "list_mcp_tools", "strict": False,
     "description": "Discover currently permitted MCP tools and their exact argument schemas. Search by topic or name, and paginate before concluding access is unavailable. These tools are the authority for workspace access.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string", "maxLength": 120}, "offset": {"type": "integer", "minimum": 0}}, "additionalProperties": False}},
    {"type": "function", "name": "call_mcp_tool", "strict": False,
     "description": "Invoke a tool discovered with list_mcp_tools, using its exact schema. arguments_json is a JSON object encoded as a string. Only perform a write when the user requested that action. MCP authorization, validation, audit and idempotency remain authoritative.",
     "parameters": {"type": "object", "properties": {"tool_name": {"type": "string", "maxLength": 120}, "arguments_json": {"type": "string", "maxLength": 18000}}, "required": ["tool_name", "arguments_json"], "additionalProperties": False}},
]


def observational(tool: Tool) -> bool:
    return bool(tool.annotations and tool.annotations.read_only_hint is True
                and (tool.meta or {}).get("capability") in {"mcp:read", "mcp:diagnose"})


async def connection_choices(user: User) -> list[dict[str, Any]]:
    async with AsyncSessionFactory() as session:
        grants = (await session.scalars(select(MCPGrantModel).where(
            MCPGrantModel.user_id == user.id, MCPGrantModel.enabled.is_(True),
            MCPGrantModel.client_id != ASSISTANT_CLIENT_ID,
            MCPGrantModel.revoked_at.is_(None), MCPGrantModel.expires_at > datetime.now(UTC),
        ).order_by(MCPGrantModel.created_at.desc()))).all()
        settings = get_settings()
        items = []
        for grant in grants:
            try:
                await MCPAuthorizationService(session, settings).require_grant(grant.id)
                access = await tool_access_snapshot(session, settings, grant=grant)
                items.append({"id": str(grant.id), "name": grant.name, "read_enabled": access.read_enabled, "write_enabled": access.write_enabled})
            except MCPAuthError:
                continue
        return items


class MCPAssistantBridge:
    def __init__(self, request: Request, user: User):
        self.request, self.user = request, user

    async def _authority(self, session: Any) -> tuple[User, list[Tool], bool]:
        actor = await fresh_actor(self.user)
        if actor.role != UserRole.SUPER_ADMIN or actor.actual_role is not None and actor.actual_role != actor.role:
            raise AssistantError("mcp_access_denied", "Workspace MCP tools require this account's super administrator access.", 403)
        server = getattr(self.request.app.state, "mcp_server", None)
        if server is None:
            raise AssistantError("mcp_unavailable", "The workspace MCP service is unavailable.", 503)
        settings = get_settings()
        try:
            await validate_assistant_authority(session, settings, actor, getattr(self.request.state, "auth_claims", {}))
            snapshot = await load_snapshot(session)
            access = await tool_access_snapshot(session, settings)
        except MCPAuthError as exc:
            raise self._access_error(exc) from None
        allowed = access.filter_tools(await server.list_tools())
        write = snapshot.configuration.mcp_write_enabled
        tools = [tool for tool in allowed if write or observational(tool)]
        return actor, tools, any(not observational(tool) for tool in tools)

    @staticmethod
    def _access_error(exc: MCPAuthError) -> AssistantError:
        if exc.error == "assistant_mfa_required":
            return AssistantError("mcp_sign_in_required", "Sign in to the dashboard with two-step verification to use workspace tools.", 403)
        if exc.error == "temporarily_unavailable":
            return AssistantError("mcp_unavailable", "Workspace MCP access is currently paused or unavailable.", 503)
        return AssistantError("mcp_access_denied", "Your signed-in account cannot currently use workspace MCP tools. Review your account and AI access settings.", 403)

    async def status(self) -> dict[str, Any]:
        try:
            async with AsyncSessionFactory() as session:
                if not (await load_snapshot(session)).configuration.enabled:
                    raise AssistantError("mcp_ai_disabled", "Enable the AI assistant in settings to use workspace tools.", 403)
            access = await self.discover()
            if not access["total"]:
                raise AssistantError("mcp_no_tools", "Current MCP permissions expose no tools for the assistant. Review workspace permissions and AI settings.", 403)
            return {"observed_at": access["observed_at"], "mcp": {"connected": True, "available_tools": access["total"], "write_enabled": access["write_enabled"]}}
        except AssistantError as exc:
            return {"observed_at": datetime.now(UTC).isoformat(), "mcp": {"connected": False, "available_tools": 0, "write_enabled": False, "code": exc.code, "message": exc.message}}

    async def discover(self, query: str = "", offset: int = 0) -> dict[str, Any]:
        if not isinstance(query, str) or len(query) > 120 or type(offset) is not int or not 0 <= offset <= 10000:
            raise AssistantError("query_rejected", "Use a short tool search and valid offset.", 422)
        async with AsyncSessionFactory() as session:
            _, tools, write = await self._authority(session)
        terms = query.casefold().split()
        matches = [tool for tool in tools if all(term in (tool.name + " " + (tool.description or "")).casefold() for term in terms)]
        page = matches[offset:offset + 8]
        return {"tools": [{"name": tool.name, "description": tool.description, "input_schema": tool.input_schema, "read_only": observational(tool)} for tool in page],
                "total": len(matches), "next_offset": offset + 8 if offset + 8 < len(matches) else None,
                "write_enabled": write, "observed_at": datetime.now(UTC).isoformat(),
                "notice": "These tools use your signed-in dashboard account and current workspace MCP permissions. Each invocation rechecks live access; no external MCP app connection is needed."}

    async def call(self, tool_name: str, arguments_json: str) -> dict[str, Any]:
        if not isinstance(tool_name, str) or len(tool_name) > 120 or not isinstance(arguments_json, str) or len(arguments_json) > 18000:
            raise AssistantError("query_rejected", "The MCP request is invalid.", 422)
        try:
            arguments = json.loads(arguments_json)
            if not isinstance(arguments, dict):
                raise ValueError()
        except ValueError:
            raise AssistantError("query_rejected", "MCP arguments must be a JSON object.", 422) from None
        # The MCP wrapper owns the transaction that checks and locks live AI
        # settings with workspace policy. Do not hold locks in a second session
        # while waiting for that transaction: a queued settings save could stall it.
        return await self._invoke(tool_name, arguments)

    async def _invoke(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        settings = get_settings()
        raw = new_credential("access")
        async with AsyncSessionFactory() as session:
            actor, tools, _ = await self._authority(session)
            if not any(tool.name == tool_name for tool in tools):
                raise AssistantError("mcp_tool_denied", "This tool is not permitted by current workspace MCP permissions and the AI write setting.", 403)
            try:
                grant = await ensure_assistant_authority(session, settings, actor, getattr(self.request.state, "auth_claims", {}))
            except MCPAuthError as exc:
                raise self._access_error(exc) from None
            auth = MCPAuthorizationService(session, settings)
            digest = auth.digest(raw)
            now = datetime.now(UTC)
            expires = min(now + timedelta(seconds=90), utc(grant.expires_at))
            session.add(MCPTokenModel(token_hash=digest, grant_id=grant.id, kind="access", created_at=now, expires_at=expires))
            token = AccessToken(token=raw, client_id=grant.client_id, scopes=list(grant.capabilities), subject=str(grant.user_id),
                                resource=grant.resource, expires_at=int(expires.timestamp()), claims={"grant_id": str(grant.id)})
            await session.commit()
        context = auth_context_var.set(AuthenticatedUser(token))
        try:
            async with asyncio.timeout(60):
                result = await self.request.app.state.mcp_server.call_tool(tool_name, arguments)
            structured = getattr(result, "structured_content", None)
            if structured is None:
                blocks = getattr(result, "content", [])
                structured = {"content": [item.model_dump(mode="json") for item in blocks]}
                if len(blocks) == 1 and getattr(blocks[0], "type", None) == "text":
                    try:
                        decoded = json.loads(blocks[0].text)
                        if isinstance(decoded, dict):
                            structured = decoded
                    except (ValueError, TypeError):
                        pass
            if getattr(result, "is_error", False):
                structured = {"error": "mcp_tool_error", "details": structured}
            if len(json.dumps(structured, default=str)) > 128000:
                return {"error": "result_too_large", "message": "Use this tool's pagination or projection options to request a smaller result."}
            return {"tool": tool_name, "result": structured, "observed_at": datetime.now(UTC).isoformat()}
        except AssistantError:
            raise
        except Exception:
            raise AssistantError("mcp_operation_failed", "The MCP operation could not complete. Inspect its existing operation status before retrying a change.", 503) from None
        finally:
            auth_context_var.reset(context)
            async with AsyncSessionFactory() as session:
                await session.execute(delete(MCPTokenModel).where(MCPTokenModel.token_hash == digest))
                await session.commit()

    async def dispatch(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "list_mcp_tools":
            return await self.discover(**arguments)
        if name == "call_mcp_tool":
            return await self.call(**arguments)
        raise AssistantError("query_rejected", "Discover an available MCP tool first.", 422)
