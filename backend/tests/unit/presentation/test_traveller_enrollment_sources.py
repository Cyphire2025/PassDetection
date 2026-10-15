"""Staff enrollment discovery is scoped, selective and incrementally paged."""

import uuid
from types import SimpleNamespace

import pytest

from app.domain.entities.entities import UserRole
from app.presentation.api.v1.routes.traveller_admin import list_enrollment_sources
from tests.unit.application.test_traveller_enrollment import _fixture, _source


@pytest.mark.asyncio
async def test_source_listing_filters_tenant_status_and_uses_cursor(db_session):
    ctx = await _fixture(db_session)
    other = await _fixture(db_session)
    eligible = _source(ctx.group)
    eligible.client_name = "Searchable Person"
    pending = _source(ctx.group)
    pending.status = "client_submitted"
    db_session.add_all([eligible, pending])
    await db_session.flush()
    user = SimpleNamespace(id=ctx.request.actor_id, agency_id=ctx.request.agency_id, role=UserRole.AGENCY_ADMIN)
    first = await list_enrollment_sources(ctx.request.company_id, ctx.request.group_id,
        search="", cursor=None, page_size=1, agency_id=None, user=user, session=db_session)
    assert len(first.items) == 1 and first.next_cursor
    second = await list_enrollment_sources(ctx.request.company_id, ctx.request.group_id,
        search="", cursor=uuid.UUID(first.next_cursor), page_size=1, agency_id=None, user=user, session=db_session)
    assert {first.items[0].id, second.items[0].id} == {ctx.source.id, eligible.id}
    assert second.next_cursor is None and first.expected_group_revision == 1
    found = await list_enrollment_sources(ctx.request.company_id, ctx.request.group_id,
        search="Searchable", cursor=None, page_size=25, agency_id=None, user=user, session=db_session)
    assert [item.id for item in found.items] == [eligible.id]
    assert other.source.id not in {first.items[0].id, second.items[0].id}
    assert set(found.items[0].model_dump()) == {"id", "display_name", "status", "extraction_revision",
        "candidate_traveller_id", "candidate_display_name", "candidate_profile_revision", "candidate_change_kind"}
