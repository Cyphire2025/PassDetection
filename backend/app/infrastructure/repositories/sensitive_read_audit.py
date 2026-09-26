"""Privacy-minimal evidence of authorized access, never delivery receipts."""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository

ReadKind = Literal["detail", "client_details", "list", "group_list", "group_view", "search", "cover", "image"]


async def record_sensitive_read(
    session: AsyncSession, *, user: User, kind: ReadKind,
    agency_id: uuid.UUID | None, entity_id: uuid.UUID | None = None,
    count: int = 1,
) -> None:
    """Call only after authorization; omit search text and document attributes.

    This event describes an authorized handler access. It does not attest that
    an object was present or that a browser received or displayed any bytes.
    It participates in the request transaction and fails with that transaction.
    """
    await AuditLogRepository(session).record(
        action="sensitive_read.authorized", entity_type="passport_access",
        entity_id=str(entity_id) if entity_id is not None else None,
        agency_id=agency_id, user_id=user.id,
        metadata={"read_kind": kind, "authorized_result_count": count},
    )
