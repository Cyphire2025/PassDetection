"""Real relational projections for initial MCP group discovery (SQLite fixture)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event

from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.group_reads import MCPGroupReadService
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    UserModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)


@pytest.fixture
async def groups_fixture(db_session):
    actor = UserModel(id=uuid.uuid4(), email="mcp-reader@example.test", hashed_password="fixture",
                      full_name="Reader", role="super_admin", is_active=True)
    first = AgencyModel(id=uuid.uuid4(), name="First Agency", email="first@example.test")
    second = AgencyModel(id=uuid.uuid4(), name="Second Agency", email="second@example.test")
    db_session.add_all([actor, first, second])
    await db_session.flush()
    return db_session, actor, first, second, MCPGroupReadService(db_session, cursor_secret="test-cursor-secret")


def group(agency, name="Trip", *, identifier=None, created_at=None, **values):
    return ClientGroupModel(id=identifier or uuid.uuid4(), agency_id=agency.id, name=name,
                            token=uuid.uuid4().hex, created_at=created_at or datetime.now(UTC) - timedelta(minutes=2), **values)


@pytest.mark.asyncio
async def test_empty_import_only_and_duplicate_names_are_explicit(groups_fixture):
    session, actor, first, second, service = groups_fixture
    empty = group(first, "Shared", import_only=True)
    duplicate = group(second, "Shared")
    session.add_all([empty, duplicate])
    await session.flush()
    ambiguous = await service.resolve_group(user_id=actor.id, name="shared")
    assert ambiguous["resolution"] == "ambiguous" and ambiguous["resolved_group_id"] is None
    assert ambiguous["requires_choice"] is True
    assert {row["agency_name"] for row in ambiguous["items"]} == {"First Agency", "Second Agency"}
    scoped = await service.resolve_group(user_id=actor.id, name="Shared", agency_id=first.id)
    assert scoped["resolution"] == "resolved" and scoped["resolved_group_id"] == str(empty.id)
    assert scoped["items"][0]["import_only"] is True
    assert all(count == 0 for count in scoped["items"][0]["counts"].values())
    assert "token" not in scoped["items"][0]
    missing = await service.resolve_group(user_id=actor.id, group_id=empty.id, agency_id=second.id)
    assert missing["resolution"] == "not_found"


@pytest.mark.asyncio
async def test_passport_operational_and_broadcast_entries_are_not_collapsed(groups_fixture):
    session, actor, first, second, service = groups_fixture
    trip = group(first)
    session.add(trip)
    await session.flush()
    passports = [PassportSubmissionModel(id=uuid.uuid4(), group_id=trip.id, agency_id=first.id,
                                         client_name=f"Person {index}", image_s3_key=f"fixture/{index}", status=status)
                 for index, status in enumerate(["confirmed", "staff_approved", "uploaded", "client_submitted"])]
    session.add_all(passports)
    broadcasts = [WhatsAppBroadcastGroupModel(id=uuid.uuid4(), agency_id=first.id, name=f"List {index}") for index in range(2)]
    archived = WhatsAppBroadcastGroupModel(id=uuid.uuid4(), agency_id=first.id, name="Archive", archived_at=datetime.now(UTC))
    unrelated = WhatsAppBroadcastGroupModel(id=uuid.uuid4(), agency_id=second.id, name="Other agency")
    session.add_all([*broadcasts, archived, unrelated])
    await session.flush()
    session.add(PassportRosterResolutionModel(id=uuid.uuid4(), agency_id=first.id,
        client_group_id=trip.id, submission_id=passports[3].id, resolution_type="rejected", status="active",
        excluded_submission_ids=[], resolved_by_user_id=actor.id))
    for index, broadcast in enumerate([*broadcasts, archived, unrelated]):
        session.add(ClientGroupWhatsAppBroadcastLinkModel(client_group_id=trip.id, broadcast_group_id=broadcast.id,
                                                         agency_id=first.id))
        session.add(WhatsAppBroadcastRecipientModel(id=uuid.uuid4(), agency_id=broadcast.agency_id,
            broadcast_group_id=broadcast.id, phone_number="+919876543210", normalized_phone_number="919876543210"))
    session.add(WhatsAppBroadcastRecipientModel(id=uuid.uuid4(), agency_id=first.id, broadcast_group_id=broadcasts[0].id,
        phone_number="+919876543211", normalized_phone_number="919876543211", removed_at=datetime.now(UTC)))
    await session.flush()
    result = await service.resolve_group(user_id=actor.id, group_id=trip.id)
    assert result["items"][0]["counts"] == {"passport_submission_records": 4, "operational_passengers": 2,
                                            "whatsapp_active_recipient_entries": 2, "linked_whatsapp_broadcasts": 3}
    assert "not a unique-person count" in result["count_definitions"]["whatsapp_active_recipient_entries"]


@pytest.mark.asyncio
async def test_keyset_ties_large_pagination_and_newer_insert(groups_fixture):
    session, actor, first, _, service = groups_fixture
    created = datetime.now(UTC) - timedelta(minutes=3)
    seeded = [group(first, f"Trip {index}", identifier=uuid.UUID(f"aaaaaaaa-aaaa-aaaa-aaaa-{index + 1:012x}"), created_at=created) for index in range(107)]
    session.add_all(seeded)
    await session.flush()
    page = await service.list_groups(user_id=actor.id, agency_id=first.id, page_size=17)
    seen = [row["id"] for row in page["items"]]
    newer = group(first, "New after first page", created_at=datetime.now(UTC))
    session.add(newer)
    await session.flush()
    while page["next_cursor"]:
        page = await service.list_groups(user_id=actor.id, agency_id=first.id, page_size=17, cursor=page["next_cursor"])
        seen.extend(row["id"] for row in page["items"])
    assert len(seen) == len(set(seen)) == 107
    assert seen == [str(item.id) for item in reversed(seeded)]
    assert str(newer.id) not in seen
    assert page["consistency"]["snapshot_guaranteed"] is False


@pytest.mark.asyncio
async def test_cursor_tampering_filter_binding_and_expiry(groups_fixture):
    session, actor, first, second, service = groups_fixture
    session.add_all([group(first), group(first)])
    await session.flush()
    page = await service.list_groups(user_id=actor.id, agency_id=first.id, page_size=1)
    cursor = page["next_cursor"]
    for override in [{"agency_id": second.id}, {"name": "Changed"}, {"page_size": 2}, {"cursor": cursor + "x"}]:
        with pytest.raises(ValueError, match="cursor"):
            await service.list_groups(**{**dict(user_id=actor.id, agency_id=first.id, page_size=1, cursor=cursor), **override})
    import base64
    import json
    state = json.loads(base64.urlsafe_b64decode(cursor.split(".")[0] + "=" * (-len(cursor.split(".")[0]) % 4)))
    state["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match="expired"):
        await service.list_groups(user_id=actor.id, agency_id=first.id, page_size=1, cursor=service._encode(state))


@pytest.mark.asyncio
async def test_names_are_literal_and_deleted_history_is_explicit(groups_fixture):
    session, actor, first, _, service = groups_fixture
    session.add_all([group(first, "Trip_100%"), group(first, "TripA1000"),
                     group(first, "Retained", status="deleted", deleted_at=datetime.now(UTC))])
    await session.flush()
    for match in ("exact", "contains"):
        page = await service.list_groups(user_id=actor.id, name="Trip_100%", name_match=match)
        assert [row["name"] for row in page["items"]] == ["Trip_100%"]
    assert len((await service.list_groups(user_id=actor.id))["items"]) == 2
    assert len((await service.list_groups(user_id=actor.id, include_deleted=True))["items"]) == 3
    with pytest.raises(ValueError):
        await service.list_groups(user_id=actor.id, status="deleted")


@pytest.mark.asyncio
async def test_role_and_deactivation_are_rechecked(groups_fixture):
    session, actor, first, _, service = groups_fixture
    session.add(group(first))
    await session.flush()
    actor.role = "agency_admin"
    await session.flush()
    with pytest.raises(MCPAuthError):
        await service.list_groups(user_id=actor.id)
    actor.role, actor.is_active = "super_admin", False
    await session.flush()
    with pytest.raises(MCPAuthError):
        await service.list_groups(user_id=actor.id)


@pytest.mark.asyncio
async def test_between_page_rename_is_live_and_cursor_is_actor_bound(groups_fixture):
    session, actor, first, _, service = groups_fixture
    older = group(first, "Trip older", created_at=datetime.now(UTC) - timedelta(days=2))
    newer = group(first, "Trip newer", created_at=datetime.now(UTC) - timedelta(days=1))
    other_actor = UserModel(id=uuid.uuid4(), email="other-mcp@example.test", hashed_password="fixture",
                            full_name="Other reader", role="super_admin", is_active=True)
    session.add_all([older, newer, other_actor])
    await session.flush()
    first_page = await service.list_groups(user_id=actor.id, name="Trip", page_size=1)
    with pytest.raises(ValueError, match="scoped"):
        await service.list_groups(user_id=other_actor.id, name="Trip", page_size=1, cursor=first_page["next_cursor"])
    older.name = "Changed outside filter"
    await session.flush()
    next_page = await service.list_groups(user_id=actor.id, name="Trip", page_size=1, cursor=first_page["next_cursor"])
    assert next_page["items"] == []
    assert next_page["consistency"]["snapshot_guaranteed"] is False
    assert "may change between pages" in next_page["consistency"]["notice"]


@pytest.mark.asyncio
async def test_fixed_query_count_and_live_edits_are_explicit(groups_fixture):
    session, actor, first, _, service = groups_fixture
    session.add_all([group(first, f"Trip {index}") for index in range(30)])
    await session.flush()
    statements = []
    engine = session.get_bind()
    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", observe)
    try:
        page = await service.list_groups(user_id=actor.id, page_size=25)
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert len(statements) == 2
    assert len(page["items"]) == 25
    assert page["consistency"]["mode"] == "live_keyset"
    assert "may change between pages" in page["consistency"]["notice"]


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [0, 101, True, 1.5])
async def test_page_size_is_bounded(groups_fixture, size):
    _, actor, _, _, service = groups_fixture
    with pytest.raises(ValueError, match="Page size"):
        await service.list_groups(user_id=actor.id, page_size=size)
