"""Closed, privacy-safe durable audit adapter for My Photos."""

from __future__ import annotations

import re
import uuid
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories.audit_log_repository import AuditLogRepository

AuditAction = Literal[
    "my_photos_consent_accepted",
    "my_photos_enrollment_completed",
    "my_photos_enrollment_deleted",
    "my_photos_provider_deletion",
    "my_photos_search_finished",
    "my_photos_match_feedback",
    "my_photos_rehydration_requested",
    "my_photos_download_authorized",
    "my_photos_job_cancelled",
]
_STABLE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


async def record_my_photos_audit(
    session: AsyncSession,
    *,
    action: AuditAction,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    outcome: str,
    gallery_revision: int | None = None,
    configuration_version: str | None = None,
) -> None:
    """Record only closed operational context; never biometric/media locators."""

    if not _STABLE.fullmatch(outcome):
        raise ValueError("My Photos audit outcome must be a stable category")
    metadata: dict[str, str | int] = {
        "group_id": str(group_id),
        "outcome": outcome,
    }
    if gallery_revision is not None:
        metadata["gallery_revision"] = gallery_revision
    if configuration_version is not None:
        if not _STABLE.fullmatch(configuration_version):
            raise ValueError("My Photos audit configuration version is invalid")
        metadata["configuration_version"] = configuration_version
    await AuditLogRepository(session).record(
        action=action,
        entity_type="my_photos",
        agency_id=agency_id,
        metadata=metadata,
    )


__all__ = ["record_my_photos_audit"]
