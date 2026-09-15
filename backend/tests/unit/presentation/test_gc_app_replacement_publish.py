"""Replacement publication must not depend on UUID update ordering."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from starlette.requests import Request

from app.infrastructure.database.gc_mobile_models import (
    GCAnnouncementModel,
    GCCommonDocumentModel,
    GCItineraryVersionModel,
)
from app.presentation.api.v1.routes.gc_app_content import (
    publish_announcement,
    publish_common_document,
    publish_itinerary,
)
from tests.gc_app_workflow_fixtures import workflow_group


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["announcement", "document", "itinerary"])
async def test_lower_uuid_replacement_retires_old_version_before_promotion(db_session, kind):
    actor, group, access = await workflow_group(db_session)
    logical_id = uuid.uuid4()
    now = datetime.now(UTC)
    model, publish = {
        "announcement": (GCAnnouncementModel, publish_announcement),
        "document": (GCCommonDocumentModel, publish_common_document),
        "itinerary": (GCItineraryVersionModel, publish_itinerary),
    }[kind]
    common = {"agency_id": access.agency_id, "group_id": group.id, "gc_group_access_id": access.id, "title": "Synthetic content"}
    if kind == "announcement":
        common.update(logical_announcement_id=logical_id, category="general", priority="normal", body="Synthetic")
    elif kind == "document":
        common.update(logical_document_id=logical_id, category="itinerary_pdf", storage_key="synthetic/document.pdf", safe_filename="document.pdf", media_type="application/pdf", byte_size=20, checksum_sha256="a" * 64)
    else:
        common.update(content_checksum="a" * 64)
    old = model(id=uuid.UUID("bbbbbbbb-0000-4000-8000-000000000020"), version=1, status="published", published_at=now, **common)
    draft = model(id=uuid.UUID("aaaaaaaa-0000-4000-8000-000000000010"), version=2, status="draft", **common)
    if kind != "itinerary":
        old.passenger_visible = True
    if kind == "document":
        draft.storage_key = "synthetic/replacement.pdf"
    db_session.add_all([old, draft])
    await db_session.commit()
    response = await publish(group.id, draft.id, Request({"type": "http", "method": "POST", "path": "/", "headers": []}), None, actor, db_session)
    await db_session.commit()
    assert response.status == "published"
    records = list(await db_session.scalars(select(model).order_by(model.version)))
    assert [record.status for record in records] == ["retired", "published"]
