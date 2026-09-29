"""Parity with shared website roster logic, tenant boundaries and continuation conflicts."""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest

from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.roster_reads import MCPRosterReadService
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.passports.roster_view_service import prepared_roster
from app.infrastructure.repositories.user_repository import UserRepository


@pytest.fixture
async def roster_fixture(db_session):
    actor = UserModel(id=uuid.uuid4(), email="roster@example.test", hashed_password="fixture",
                      full_name="Reader", role="super_admin", is_active=True)
    agency = AgencyModel(id=uuid.uuid4(), name="Roster Agency", email="rosteragency@example.test")
    other = AgencyModel(id=uuid.uuid4(), name="Other Agency", email="otheragency@example.test")
    db_session.add_all([actor, agency, other])
    await db_session.flush()
    group = ClientGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Roster", token=uuid.uuid4().hex)
    db_session.add(group)
    await db_session.flush()
    return db_session, actor, agency, other, group, MCPRosterReadService(db_session, cursor_secret="test-cursor")


def passport(group, index, **values):
    return PassportSubmissionModel(id=uuid.uuid4(), group_id=group.id, agency_id=group.agency_id,
        client_name=f"Person {index:03}", client_email=f"person{index}@example.test", client_phone="+919876543210",
        image_s3_key=f"private/{index}", status=values.pop("status", "staff_approved"), **values)


async def test_roster_matches_shared_website_pages_and_filters(roster_fixture):
    session, actor, agency, _, group, service = roster_fixture
    rows = [passport(group, index, document_follow_up=index % 3 == 0) for index in range(17)]
    session.add_all([*rows, passport(group, 100, status="uploaded")])
    await session.flush()
    user = await UserRepository(session).get_by_id(actor.id)
    website, _ = await prepared_roster(session, group_id=group.id, user=replace(user, agency_id=agency.id),
        include_deleted=False, submission_filter="all", sort_by="name", sort_order="asc", search=None, page_size=5)
    page = await service.list_passports(user_id=actor.id, group_id=group.id, page_size=5)
    seen = []
    number = 1
    while True:
        assert [row["submission_id"] for row in page["items"]] == [str(entry.submission.id) for entry in website.page(number).items]
        seen.extend(row["submission_id"] for row in page["items"])
        assert all("image_s3_key" not in row and "client_email" not in row for row in page["items"])
        if not page["has_more"]:
            break
        page = await service.list_passports(user_id=actor.id, group_id=group.id, page_size=5, cursor=page["next_cursor"])
        number += 1
    assert len(seen) == len(set(seen)) == 17
    assert page["group_total"] == 17 and page["completeness"] == "complete"
    follow_up = await service.list_passports(user_id=actor.id, group_id=group.id,
        submission_filter="document_follow_up", include_contact_details=True)
    assert len(follow_up["items"]) == 6 and all(row["document_follow_up"] for row in follow_up["items"])
    assert follow_up["items"][0]["client_email"].endswith("@example.test")


async def test_empty_missing_and_cross_tenant_rows_are_distinct(roster_fixture):
    session, actor, _, other, group, service = roster_fixture
    missing = await service.list_passports(user_id=actor.id, group_id=uuid.uuid4())
    assert missing["resolution"] == "not_found" and missing["completeness"] == "unavailable"
    empty = await service.list_passports(user_id=actor.id, group_id=group.id)
    assert empty["resolution"] == "resolved" and empty["group_total"] == 0
    other_group = ClientGroupModel(id=uuid.uuid4(), agency_id=other.id, name="Other", token=uuid.uuid4().hex)
    session.add(other_group)
    await session.flush()
    session.add(passport(other_group, 1))
    await session.flush()
    assert (await service.list_passports(user_id=actor.id, group_id=group.id))["group_total"] == 0
    group.status = "archived"
    await session.flush()
    assert (await service.list_passports(user_id=actor.id, group_id=group.id))["resolution"] == "not_found"


async def test_cursor_is_bound_and_roster_changes_conflict(roster_fixture):
    session, actor, _, _, group, service = roster_fixture
    rows = [passport(group, index) for index in range(3)]
    session.add_all(rows)
    await session.flush()
    first = await service.list_passports(user_id=actor.id, group_id=group.id, page_size=1)
    cursor = first["next_cursor"]
    with pytest.raises(ValueError, match="different query"):
        await service.list_passports(user_id=actor.id, group_id=group.id, page_size=2, cursor=cursor)
    with pytest.raises(ValueError, match="Invalid or expired"):
        await service.list_passports(user_id=actor.id, group_id=group.id, page_size=1, cursor=cursor + "x")
    rows[-1].client_name = "Changed after first page"
    await session.flush()
    with pytest.raises(ValueError, match="roster changed"):
        await service.list_passports(user_id=actor.id, group_id=group.id, page_size=1, cursor=cursor)


async def test_role_loss_and_bounds_fail_before_content(roster_fixture):
    session, actor, _, _, group, service = roster_fixture
    with pytest.raises(ValueError, match="Page size"):
        await service.list_passports(user_id=actor.id, group_id=group.id, page_size=101)
    actor.role = "agency_admin"
    await session.flush()
    with pytest.raises(MCPAuthError):
        await service.list_passports(user_id=actor.id, group_id=group.id)
