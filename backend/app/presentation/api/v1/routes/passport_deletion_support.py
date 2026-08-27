"""Read-only replay support for idempotent passport deletion routes."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import AuditLogModel
from app.presentation.api.v1.schemas.passport_schemas import (
    BulkDeletePassportSubmissionsResponse,
)


async def previous_bulk_delete_result(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    request_fingerprint: str,
    requested_submission_ids: list[uuid.UUID],
) -> BulkDeletePassportSubmissionsResponse | None:
    """Resolve an exact committed retry without reconstructing deleted PII."""

    result = await session.execute(
        select(AuditLogModel)
        .where(
            AuditLogModel.action == "passport_submissions_bulk_deleted",
            AuditLogModel.entity_type == "client_group",
            AuditLogModel.entity_id == str(group_id),
            AuditLogModel.metadata_json["request_fingerprint"].as_string() == request_fingerprint,
        )
        .order_by(AuditLogModel.created_at.desc(), AuditLogModel.id.desc())
        .limit(1)
    )
    audit_row = result.scalar_one_or_none()
    if audit_row is None:
        return None
    metadata = audit_row.metadata_json or {}
    deleted_count = metadata.get("deleted_count")
    deleted_notifications = metadata.get("deleted_notifications")
    if not isinstance(deleted_count, int) or not isinstance(
        deleted_notifications,
        int,
    ):
        return None
    return BulkDeletePassportSubmissionsResponse(
        deleted_count=deleted_count,
        deleted_submission_ids=requested_submission_ids,
        deleted_storage_objects=0,
        deleted_notifications=deleted_notifications,
        # Cleanup completion is decoupled from the request. A replay reports
        # the conservative durable state until the cleanup worker completes.
        storage_cleanup_deferred=True,
    )
