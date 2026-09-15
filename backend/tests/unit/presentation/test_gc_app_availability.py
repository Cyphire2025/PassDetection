"""Database availability filtering agrees with page/detail state and restore flow."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.infrastructure.database.gc_mobile_models import GCGroupAccessModel
from app.presentation.api.v1.routes.gc_app import search_gc_groups
from tests.unit.presentation.test_gc_app_closed_collection_groups import _context, _group


async def _search(session, actor, **filters):
    return await search_gc_groups(
        q=None,
        agency_id=None,
        group_id=None,
        gc_enabled=None,
        lifecycle_status=None,
        offset=filters.pop("offset", 0),
        limit=filters.pop("limit", 2),
        current_user=actor,
        session=session,
        **filters,
    )


async def test_configured_filters_keep_paused_groups_and_exclude_them_from_new_add_picker(
    db_session,
):
    actor, organization, closed = await _context(db_session)
    opened = _group(actor.agency_id, status="active")
    paused = _group(actor.agency_id)
    db_session.add_all([opened, paused])
    await db_session.flush()
    db_session.add(
        GCGroupAccessModel(
            id=uuid.uuid4(),
            agency_id=actor.agency_id,
            group_id=paused.id,
            client_organization_id=organization.id,
            is_enabled=False,
            revoked_at=datetime.now(UTC),
        )
    )
    await db_session.flush()
    configured = await _search(db_session, actor, configured_only=True)
    assert configured.total == 1 and configured.items[0].id == paused.id
    assert configured.items[0].app_availability == "paused"
    assert configured.items[0].access.app_availability == "paused"
    eligible = await _search(db_session, actor, eligible_only=True, unconfigured_only=True)
    assert eligible.total == 2 and {item.id for item in eligible.items} == {closed.id, opened.id}


@pytest.mark.parametrize("wanted", ["active", "scheduled", "paused", "ended", "unavailable"])
async def test_availability_filter_applies_before_pagination_and_matches_projection(
    db_session, wanted
):
    actor, organization, _ = await _context(db_session)
    now = datetime.now(UTC)
    cases = [
        ("active", "closed", {}, None),
        ("active", "active", {}, None),
        (
            "scheduled",
            "closed",
            {"access_starts_at": now + timedelta(days=1)},
            "access_not_started",
        ),
        ("paused", "closed", {"is_enabled": False}, "app_disabled"),
        ("paused", "closed", {"revoked_at": now}, "access_revoked"),
        (
            "paused",
            "closed",
            {
                "passenger_access_enabled": False,
                "client_manager_access_enabled": False,
                "coordinator_access_enabled": False,
            },
            "no_roles_enabled",
        ),
        ("ended", "closed", {"access_expires_at": now - timedelta(seconds=1)}, "access_ended"),
        ("unavailable", "archived", {}, "group_archived"),
        ("unavailable", "deleted", {}, "group_deleted"),
    ]
    expected = {}
    for state, lifecycle, fields, reason in cases:
        group = _group(actor.agency_id, status=lifecycle)
        db_session.add(group)
        await db_session.flush()
        db_session.add(
            GCGroupAccessModel(
                id=uuid.uuid4(),
                agency_id=actor.agency_id,
                group_id=group.id,
                client_organization_id=organization.id,
                **{"is_enabled": True, "passenger_access_enabled": True, **fields},
            )
        )
        if state == wanted:
            expected[group.id] = reason
    await _context(db_session)  # foreign agency remains outside all counts
    await db_session.flush()
    pages = [
        await _search(
            db_session, actor, configured_only=True, availability=wanted, offset=offset, limit=1
        )
        for offset in range(len(expected))
    ]
    assert all(page.total == len(expected) for page in pages)
    items = [page.items[0] for page in pages]
    assert {item.id: item.app_availability_reason for item in items} == expected
    assert all(
        item.app_availability == wanted and item.app_availability_evaluated_at for item in items
    )
