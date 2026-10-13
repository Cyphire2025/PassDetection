"""Scoped operational review tasks and signed incremental reference feeds."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.access import (
    COMPANY_ADMIN_ROLES,
    require_company,
    visible_company_groups,
)
from app.application.mcp.read_cursor import MCPReadCursor
from app.application.travellers.change_feed import read_changes
from app.core.config.settings import Settings, get_settings
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import ConflictError, EntityNotFoundError
from app.infrastructure.database.session import get_db_session
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentReviewTaskModel,
    TravellerParticipationModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.routes.companies import _private_response
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter(dependencies=[Depends(_private_response)])


class ReviewTaskResponse(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    traveller_id: uuid.UUID
    source_submission_id: uuid.UUID | None
    old_document_revision_id: uuid.UUID
    new_document_revision_id: uuid.UUID | None
    status: Literal["pending", "resolved", "dismissed"]
    reason_code: str
    revision: int
    expected_participation_revision: int
    current_participation_revision: int
    created_at: datetime
    resolved_at: datetime | None
    resolution_reason: str | None


class ReviewTaskPage(BaseModel):
    items: list[ReviewTaskResponse]
    next_cursor: str | None
    has_more: bool


class ResolveReviewTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=1)
    expected_participation_revision: int = Field(ge=1)
    resolution: Literal["resolved", "dismissed"]
    reason: str = Field(min_length=10, max_length=500)


def _response(task: TravellerDocumentReviewTaskModel, participation: TravellerParticipationModel) -> ReviewTaskResponse:
    return ReviewTaskResponse.model_validate({
        **{key: getattr(task, key) for key in ("id", "old_document_revision_id", "new_document_revision_id", "status",
            "reason_code", "revision", "expected_participation_revision", "created_at", "resolved_at", "resolution_reason")},
        "group_id": participation.group_id, "traveller_id": participation.traveller_id,
        "source_submission_id": participation.source_submission_id, "current_participation_revision": participation.revision,
    })


@router.get("/{company_id}/review-tasks", response_model=ReviewTaskPage)
async def review_tasks(
    company_id: uuid.UUID, agency_id: uuid.UUID | None = None,
    status: Literal["pending", "resolved", "dismissed", "all"] = "pending",
    cursor: str | None = Query(default=None, max_length=2048), page_size: int = Query(default=30, ge=1, le=100),
    user: User = Depends(require_role(COMPANY_ADMIN_ROLES)), session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ReviewTaskPage:
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    codec = MCPReadCursor(settings.app_secret_key, "company-review-tasks-v1")
    try:
        state = codec.read(cursor, {"actor": str(user.id), "company": str(company.id), "agency": str(company.agency_id), "status": status})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    groups = visible_company_groups(user, company.agency_id, company.id).subquery()
    query = select(TravellerDocumentReviewTaskModel, TravellerParticipationModel).join(TravellerParticipationModel,
        TravellerParticipationModel.id == TravellerDocumentReviewTaskModel.participation_id,
    ).join(groups, groups.c.id == TravellerParticipationModel.group_id).where(
        TravellerDocumentReviewTaskModel.agency_id == company.agency_id,
        TravellerDocumentReviewTaskModel.company_id == company.id,
        TravellerDocumentReviewTaskModel.created_at <= datetime.fromisoformat(state["cutoff"]),
    )
    if status != "all":
        query = query.where(TravellerDocumentReviewTaskModel.status == status)
    after = codec.after(state)
    if after:
        query = query.where(or_(TravellerDocumentReviewTaskModel.created_at < after[0], and_(
            TravellerDocumentReviewTaskModel.created_at == after[0], TravellerDocumentReviewTaskModel.id < after[1])))
    rows = list((await session.execute(query.order_by(TravellerDocumentReviewTaskModel.created_at.desc(),
        TravellerDocumentReviewTaskModel.id.desc()).limit(page_size + 1))).all())
    has_more, rows = len(rows) > page_size, rows[:page_size]
    next_cursor = codec.next(state, {"id": rows[-1][0].id, "created_at": rows[-1][0].created_at}) if has_more else None
    return ReviewTaskPage(items=[_response(task, participation) for task, participation in rows], next_cursor=next_cursor, has_more=has_more)


@router.patch("/{company_id}/review-tasks/{task_id}", response_model=ReviewTaskResponse, dependencies=[Depends(require_cookie_csrf)])
async def resolve_review_task(
    company_id: uuid.UUID, task_id: uuid.UUID, body: ResolveReviewTaskRequest, agency_id: uuid.UUID | None = None,
    user: User = Depends(require_role(COMPANY_ADMIN_ROLES)), session: AsyncSession = Depends(get_db_session),
) -> ReviewTaskResponse:
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    groups = visible_company_groups(user, company.agency_id, company.id).subquery()
    result = (await session.execute(select(TravellerDocumentReviewTaskModel, TravellerParticipationModel)
        .join(TravellerParticipationModel, TravellerParticipationModel.id == TravellerDocumentReviewTaskModel.participation_id)
        .join(groups, groups.c.id == TravellerParticipationModel.group_id)
        .where(TravellerDocumentReviewTaskModel.id == task_id,
            TravellerDocumentReviewTaskModel.agency_id == company.agency_id,
            TravellerDocumentReviewTaskModel.company_id == company.id)
        .with_for_update(of=[TravellerParticipationModel.id, TravellerDocumentReviewTaskModel.id])
        .execution_options(populate_existing=True))).one_or_none()
    if result is None:
        raise EntityNotFoundError("Review task", task_id)
    task, participation = result
    if task.revision != body.expected_revision or participation.revision != body.expected_participation_revision or task.status != "pending":
        raise ConflictError("The task or trip changed; refresh and review again")
    task.status, task.resolution_reason = body.resolution, body.reason
    task.resolved_by_user_id, task.resolved_at = user.id, datetime.now(UTC)
    task.revision += 1
    await AuditLogRepository(session).record(action="traveller.review_task_resolved", entity_type="traveller_review_task",
        entity_id=str(task.id), agency_id=company.agency_id, user_id=user.id, actor_email=user.email,
        metadata={"resolution": task.status, "revision": task.revision, "participation_id": str(participation.id),
            "reason": task.resolution_reason})
    await session.flush()
    return _response(task, participation)


class ChangeReference(BaseModel):
    id: uuid.UUID
    sequence: int
    kind: Literal["added", "changed", "removed"]
    record_type: Literal["document", "profile", "participation"]
    record_id: uuid.UUID
    revision: int
    reason_code: str
    occurred_at: datetime


class ChangePage(BaseModel):
    items: list[ChangeReference]
    checkpoint: str
    has_more: bool


@router.get("/{company_id}/changes", response_model=ChangePage)
async def company_changes(
    company_id: uuid.UUID, agency_id: uuid.UUID | None = None,
    checkpoint: str | None = Query(default=None, max_length=2048), page_size: int = Query(default=100, ge=1, le=100),
    user: User = Depends(require_role(COMPANY_ADMIN_ROLES)), session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ChangePage:
    try:
        return ChangePage.model_validate(await read_changes(session, user=user, company_id=company_id,
            agency_id=agency_id, checkpoint=checkpoint, page_size=page_size, signing_secret=settings.app_secret_key))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
