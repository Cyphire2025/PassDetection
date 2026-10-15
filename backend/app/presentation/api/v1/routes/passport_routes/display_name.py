"""Scoped edits of the existing operational label, preserving passport identity."""

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
from app.presentation.api.v1.schemas.passport_display_name_schemas import (
    PassportDisplayNameResponse,
    UpdatePassportDisplayNameRequest,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

from .bulk_actions import _lock_active_bulk_approval_actor

router = APIRouter()
_ALLOWED_ROLES = {
    UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER, UserRole.AGENCY_STAFF,
}


@router.patch(
    "/groups/{group_id}/submissions/{submission_id}/display-name",
    response_model=PassportDisplayNameResponse,
    summary="Edit a passenger's display name without changing passport details",
)
async def update_passport_display_name(
    group_id: uuid.UUID,
    submission_id: uuid.UUID,
    body: UpdatePassportDisplayNameRequest,
    response: Response,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportDisplayNameResponse:
    if current_user.role not in _ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    actor = await _lock_active_bulk_approval_actor(session, current_user)
    if actor.role not in _ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
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

    # Only this presentation override changes. The original client_name remains
    # authoritative for WhatsApp identity matching, including active sends.
    statement = AuthorizationPolicy.apply_passport_visibility_scope(
        select(PassportSubmissionModel).where(
            PassportSubmissionModel.id == submission_id,
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.agency_id == group.agency_id,
            PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
        ), actor,
    ).with_for_update(of=PassportSubmissionModel).execution_options(populate_existing=True)
    model = (await session.execute(statement)).scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail="Passenger was not found in this group")
    current_updated_at = model.updated_at
    if current_updated_at.tzinfo is None:
        current_updated_at = current_updated_at.replace(tzinfo=UTC)
    if current_updated_at != body.expected_updated_at:
        raise HTTPException(status_code=409, detail=(
            "This passenger changed while you were editing. Reload the latest name and try again."
        ))

    try:
        display_name = None if body.display_name == model.client_name else body.display_name
        if model.display_name != display_name:
            now = datetime.now(UTC)
            model.display_name = display_name
            model.updated_at = now
            session.add(AuditLogModel(
                id=uuid.uuid4(), agency_id=group.agency_id, user_id=actor.id,
                actor_email=actor.email, action="passport_display_name_changed",
                entity_type="passport_submission", entity_id=str(model.id), created_at=now,
                metadata_json={"group_id": str(group.id), "changed_fields": ["display_name"]},
            ))
        # Existing roster revision triggers refresh names, search and sorting.
        # Assignments reference the unchanged passenger ID, not this label.
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    response.headers["Cache-Control"] = "no-store"
    updated_at = model.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return PassportDisplayNameResponse(
        id=model.id, client_name=model.client_name, display_name=model.display_name, updated_at=updated_at,
    )
