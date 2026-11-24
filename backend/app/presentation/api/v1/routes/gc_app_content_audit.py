"""Bounded tenant/group GC audit history route."""

from __future__ import annotations

import uuid

from fastapi import (
    APIRouter,
    Depends,
    Query,
)
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.models import AuditLogModel
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.gc_app_content_scope import (
    GC_CONTENT_ROLES,
    _admin_access_context,
)
from app.presentation.api.v1.routes.gc_app_history_support import gc_app_audit_responses
from app.presentation.api.v1.schemas.gc_app_schemas import (
    GCAppAuditPageResponse,
)
from app.presentation.dependencies.auth import require_role

router = APIRouter()


@router.get(
    "/groups/{group_id}/audit",
    response_model=GCAppAuditPageResponse,
)
async def list_group_gc_audit(
    group_id: uuid.UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> GCAppAuditPageResponse:
    access, _group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=False
    )
    filters = (
        AuditLogModel.agency_id == access.agency_id,
        AuditLogModel.action.like("gc_app.%"),
        or_(
            AuditLogModel.entity_id == str(access.id),
            AuditLogModel.metadata_json["group_id"].as_string() == str(group_id),
        ),
    )
    total = int(await session.scalar(select(func.count(AuditLogModel.id)).where(*filters)) or 0)
    logs = list(
        (
            await session.execute(
                select(AuditLogModel)
                .where(*filters)
                .order_by(AuditLogModel.created_at.desc(), AuditLogModel.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
    )
    return GCAppAuditPageResponse(
        items=gc_app_audit_responses(logs),
        total=total,
        offset=offset,
        limit=limit,
    )
