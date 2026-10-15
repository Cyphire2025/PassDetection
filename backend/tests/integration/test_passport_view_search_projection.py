"""Roster metadata is search-only and remains behind live object authorization."""

from __future__ import annotations

import uuid
import zlib
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.passports import roster_cache_codec
from app.infrastructure.passports.roster_cache import RosterCache
from app.infrastructure.passports.roster_view_service import prepared_roster
from app.infrastructure.repositories.passport_submission_view_repository import (
    PassportSubmissionViewRepository,
)


@pytest.fixture
async def roster(db_session):
    agency_id, other_agency_id, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db_session.add_all([
        AgencyModel(id=agency_id, name="Synthetic agency", email="agency@example.test"),
        AgencyModel(id=other_agency_id, name="Other agency", email="other@example.test"),
    ])
    await db_session.flush()
    db_session.add(UserModel(id=user_id, agency_id=agency_id, email="staff@example.test",
                            full_name="Synthetic staff", hashed_password="unused", role="agency_staff"))
    await db_session.flush()
    group = ClientGroupModel(id=uuid.uuid4(), agency_id=agency_id, created_by_user_id=user_id,
                             name="Synthetic roster", token=uuid.uuid4().hex)
    db_session.add(group)
    await db_session.flush()
    rows = [PassportSubmissionModel(id=uuid.uuid4(), agency_id=agency_id, group_id=group.id,
        client_name=f"Synthetic traveller {number}", image_s3_key="synthetic/private-image",
        mrz_raw="synthetic-private-raw-ocr", status="submitted",
        staff_metadata={"staff_code": f"STAFF-{number}", "nested": {"private": "synthetic-note"}})
        for number in range(2)]
    db_session.add_all(rows)
    await db_session.flush()
    user = User(id=user_id, agency_id=agency_id, email="staff@example.test", full_name="Synthetic staff",
                hashed_password="unused", role=UserRole.AGENCY_STAFF)
    return db_session, user, other_agency_id, group, rows


@pytest.mark.parametrize("search", [None, "", " \t ", "STAFF-1"])
async def test_metadata_is_loaded_only_for_nonblank_search_and_never_cached(roster, search):
    session, user, _, group, rows = roster
    index, revision = await prepared_roster(
        session, group_id=group.id, user=user, include_deleted=False,
        submission_filter="all", sort_by="name", sort_order="asc", search=search, page_size=1,
    )
    assert revision is not None
    if search and search.strip():
        assert index.ordered_submission_ids == (rows[1].id,)
        assert index.pages[0][0].submission.staff_metadata["staff_code"] == "STAFF-1"
    else:
        assert index.ordered_submission_ids == tuple(row.id for row in rows)
        assert all(entry.submission.staff_metadata is None for page in index.pages for entry in page)
    # Inspect decrypted serialized data too: encryption alone is not minimization.
    cache = RosterCache(AsyncMock(), secret="synthetic-key-only")
    encoded = roster_cache_codec.encode(index, cache.cipher, "synthetic-identity")
    assert encoded is not None
    payload = zlib.decompress(cache.cipher.decrypt(encoded))
    assert b"staff_metadata" not in payload and b"STAFF-" not in payload
    assert b"synthetic-note" not in payload and b"synthetic-private-raw-ocr" not in payload
    assert b"synthetic/private-image" not in payload
    restored = roster_cache_codec.decode(encoded, cache.cipher, "synthetic-identity")
    assert restored.ordered_submission_ids == index.ordered_submission_ids


@pytest.mark.parametrize("search_metadata", [False, True])
@pytest.mark.parametrize("denied_scope", ["unassigned_staff", "other_agency", "archived", "deleted"])
async def test_projection_and_search_do_not_escape_staff_or_tenant_scope(roster, search_metadata, denied_scope):
    session, user, other_agency_id, group, rows = roster
    if denied_scope == "unassigned_staff":
        user = replace(user, id=uuid.uuid4())
    elif denied_scope == "other_agency":
        user = replace(user, agency_id=other_agency_id)
    elif denied_scope == "archived":
        group.status = "archived"
    else:
        group.deleted_at = datetime.now(UTC)
    await session.flush()
    repository = PassportSubmissionViewRepository(session)
    assert await repository.projection(group_id=group.id, user=user, include_deleted=False,
                                       include_search_metadata=search_metadata) == []
    assert await repository.page_details(submission_ids=[row.id for row in rows],
                                         group_id=group.id, user=user) == {}
