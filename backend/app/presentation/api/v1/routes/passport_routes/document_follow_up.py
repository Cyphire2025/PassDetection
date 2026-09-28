"""Office-only manual document follow-up flags, independent of verification."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES, User, UserRole
from app.infrastructure.database.models import (
    AuditLogModel,
    ClientGroupModel,
    PassportSubmissionModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.schemas.passport_schemas import (
    BulkDocumentFollowUpRequest,
    BulkDocumentFollowUpResponse,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

from .bulk_actions import _lock_active_bulk_approval_actor

router = APIRouter()
_ALLOWED_ROLES = {
    UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER, UserRole.AGENCY_STAFF,
}


@router.post(
    "/groups/{group_id}/bulk-document-follow-up",
    response_model=BulkDocumentFollowUpResponse,
    summary="Flag or clear selected passengers for document follow-up",
)
async def bulk_document_follow_up(
    group_id: uuid.UUID,
    body: BulkDocumentFollowUpRequest,
    response: Response,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> BulkDocumentFollowUpResponse:
    if current_user.role not in _ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    actor = await _lock_active_bulk_approval_actor(session, current_user)
    if actor.role not in _ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Serialize against group archival/deletion and assignment mutations before
    # checking current scope; all selected rows must remain in the same group.
    group_statement = AuthorizationPolicy.apply_group_visibility_scope(
        select(ClientGroupModel).where(
            ClientGroupModel.id == group_id,
            ClientGroupModel.deleted_at.is_(None),
            ClientGroupModel.status.notin_(["archived", "deleted"]),
        ), actor,
    ).with_for_update(of=ClientGroupModel).execution_options(populate_existing=True)
    group = (await session.execute(group_statement)).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="Client group was not found")

    requested_ids = list(dict.fromkeys(body.submission_ids))
    statement = AuthorizationPolicy.apply_passport_visibility_scope(
        select(PassportSubmissionModel).where(
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.agency_id == group.agency_id,
            PassportSubmissionModel.id.in_(requested_ids),
            PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
        ), actor,
    ).order_by(PassportSubmissionModel.id).with_for_update(
        of=PassportSubmissionModel,
    ).execution_options(populate_existing=True)
    models = list((await session.execute(statement)).scalars().all())
    if len(models) != len(requested_ids):
        raise HTTPException(status_code=404, detail=(
            "One or more selected passengers were not found in this group. Refresh and try again."
        ))

    now = datetime.now(UTC)
    changed = [model for model in models if bool(model.document_follow_up) != body.flagged]
    for model in changed:
        model.document_follow_up = body.flagged
        model.updated_at = now
    if changed:
        session.add(AuditLogModel(
            id=uuid.uuid4(), agency_id=group.agency_id, user_id=actor.id,
            actor_email=actor.email, action="passport_document_follow_up_changed",
            entity_type="client_group", entity_id=str(group_id), created_at=now,
            metadata_json={"flagged": body.flagged, "updated_count": len(changed),
                           "submission_ids": [str(model.id) for model in changed]},
        ))
    try:
        # Existing statement-level roster triggers invalidate cached filters and
        # counts in the same transaction. No extraction/approval fields change.
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    response.headers["Cache-Control"] = "no-store"
    return BulkDocumentFollowUpResponse(updated_count=len(changed), flagged=body.flagged)
