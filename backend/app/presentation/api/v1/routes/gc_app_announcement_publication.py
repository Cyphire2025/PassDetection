"""Atomic GC announcement publication and notification cancellation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.notification_service import (
    cancel_announcement_notifications,
    enqueue_announcement_notifications,
)
from app.application.mobile.sync_journal import append_mobile_sync_change
from app.domain.entities.entities import User
from app.infrastructure.database.gc_mobile_models import (
    GCAnnouncementModel,
)
from app.infrastructure.database.session import get_db_session
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
    _require_publishable_group,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    AnnouncementResponse,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.post(
    "/groups/{group_id}/announcements/{announcement_id}/publish",
    response_model=AnnouncementResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def publish_announcement(
    group_id: uuid.UUID,
    announcement_id: uuid.UUID,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> AnnouncementResponse:
    access, group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=True
    )
    _require_publishable_group(group)
    announcement = await _get_announcement(session, access, announcement_id, lock=True)
    if announcement.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a draft announcement can be published",
        )
    now = datetime.now(tz=UTC)
    previous = list(
        (
            await session.execute(
                select(GCAnnouncementModel)
                .where(
                    GCAnnouncementModel.gc_group_access_id == access.id,
                    GCAnnouncementModel.logical_announcement_id
                    == announcement.logical_announcement_id,
                    GCAnnouncementModel.status == "published",
                    GCAnnouncementModel.id != announcement.id,
                )
                .with_for_update()
            )
        ).scalars()
    )
    for item in previous:
        item.status = "retired"
        item.retired_at = now
        item.updated_at = now
    await session.flush()
    announcement.status = "published"
    announcement.passenger_visible = True
    announcement.client_manager_visible = True
    announcement.coordinator_visible = True
    announcement.published_at = now
    announcement.published_by_user_id = current_user.id
    announcement.updated_at = now
    access.announcement_version += 1
    access.manifest_version += 1
    access.revision += 1
    access.updated_by_user_id = current_user.id
    access.updated_at = now
    await append_mobile_sync_change(
        session,
        access=access,
        entity_type="announcement",
        entity_id=announcement.id,
        operation="upsert",
        version=access.announcement_version,
        changed_by_user_id=current_user.id,
        payload={
            "resource_path": f"/api/v1/mobile/trips/{group_id}/announcements/{announcement.id}"
        },
    )
    await enqueue_announcement_notifications(
        session,
        access=access,
        announcement=announcement,
        now=now,
    )
    await _content_audit(
        session,
        request,
        current_user,
        access,
        action="gc_app.announcement_published",
        entity_type="gc_announcement",
        entity_id=announcement.id,
    )
    return _announcement_response(announcement)


@router.post(
    "/groups/{group_id}/announcements/{announcement_id}/unpublish",
    response_model=AnnouncementResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def unpublish_announcement(
    group_id: uuid.UUID,
    announcement_id: uuid.UUID,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> AnnouncementResponse:
    access, _group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=True
    )
    announcement = await _get_announcement(session, access, announcement_id, lock=True)
    if announcement.status != "published":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Announcement is not published"
        )
    now = datetime.now(tz=UTC)
    announcement.status = "retired"
    announcement.retired_at = now
    announcement.updated_at = now
    access.announcement_version += 1
    access.manifest_version += 1
    access.revision += 1
    access.updated_by_user_id = current_user.id
    access.updated_at = now
    await append_mobile_sync_change(
        session,
        access=access,
        entity_type="announcement",
        entity_id=announcement.id,
        operation="delete",
        version=access.announcement_version,
        changed_by_user_id=current_user.id,
        payload={"resource_path": f"/api/v1/mobile/trips/{group_id}/announcements"},
    )
    await cancel_announcement_notifications(
        session,
        access=access,
        announcement_id=announcement.id,
        now=now,
    )
    await _content_audit(
        session,
        request,
        current_user,
        access,
        action="gc_app.announcement_unpublished",
        entity_type="gc_announcement",
        entity_id=announcement.id,
    )
    return _announcement_response(announcement)


@router.delete(
    "/groups/{group_id}/announcements/{announcement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(require_cookie_csrf)],
)
async def delete_announcement(
    group_id: uuid.UUID,
    announcement_id: uuid.UUID,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    access, _group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=True
    )
    announcement = await _get_announcement(session, access, announcement_id, lock=True)
    now = datetime.now(tz=UTC)
    if announcement.status == "draft":
        await session.delete(announcement)
        await session.flush()
    else:
        announcement.status = "revoked"
        announcement.revoked_at = now
        announcement.updated_at = now
        access.announcement_version += 1
        access.manifest_version += 1
        access.revision += 1
        access.updated_by_user_id = current_user.id
        access.updated_at = now
        await append_mobile_sync_change(
            session,
            access=access,
            entity_type="announcement",
            entity_id=announcement.id,
            operation="delete",
            version=access.announcement_version,
            changed_by_user_id=current_user.id,
            payload={"resource_path": f"/api/v1/mobile/trips/{group_id}/announcements"},
        )
        await cancel_announcement_notifications(
            session,
            access=access,
            announcement_id=announcement.id,
            now=now,
        )
    await _content_audit(
        session,
        request,
        current_user,
        access,
        action="gc_app.announcement_deleted",
        entity_type="gc_announcement",
        entity_id=announcement_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
