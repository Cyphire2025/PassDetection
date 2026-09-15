"""Agency-scoped explicit phone alert drafting, audience review and batch history."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.authored_notification_history import (
    batch_responses,
    cursor_filter,
    page_cursor,
)
from app.application.mobile.authored_notification_service import (
    batch_by_request,
    draft_response,
    preview_notification,
    require_draft,
    save_notification_draft,
    send_notification,
)
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.gc_notification_models import (
    GCNotificationBatchModel,
    GCNotificationDraftModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.schemas.gc_notification_schemas import (
    NotificationBatchPage,
    NotificationBatchResponse,
    NotificationDraftInput,
    NotificationDraftPage,
    NotificationDraftResponse,
    NotificationDraftUpdate,
    NotificationPreviewRequest,
    NotificationPreviewResponse,
    NotificationSendRequest,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter(prefix="/notifications")
_ROLES = [UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER]


def _agency(user: User, requested: uuid.UUID | None) -> uuid.UUID:
    if user.role == UserRole.SUPER_ADMIN:
        if requested is None:
            raise HTTPException(422, "agency_id is required")
        return requested
    if user.agency_id is None or (requested is not None and requested != user.agency_id):
        raise HTTPException(403, "Agency scope mismatch")
    return user.agency_id


@router.get("", response_model=NotificationDraftPage)
async def list_drafts(
    agency_id: uuid.UUID | None = None,
    cursor: str | None = Query(None, max_length=256),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_role(_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> NotificationDraftPage:
    statement = select(GCNotificationDraftModel).where(
        GCNotificationDraftModel.agency_id == _agency(current_user, agency_id)
    )
    if cursor:
        statement = statement.where(cursor_filter(GCNotificationDraftModel, cursor))
    rows = list(
        (
            await session.execute(
                statement.order_by(
                    GCNotificationDraftModel.created_at.desc(), GCNotificationDraftModel.id.desc()
                ).limit(limit + 1)
            )
        ).scalars()
    )
    return NotificationDraftPage(
        items=[draft_response(row) for row in rows[:limit]],
        next_cursor=page_cursor(rows[limit - 1]) if len(rows) > limit else None,
    )


@router.get("/batches", response_model=NotificationBatchPage)
async def list_batches(
    agency_id: uuid.UUID | None = None,
    cursor: str | None = Query(None, max_length=256),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_role(_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> NotificationBatchPage:
    statement = select(GCNotificationBatchModel).where(
        GCNotificationBatchModel.agency_id == _agency(current_user, agency_id)
    )
    if cursor:
        statement = statement.where(cursor_filter(GCNotificationBatchModel, cursor))
    rows = list(
        (
            await session.execute(
                statement.order_by(
                    GCNotificationBatchModel.created_at.desc(), GCNotificationBatchModel.id.desc()
                ).limit(limit + 1)
            )
        ).scalars()
    )
    return NotificationBatchPage(
        items=await batch_responses(session, rows[:limit]),
        next_cursor=page_cursor(rows[limit - 1]) if len(rows) > limit else None,
    )


@router.get("/batches/by-request/{request_id}", response_model=NotificationBatchResponse)
async def get_batch_by_request(
    request_id: uuid.UUID,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> NotificationBatchResponse:
    batch = await batch_by_request(session, _agency(current_user, agency_id), request_id)
    if batch is None:
        raise HTTPException(404, "Notification batch not found")
    return (await batch_responses(session, [batch]))[0]


@router.get("/batches/{batch_id}", response_model=NotificationBatchResponse)
async def get_batch(
    batch_id: uuid.UUID,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> NotificationBatchResponse:
    batch = (
        await session.execute(
            select(GCNotificationBatchModel).where(
                GCNotificationBatchModel.id == batch_id,
                GCNotificationBatchModel.agency_id == _agency(current_user, agency_id),
            )
        )
    ).scalar_one_or_none()
    if batch is None:
        raise HTTPException(404, "Notification batch not found")
    return (await batch_responses(session, [batch]))[0]


@router.get("/{draft_id}", response_model=NotificationDraftResponse)
async def get_draft(
    draft_id: uuid.UUID,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> NotificationDraftResponse:
    return draft_response(
        await require_draft(session, agency_id=_agency(current_user, agency_id), draft_id=draft_id)
    )


@router.post(
    "",
    response_model=NotificationDraftResponse,
    status_code=201,
    dependencies=[Depends(require_cookie_csrf)],
)
async def create_draft(
    body: NotificationDraftInput,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> NotificationDraftResponse:
    return draft_response(
        await save_notification_draft(
            session, agency_id=_agency(current_user, agency_id), actor_id=current_user.id, body=body
        )
    )


@router.patch(
    "/{draft_id}",
    response_model=NotificationDraftResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def update_draft(
    draft_id: uuid.UUID,
    body: NotificationDraftUpdate,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> NotificationDraftResponse:
    return draft_response(
        await save_notification_draft(
            session,
            agency_id=_agency(current_user, agency_id),
            actor_id=current_user.id,
            body=body,
            draft_id=draft_id,
        )
    )


@router.post(
    "/{draft_id}/preview",
    response_model=NotificationPreviewResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def review_draft(
    draft_id: uuid.UUID,
    body: NotificationPreviewRequest,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> NotificationPreviewResponse:
    return await preview_notification(
        session,
        agency_id=_agency(current_user, agency_id),
        actor_id=current_user.id,
        draft_id=draft_id,
        revision=body.expected_revision,
    )


@router.post(
    "/{draft_id}/send",
    response_model=NotificationBatchResponse,
    status_code=202,
    dependencies=[Depends(require_cookie_csrf)],
)
async def send_draft(
    draft_id: uuid.UUID,
    body: NotificationSendRequest,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> NotificationBatchResponse:
    batch = await send_notification(
        session,
        agency_id=_agency(current_user, agency_id),
        actor_id=current_user.id,
        draft_id=draft_id,
        body=body,
    )
    response = (await batch_responses(session, [batch]))[0]
    # A 202 acknowledges a durable batch. Do not defer this commit until a
    # yield-dependency teardown that may happen after the HTTP response starts.
    await session.commit()
    return response
