"""Dashboard administration keeps content, revisions and audit inside one agency."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.gc_mobile_models import (
    GCCommonDocumentModel,
    GCGroupAccessModel,
    GCItineraryVersionModel,
)
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    UserModel,
)
from app.presentation.api.v1.routes.gc_app_common_documents import list_common_documents
from app.presentation.api.v1.routes.gc_app_common_publication import unpublish_common_document
from app.presentation.api.v1.routes.gc_app_itineraries import (
    preview_itinerary,
    unpublish_itinerary,
)


def _actor(role: UserRole, agency_id: uuid.UUID | None) -> User:
    return User.create(
        email=f"{uuid.uuid4().hex}@example.test",
        hashed_password="synthetic-unused-password-hash",
        full_name="Synthetic content administrator",
        role=role,
        agency_id=agency_id,
    )


async def _context(session: AsyncSession) -> tuple[User, ClientGroupModel, GCGroupAccessModel]:
    agency = AgencyModel(id=uuid.uuid4(), name="Synthetic agency", email=f"{uuid.uuid4()}@example.test")
    session.add(agency)
    await session.flush()
    actor = _actor(UserRole.AGENCY_ADMIN, agency.id)
    group = ClientGroupModel(
        id=uuid.uuid4(), agency_id=agency.id, name="Synthetic content group",
        token=uuid.uuid4().hex, status="closed",
    )
    session.add_all([
        group,
        UserModel(
            id=actor.id, agency_id=agency.id, email=actor.email,
            full_name=actor.full_name, hashed_password=actor.hashed_password,
            role=actor.role.value,
        ),
    ])
    await session.flush()
    access = GCGroupAccessModel(
        id=uuid.uuid4(), agency_id=agency.id, group_id=group.id,
        is_enabled=True, passenger_access_enabled=True,
    )
    session.add(access)
    await session.flush()
    return actor, group, access


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "has_agency", "override_agency", "expected_status", "detail"),
    [
        (UserRole.SUPER_ADMIN, False, False, 422, "agency_id is required"),
        (UserRole.AGENCY_ADMIN, False, False, 403, "Account has no agency"),
        (UserRole.AGENCY_MANAGER, True, True, 403, "Agency scope mismatch"),
    ],
)
async def test_dashboard_content_rejects_ambiguous_or_foreign_agency_before_queries(
    role: UserRole, has_agency: bool, override_agency: bool, expected_status: int, detail: str,
) -> None:
    actor = _actor(role, uuid.uuid4() if has_agency else None)
    session = AsyncMock(spec=AsyncSession)
    with pytest.raises(HTTPException) as error:
        await preview_itinerary(
            group_id=uuid.uuid4(), agency_id=uuid.uuid4() if override_agency else None,
            current_user=actor, session=session,
        )
    assert error.value.status_code == expected_status
    assert detail in error.value.detail
    session.execute.assert_not_awaited()
    session.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_dashboard_content_does_not_disclose_a_real_group_from_another_agency(
    db_session: AsyncSession,
) -> None:
    actor, _own_group, _own_access = await _context(db_session)
    _other_actor, other_group, _other_access = await _context(db_session)
    with pytest.raises(HTTPException) as error:
        await preview_itinerary(
            other_group.id, agency_id=None, current_user=actor, session=db_session,
        )
    assert error.value.status_code == 404
    assert error.value.detail == "GC App group not found"
    assert await db_session.scalar(select(ClientGroupModel.id).where(ClientGroupModel.id == other_group.id))


@pytest.mark.asyncio
async def test_dashboard_preview_returns_its_own_unsent_itinerary_draft(
    db_session: AsyncSession,
) -> None:
    actor, group, access = await _context(db_session)
    draft = GCItineraryVersionModel(
        id=uuid.uuid4(), agency_id=actor.agency_id, group_id=group.id,
        gc_group_access_id=access.id, version=1, status="draft", title="Unsent itinerary",
    )
    db_session.add(draft)
    await db_session.flush()
    response = await preview_itinerary(group.id, agency_id=None, current_user=actor, session=db_session)
    assert (response.id, response.group_id, response.status, response.title) == (
        draft.id, group.id, "draft", "Unsent itinerary",
    )
    assert response.published_at is None
    assert response.days == []
    assert access.itinerary_version == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["itinerary", "common_document"])
async def test_dashboard_unpublish_returns_retired_content_and_records_only_scoped_audit(
    db_session: AsyncSession, kind: str,
) -> None:
    actor, group, access = await _context(db_session)
    now = datetime.now(UTC)
    shared = dict(
        id=uuid.uuid4(), agency_id=actor.agency_id, group_id=group.id,
        gc_group_access_id=access.id, version=1, status="published",
        title="Private administrator handover", published_at=now,
    )
    if kind == "itinerary":
        record = GCItineraryVersionModel(**shared, content_checksum="a" * 64)
        unpublish = unpublish_itinerary
        version_field = "itinerary_version"
    else:
        record = GCCommonDocumentModel(
            **shared, logical_document_id=uuid.uuid4(), category="itinerary_pdf",
            storage_key="synthetic/private-handover.pdf", safe_filename="handover.pdf",
            media_type="application/pdf", byte_size=20, checksum_sha256="a" * 64,
            passenger_visible=True,
        )
        unpublish = unpublish_common_document
        version_field = "common_document_version"
    db_session.add(record)
    await db_session.flush()
    before = (access.revision, access.manifest_version, getattr(access, version_field))
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    response = await unpublish(group.id, record.id, request, None, actor, db_session)
    assert (response.id, response.group_id, response.status) == (record.id, group.id, "retired")
    assert (access.revision, access.manifest_version, getattr(access, version_field)) == tuple(
        value + 1 for value in before
    )
    if kind == "itinerary":
        with pytest.raises(HTTPException, match="Itinerary not found"):
            await preview_itinerary(group.id, agency_id=None, current_user=actor, session=db_session)
    else:
        assert await list_common_documents(group.id, agency_id=None, current_user=actor, session=db_session) == []
    audit = await db_session.scalar(
        select(AuditLogModel).where(AuditLogModel.action == f"gc_app.{kind}_unpublished")
    )
    assert audit is not None
    assert (audit.agency_id, audit.user_id, audit.entity_id) == (actor.agency_id, actor.id, str(record.id))
    assert audit.metadata_json["group_id"] == str(group.id)
    assert "Private administrator handover" not in json.dumps(audit.metadata_json)
    assert "synthetic/private-handover.pdf" not in json.dumps(audit.metadata_json)
