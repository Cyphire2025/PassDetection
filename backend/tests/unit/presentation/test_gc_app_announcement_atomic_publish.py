"""Saving and publishing are one revision-guarded database transaction."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from starlette.requests import Request

from app.infrastructure.database.gc_mobile_models import (
    GCAnnouncementModel,
    GCGroupAccessModel,
    MobileSyncChangeModel,
)
from app.presentation.api.v1.routes.gc_app_content import (
    create_announcement,
    page_announcements,
    update_announcement,
)
from app.presentation.api.v1.schemas.gc_app_schemas import AnnouncementCreateRequest
from tests.gc_app_workflow_fixtures import workflow_group


def request():
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []})


def body(revision, *, publish=True):
    return AnnouncementCreateRequest(
        title="Synthetic announcement", message="Synthetic message", publish=publish,
        expected_access_revision=revision,
    )


@pytest.mark.asyncio
async def test_save_publish_and_edit_publish_keep_single_current_version(db_session):
    actor, group, access = await workflow_group(db_session)
    result = await create_announcement(group.id, body(access.revision), request(), None, actor, db_session)
    assert result.status == "published"
    await db_session.commit()
    updated = await update_announcement(group.id, result.id, body(access.revision), request(), None, actor, db_session)
    await db_session.commit()
    assert updated.status == "published" and updated.version == 2
    records = list(await db_session.scalars(select(GCAnnouncementModel).order_by(GCAnnouncementModel.version)))
    assert [record.status for record in records] == ["retired", "published"]
    assert access.announcement_version == 2
    assert await db_session.scalar(select(func.count()).select_from(MobileSyncChangeModel)) == 2


@pytest.mark.asyncio
async def test_failed_publication_rolls_back_draft_and_revision_so_safe_retry_creates_once(db_session):
    actor, group, access = await workflow_group(db_session)
    await db_session.commit()
    group_id, access_id, revision = group.id, access.id, access.revision
    with patch("app.presentation.api.v1.routes.gc_app_content.enqueue_announcement_notifications", new=AsyncMock(side_effect=RuntimeError("synthetic queue write failure"))):
        with pytest.raises(RuntimeError):
            async with db_session.begin():
                await create_announcement(group_id, body(revision), request(), None, actor, db_session)
    assert await db_session.scalar(select(func.count()).select_from(GCAnnouncementModel)) == 0
    restored = await db_session.get(GCGroupAccessModel, access_id)
    assert restored.revision == revision
    result = await create_announcement(group_id, body(revision), request(), None, actor, db_session)
    await db_session.commit()
    assert result.status == "published"
    assert await db_session.scalar(select(func.count()).select_from(GCAnnouncementModel)) == 1
    with pytest.raises(HTTPException) as stale:
        await create_announcement(group_id, body(revision), request(), None, actor, db_session)
    assert stale.value.status_code == 409


@pytest.mark.asyncio
async def test_legacy_draft_request_remains_hidden_until_explicit_publish(db_session):
    actor, group, access = await workflow_group(db_session)
    result = await create_announcement(group.id, body(access.revision, publish=False), request(), None, actor, db_session)
    assert result.status == "draft"
    assert access.announcement_version == 0
    assert await db_session.scalar(select(func.count()).select_from(MobileSyncChangeModel)) == 0


@pytest.mark.asyncio
async def test_announcement_paging_reaches_records_beyond_legacy_limit_with_stable_order(db_session):
    actor, group, access = await workflow_group(db_session)
    records = [GCAnnouncementModel(
        agency_id=access.agency_id, group_id=group.id, gc_group_access_id=access.id,
        category="general", priority="normal", title=f"Synthetic {index}", body="Test",
        version=1, status="draft",
    ) for index in range(205)]
    db_session.add_all(records)
    await db_session.commit()
    first = await page_announcements(group.id, 0, 100, None, actor, db_session)
    second = await page_announcements(group.id, 100, 100, None, actor, db_session)
    last = await page_announcements(group.id, 200, 100, None, actor, db_session)
    assert first.total == second.total == last.total == 205
    assert len(first.items) == len(second.items) == 100
    assert len(last.items) == 5
    assert len({item.id for item in [*first.items, *second.items, *last.items]}) == 205
