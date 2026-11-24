"""Versioned GC itinerary preview, draft and publication routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.sync_journal import append_mobile_sync_change
from app.application.use_cases.gc_app.create_itinerary import create_itinerary_version
from app.domain.entities.entities import User
from app.infrastructure.database.gc_mobile_models import (
    GCItineraryVersionModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.gc_app_content_lookup import (
    _get_itinerary,
    _latest_itinerary,
)
from app.presentation.api.v1.routes.gc_app_content_projection import (
    _itinerary_response,
)
from app.presentation.api.v1.routes.gc_app_content_scope import (
    GC_CONTENT_ROLES,
    _admin_access_context,
    _content_audit,
    _json_checksum,
    _require_access_revision,
    _require_publishable_group,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ItineraryDraftRequest,
    ItineraryVersionResponse,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.get(
    "/groups/{group_id}/itineraries/preview",
    response_model=ItineraryVersionResponse,
)
async def preview_itinerary(
    group_id: uuid.UUID,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> ItineraryVersionResponse:
    access, _group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=False
    )
    itinerary = await _latest_itinerary(session, access, prefer_draft=True)
    if itinerary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary not found")
    return await _itinerary_response(session, itinerary)


@router.post(
    "/groups/{group_id}/itineraries/drafts",
    response_model=ItineraryVersionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_cookie_csrf)],
)
async def create_itinerary_draft(
    group_id: uuid.UUID,
    body: ItineraryDraftRequest,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> ItineraryVersionResponse:
    access, group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=True
    )
    _require_publishable_group(group)
    _require_access_revision(access, body.expected_access_revision)
    itinerary = await create_itinerary_version(
        session,
        access=access,
        group_id=group_id,
        actor_id=current_user.id,
        body=body,
        checksum=_json_checksum(body.model_dump(mode="json", by_alias=True)),
    )
    await _content_audit(
        session,
        request,
        current_user,
        access,
        action="gc_app.itinerary_draft_created",
        entity_type="gc_itinerary_version",
        entity_id=itinerary.id,
    )
    return await _itinerary_response(session, itinerary)


@router.post(
    "/groups/{group_id}/itineraries/{version_id}/publish",
    response_model=ItineraryVersionResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def publish_itinerary(
    group_id: uuid.UUID,
    version_id: uuid.UUID,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> ItineraryVersionResponse:
    access, group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=True
    )
    _require_publishable_group(group)
    itinerary = await _get_itinerary(session, access, version_id, lock=True)
    if itinerary.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Only a draft itinerary can be published"
        )
    now = datetime.now(tz=UTC)
    previous = list(
        (
            await session.execute(
                select(GCItineraryVersionModel)
                .where(
                    GCItineraryVersionModel.gc_group_access_id == access.id,
                    GCItineraryVersionModel.status == "published",
                    GCItineraryVersionModel.id != itinerary.id,
                )
                .with_for_update()
            )
        ).scalars()
    )
    for item in previous:
        item.status = "retired"
        item.updated_at = now
    # Release the partial unique "published" slot before promoting the draft;
    # SQLAlchemy may otherwise order the new row's UPDATE before the old one.
    await session.flush()
    itinerary.status = "published"
    itinerary.published_at = now
    itinerary.published_by_user_id = current_user.id
    itinerary.updated_at = now
    access.itinerary_version += 1
    access.manifest_version += 1
    access.revision += 1
    access.updated_by_user_id = current_user.id
    access.updated_at = now
    await append_mobile_sync_change(
        session,
        access=access,
        entity_type="itinerary",
        entity_id=itinerary.id,
        operation="upsert",
        version=access.itinerary_version,
        changed_by_user_id=current_user.id,
        payload={
            "resource_path": f"/api/v1/mobile/trips/{group_id}/itinerary",
            "itinerary_version_id": str(itinerary.id),
        },
    )
    await _content_audit(
        session,
        request,
        current_user,
        access,
        action="gc_app.itinerary_published",
        entity_type="gc_itinerary_version",
        entity_id=itinerary.id,
    )
    return await _itinerary_response(session, itinerary)


@router.post(
    "/groups/{group_id}/itineraries/{version_id}/unpublish",
    response_model=ItineraryVersionResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def unpublish_itinerary(
    group_id: uuid.UUID,
    version_id: uuid.UUID,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> ItineraryVersionResponse:
    access, _group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=True
    )
    itinerary = await _get_itinerary(session, access, version_id, lock=True)
    if itinerary.status != "published":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Itinerary is not published"
        )
    now = datetime.now(tz=UTC)
    itinerary.status = "retired"
    itinerary.updated_at = now
    access.itinerary_version += 1
    access.manifest_version += 1
    access.revision += 1
    access.updated_by_user_id = current_user.id
    access.updated_at = now
    await append_mobile_sync_change(
        session,
        access=access,
        entity_type="itinerary",
        entity_id=itinerary.id,
        operation="delete",
        version=access.itinerary_version,
        changed_by_user_id=current_user.id,
        payload={"resource_path": f"/api/v1/mobile/trips/{group_id}/itinerary"},
    )
    await _content_audit(
        session,
        request,
        current_user,
        access,
        action="gc_app.itinerary_unpublished",
        entity_type="gc_itinerary_version",
        entity_id=itinerary.id,
    )
    return await _itinerary_response(session, itinerary)
