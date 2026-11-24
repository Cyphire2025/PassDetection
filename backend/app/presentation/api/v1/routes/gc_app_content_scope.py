"""GC content authorization, revision guards, status and audit boundaries."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Literal

from fastapi import (
    HTTPException,
    Request,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging.logger import get_logger
from app.domain.entities.entities import GroupStatus, User, UserRole
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
)
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.security.client_ip import trusted_client_ip

GC_CONTENT_ROLES = [UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER]


logger = get_logger("app.presentation.api.v1.routes.gc_app_content")


async def _admin_access_context(
    session: AsyncSession,
    current_user: User,
    group_id: uuid.UUID,
    *,
    agency_id: uuid.UUID | None,
    lock: bool,
) -> tuple[GCGroupAccessModel, ClientGroupModel]:
    if current_user.role == UserRole.SUPER_ADMIN:
        if agency_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="agency_id is required for super-admin GC App operations",
            )
        tenant_id = agency_id
    else:
        if current_user.agency_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account has no agency",
            )
        if agency_id is not None and agency_id != current_user.agency_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Agency scope mismatch",
            )
        tenant_id = current_user.agency_id
    if lock:
        # Explicit group -> access order matches source/dispatch transactions;
        # a joined FOR UPDATE leaves acquisition order to the query plan.
        group = await session.scalar(
            select(ClientGroupModel)
            .where(
                ClientGroupModel.id == group_id,
                ClientGroupModel.agency_id == tenant_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        access = (
            await session.scalar(
                select(GCGroupAccessModel)
                .where(
                    GCGroupAccessModel.group_id == group_id,
                    GCGroupAccessModel.agency_id == tenant_id,
                    GCGroupAccessModel.removed_at.is_(None),
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if group is not None
            else None
        )
        if access is None or group is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="GC App group not found"
            )
        return access, group
    stmt = (
        select(GCGroupAccessModel, ClientGroupModel)
        .join(ClientGroupModel, ClientGroupModel.id == GCGroupAccessModel.group_id)
        .where(
            GCGroupAccessModel.group_id == group_id,
            GCGroupAccessModel.agency_id == tenant_id,
            GCGroupAccessModel.agency_id == ClientGroupModel.agency_id,
        )
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GC App group not found")
    access, group = row
    return access, group


def _require_access_revision(access: GCGroupAccessModel, expected: int) -> None:
    if access.revision != expected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="GC App content changed; refresh and retry"
        )


def _require_publishable_group(group: ClientGroupModel) -> None:
    if group.status not in {GroupStatus.ACTIVE.value, GroupStatus.CLOSED.value}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Archived or deleted groups cannot publish mobile content",
        )


async def _content_audit(
    session: AsyncSession,
    request: Request,
    actor: User,
    access: GCGroupAccessModel,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
) -> None:
    await AuditLogRepository(session).record(
        action=action,
        entity_type=entity_type,
        agency_id=access.agency_id,
        user_id=actor.id,
        actor_email=actor.email,
        entity_id=str(entity_id),
        ip_address=trusted_client_ip(request),
        metadata={"group_id": str(access.group_id)},
    )


def _validate_window(starts_at: datetime | None, expires_at: datetime | None) -> None:
    if starts_at is not None and expires_at is not None and expires_at <= starts_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Availability expiry must be after its start",
        )


def _json_checksum(value: dict[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _itinerary_status(value: str) -> Literal["draft", "published", "retired"]:
    if value == "draft":
        return "draft"
    if value == "published":
        return "published"
    if value == "retired":
        return "retired"
    raise ValueError("Unsupported itinerary status")


def _content_status(
    value: str,
) -> Literal["draft", "published", "retired", "revoked"]:
    if value == "draft":
        return "draft"
    if value == "published":
        return "published"
    if value == "retired":
        return "retired"
    if value == "revoked":
        return "revoked"
    raise ValueError("Unsupported GC content status")
