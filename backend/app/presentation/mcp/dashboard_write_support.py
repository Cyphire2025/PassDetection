"""Explicit website write adapters inside the MCP receipt transaction.

Only reviewed, database-only handlers are bound here. HTTP routing, arbitrary
paths and provider dispatch are never tool inputs. The business change, retained
before-image and operation receipt belong to the caller's atomic transaction.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from starlette.requests import Request

from app.application.mcp.change_context import require_change_actor
from app.application.mcp.credentials import utc
from app.application.mcp.operations import MCPDatabaseContext, MCPOperationError
from app.domain.entities.entities import User
from app.infrastructure.database.models import ClientGroupModel

MAX_RESULT_BYTES = 256 * 1024
PRIVATE_FIELDS = frozenset({
    "upload_token", "token", "password", "reset_token", "storage_key",
    "presigned_url", "source_url", "image_url", "document_url",
})


def safe_result(value: Any) -> Any:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: safe_result(item) for key, item in value.items() if key not in PRIVATE_FIELDS}
    if isinstance(value, (list, tuple)):
        return [safe_result(item) for item in value]
    if isinstance(value, datetime):
        return utc(value).isoformat()
    if isinstance(value, (UUID, date)):
        return str(value) if isinstance(value, UUID) else value.isoformat()
    return value


def audit_request() -> Request:
    # No invented browser/device address is attributed to an MCP operation.
    return Request({"type": "http", "method": "POST", "path": "/mcp",
                    "headers": [], "query_string": b"", "client": None,
                    "server": None, "scheme": "https"})


async def scoped_actor(context: MCPDatabaseContext, agency_id: UUID | None) -> User:
    actor = await require_change_actor(context, agency_id)
    # The current, authenticated superadmin selects a tenant explicitly. Identity,
    # role, security version and audit attribution remain the real actor's.
    return replace(actor, agency_id=agency_id)


def configuration_revision(row: Any) -> str:
    snapshot = safe_result({column.key: getattr(row, column.key)
                            for column in row.__table__.columns if column.key not in PRIVATE_FIELDS})
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


async def lock_group_revision(
    context: MCPDatabaseContext, agency_id: UUID, group_id: UUID,
    expected_revision: str,
) -> ClientGroupModel:
    row = await context.session.scalar(select(ClientGroupModel).where(
        ClientGroupModel.id == group_id, ClientGroupModel.agency_id == agency_id,
        ClientGroupModel.deleted_at.is_(None), ClientGroupModel.status != "deleted",
    ).with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise MCPOperationError("workflow_resource_unavailable")
    if configuration_revision(row) != expected_revision:
        raise MCPOperationError("workflow_revision_changed")
    return row


def public_failure(error: HTTPException) -> MCPOperationError:
    # Never relay canonical exceptions containing names, cells or provider text.
    code = {403: "workflow_access_denied", 404: "workflow_resource_unavailable",
            409: "workflow_revision_changed", 410: "workflow_retired",
            422: "workflow_invalid_configuration"}.get(error.status_code,
                                                       "workflow_unavailable")
    return MCPOperationError(code)
