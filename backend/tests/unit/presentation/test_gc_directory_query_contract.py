"""Retained directory tenant, literal search and conditional metrics contracts."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.domain.entities.entities import UserRole
from app.infrastructure.database.gc_mobile_models import GCGroupAccessModel
from app.infrastructure.database.models import AgencyModel
from app.presentation.api.v1.routes import gc_app_group_directory as directory
from tests.unit.presentation.test_gc_app_closed_collection_groups import _context, _group


async def _search(session, actor, **options):
    arguments = {
        "q": None,
        "agency_id": None,
        "group_id": None,
        "gc_enabled": None,
        "eligible_only": False,
        "configured_only": False,
        "unconfigured_only": False,
        "availability": None,
        "lifecycle_status": None,
        "offset": 0,
        "limit": 50,
        **options,
    }
    return await directory.search_gc_groups(**arguments, current_user=actor, session=session)


async def test_agency_directory_keeps_literal_search_active_scope_and_page(db_session):
    actor, _, _ = await _context(db_session)
    own = await db_session.get(AgencyModel, actor.agency_id)
    own.name = "Literal %_ agency"
    other = AgencyModel(id=uuid.uuid4(), name="Literal XX agency", email="other@example.test")
    inactive = AgencyModel(
        id=uuid.uuid4(), name="A inactive", email="inactive@example.test", is_active=False
    )
    db_session.add_all([other, inactive])
    await db_session.flush()
    literal = await directory.list_gc_agencies(
        q="  %_  ", offset=0, limit=1, current_user=actor, session=db_session
    )
    assert literal.total == 1 and literal.items[0].id == own.id
    scoped = await directory.list_gc_agencies(
        q=None, offset=0, limit=10, current_user=actor, session=db_session
    )
    assert [item.id for item in scoped.items] == [own.id]
    super_admin = SimpleNamespace(role=UserRole.SUPER_ADMIN, agency_id=None)
    page = await directory.list_gc_agencies(
        q=" Literal  ", offset=1, limit=1, current_user=super_admin, session=db_session
    )
    assert page.total == 2 and [item.id for item in page.items] == [other.id]


@pytest.mark.parametrize("operation", ["agencies", "groups"])
async def test_unassigned_directory_actor_is_rejected(db_session, operation):
    actor = SimpleNamespace(role=UserRole.AGENCY_ADMIN, agency_id=None)
    with pytest.raises(HTTPException) as rejected:
        if operation == "agencies":
            await directory.list_gc_agencies(
                q=None, offset=0, limit=1, current_user=actor, session=db_session
            )
        else:
            await _search(db_session, actor)
    assert rejected.value.status_code == 403


@pytest.mark.parametrize(
    "options,expected,metrics",
    [
        ({}, {"fresh", "enabled", "paused", "removed"}, False),
        ({"gc_enabled": True}, {"enabled"}, True),
        ({"gc_enabled": False}, {"fresh", "paused", "removed"}, False),
        ({"eligible_only": True, "gc_enabled": True}, {"fresh", "paused", "removed"}, True),
        ({"configured_only": True}, {"enabled", "paused"}, True),
        ({"unconfigured_only": True}, {"fresh", "removed"}, False),
        ({"configured_only": True, "unconfigured_only": True}, set(), True),
    ],
)
async def test_group_filter_combinations_keep_counts_and_conditional_metrics(
    db_session, monkeypatch, options, expected, metrics
):
    actor, organization, fresh = await _context(db_session)
    groups = {"fresh": fresh}
    for name in ("enabled", "paused", "removed"):
        group = _group(actor.agency_id, status="active")
        group.company_id = organization.id
        groups[name] = group
        db_session.add(group)
        await db_session.flush()
        db_session.add(
            GCGroupAccessModel(
                id=uuid.uuid4(),
                agency_id=actor.agency_id,
                group_id=group.id,
                client_organization_id=organization.id,
                is_enabled=name == "enabled",
                revoked_at=None if name == "enabled" else datetime.now(UTC),
                removed_at=datetime.now(UTC) if name == "removed" else None,
            )
        )
    await _context(db_session)  # Never enters this tenant's result or total.
    await db_session.flush()
    execute = db_session.execute
    statements = []

    async def capture(statement, *args, **kwargs):
        statements.append(
            str(
                statement.compile(
                    dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
                )
            )
        )
        return await execute(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", capture)
    page = await _search(db_session, actor, **options)
    assert page.total == len(expected)
    assert {item.id for item in page.items} == {groups[name].id for name in expected}
    assert len(statements) == 2
    assert "count(*)" in statements[0] and "mobile_device_sessions" not in statements[0]
    assert ("mobile_device_sessions" in statements[1]) is metrics
    assert all(
        item.access is None
        or (item.access.active_mobile_users == 0 and item.access.synced_device_count == 0)
        for item in page.items
    )


async def test_group_literal_query_and_lifecycle_admission(db_session):
    actor, _, group = await _context(db_session)
    group.name = "Exact %_ party"
    other = _group(actor.agency_id)
    other.name = "Exact XX party"
    db_session.add(other)
    await db_session.flush()
    page = await _search(db_session, actor, q="  %_  ", lifecycle_status="closed")
    assert page.total == 1 and [item.id for item in page.items] == [group.id]
    with pytest.raises(HTTPException) as rejected:
        await _search(db_session, actor, lifecycle_status="not-a-status")
    assert rejected.value.status_code == 422
