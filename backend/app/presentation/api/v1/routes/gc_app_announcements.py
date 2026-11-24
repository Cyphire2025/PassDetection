"""GC announcement directory, drafts and delivery-status routes."""

from __future__ import annotations

import uuid
from dataclasses import asdict

from fastapi import (
    APIRouter,
    Depends,
    Query,
    Request,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.announcement_notification_status import announcement_notification_status
from app.application.use_cases.gc_app.create_announcement import (
    AnnouncementContent,
    create_announcement_version,
)
from app.core.config.settings import get_settings
from app.domain.entities.entities import User
from app.infrastructure.database.gc_mobile_models import (
    GCAnnouncementModel,
    GCGroupAccessModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.gc_app_announcement_publication import (
    publish_announcement,
)
from app.presentation.api.v1.routes.gc_app_content_lookup import (
    _get_announcement,
)
from app.presentation.api.v1.routes.gc_app_content_projection import (
    _announcement_response,
)
from app.presentation.api.v1.routes.gc_app_content_scope import (
    GC_CONTENT_ROLES,
    _admin_access_context,
    _content_audit,
    _require_access_revision,
    _require_publishable_group,
    _validate_window,
)
from app.presentation.api.v1.schemas.announcement_notification_status import (
    AnnouncementNotificationStatusResponse,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    AnnouncementCreateRequest,
    AnnouncementPageResponse,
    AnnouncementResponse,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.get(
    "/groups/{group_id}/announcements",
    response_model=list[AnnouncementResponse],
)
async def list_announcements(
    group_id: uuid.UUID,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[AnnouncementResponse]:
    access, _group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=False
    )
    items = list(
        (
            await session.execute(
                select(GCAnnouncementModel)
                .where(
                    GCAnnouncementModel.gc_group_access_id == access.id,
                    GCAnnouncementModel.status.in_(("draft", "published")),
                )
                .order_by(GCAnnouncementModel.created_at.desc())
                .limit(200)
            )
        ).scalars()
    )
    return [_announcement_response(item) for item in items]


@router.get("/groups/{group_id}/announcements/page", response_model=AnnouncementPageResponse)
async def page_announcements(
    group_id: uuid.UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> AnnouncementPageResponse:
    access, _group = await _admin_access_context(
        session,
        current_user,
        group_id,
        agency_id=agency_id,
        lock=False,
    )
    filters = (
        GCAnnouncementModel.gc_group_access_id == access.id,
        GCAnnouncementModel.agency_id == access.agency_id,
        GCAnnouncementModel.group_id == access.group_id,
        GCAnnouncementModel.status.in_(("draft", "published")),
    )
    total = int(
        (
            await session.execute(
                select(func.count()).select_from(GCAnnouncementModel).where(*filters),
            )
        ).scalar_one()
    )
    rows = (
        await session.execute(
            select(GCAnnouncementModel)
            .where(*filters)
            .order_by(GCAnnouncementModel.created_at.desc(), GCAnnouncementModel.id.desc())
            .offset(offset)
            .limit(limit),
        )
    ).scalars()
    return AnnouncementPageResponse(
        items=[_announcement_response(row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/groups/{group_id}/announcements/{announcement_id}/notification-status",
    response_model=AnnouncementNotificationStatusResponse,
)
async def get_announcement_notification_status(
    group_id: uuid.UUID,
    announcement_id: uuid.UUID,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> AnnouncementNotificationStatusResponse:
    access, _group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=False
    )
    await _get_announcement(session, access, announcement_id, lock=False)
    settings = get_settings().mobile
    summary = await announcement_notification_status(
        session,
        agency_id=access.agency_id,
        group_id=group_id,
        access_id=access.id,
        announcement_id=announcement_id,
        provider_enabled=settings.enabled and settings.push_provider != "disabled",
    )
    return AnnouncementNotificationStatusResponse.model_validate(asdict(summary))


@router.post(
    "/groups/{group_id}/announcements",
    response_model=AnnouncementResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_cookie_csrf)],
)
async def create_announcement(
    group_id: uuid.UUID,
    body: AnnouncementCreateRequest,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> AnnouncementResponse:
    access, group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=True
    )
    _require_publishable_group(group)
    _require_access_revision(access, body.expected_access_revision)
    return await _create_announcement_version(
        session,
        request=request,
        current_user=current_user,
        access=access,
        body=body,
        logical_id=uuid.uuid4(),
        version=1,
    )


@router.put(
    "/groups/{group_id}/announcements/{announcement_id}",
    response_model=AnnouncementResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_cookie_csrf)],
)
async def update_announcement(
    group_id: uuid.UUID,
    announcement_id: uuid.UUID,
    body: AnnouncementCreateRequest,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> AnnouncementResponse:
    access, group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=True
    )
    _require_publishable_group(group)
    _require_access_revision(access, body.expected_access_revision)
    previous = await _get_announcement(session, access, announcement_id, lock=True)
    existing_drafts = list(
        (
            await session.execute(
                select(GCAnnouncementModel)
                .where(
                    GCAnnouncementModel.gc_group_access_id == access.id,
                    GCAnnouncementModel.logical_announcement_id == previous.logical_announcement_id,
                    GCAnnouncementModel.status == "draft",
                )
                .with_for_update()
            )
        ).scalars()
    )
    for draft in existing_drafts:
        await session.delete(draft)
    max_version = int(
        (
            await session.execute(
                select(func.max(GCAnnouncementModel.version)).where(
                    GCAnnouncementModel.gc_group_access_id == access.id,
                    GCAnnouncementModel.logical_announcement_id == previous.logical_announcement_id,
                )
            )
        ).scalar_one()
        or previous.version
    )
    return await _create_announcement_version(
        session,
        request=request,
        current_user=current_user,
        access=access,
        body=body,
        logical_id=previous.logical_announcement_id,
        version=max_version + 1,
    )


async def _create_announcement_version(
    session: AsyncSession,
    *,
    request: Request,
    current_user: User,
    access: GCGroupAccessModel,
    body: AnnouncementCreateRequest,
    logical_id: uuid.UUID,
    version: int,
) -> AnnouncementResponse:
    _validate_window(body.available_from, body.available_until)
    announcement = await create_announcement_version(
        session,
        access=access,
        actor_id=current_user.id,
        content=AnnouncementContent(
            body.title, body.message, body.priority, body.available_from, body.available_until
        ),
        logical_id=logical_id,
        version=version,
    )
    await _content_audit(
        session,
        request,
        current_user,
        access,
        action="gc_app.announcement_draft_created",
        entity_type="gc_announcement",
        entity_id=announcement.id,
    )
    if body.publish:
        # Saving and publishing share the request transaction. A failed queue,
        # audit or publication write must not leave an invisible saved draft
        # that the operator accidentally duplicates by retrying the form.
        return await publish_announcement(
            group_id=access.group_id,
            announcement_id=announcement.id,
            request=request,
            agency_id=access.agency_id,
            current_user=current_user,
            session=session,
        )
    return _announcement_response(announcement)
