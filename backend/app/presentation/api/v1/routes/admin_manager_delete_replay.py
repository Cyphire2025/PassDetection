"""Exact committed manager-deletion receipt recovery."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    AuditLogModel,
)
from app.presentation.api.v1.schemas.operations_schemas import (
    DeleteManagerResponse,
)


@dataclass(frozen=True, slots=True)
class _PreviousManagerDelete:
    response: DeleteManagerResponse
    agency_id: uuid.UUID | None


async def _previous_manager_delete_result(
    session: AsyncSession,
    *,
    manager_id: uuid.UUID,
    delete_owned_data: bool,
) -> _PreviousManagerDelete | None:
    """Return an exact committed manager-deletion replay, if one exists."""

    result = await session.execute(
        select(AuditLogModel)
        .where(
            AuditLogModel.action == "manager_deleted",
            AuditLogModel.entity_type == "user",
            AuditLogModel.entity_id == str(manager_id),
            AuditLogModel.metadata_json["delete_owned_data"].as_boolean() == delete_owned_data,
        )
        .order_by(AuditLogModel.created_at.desc(), AuditLogModel.id.desc())
        .limit(1)
    )
    audit = result.scalar_one_or_none()
    if audit is None:
        return None
    metadata = audit.metadata_json or {}
    try:
        response = DeleteManagerResponse.model_validate(metadata)
    except ValueError:
        return None
    if response.deleted_manager_id != manager_id:
        return None
    # Immediate cleanup counts are not authoritative on a later replay. The
    # committed tombstones remain the durable source of truth for object work.
    response.deleted_storage_objects = 0
    return _PreviousManagerDelete(response=response, agency_id=audit.agency_id)
