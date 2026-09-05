from __future__ import annotations

import uuid

import pytest

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.presentation.api.v1.routes.search import global_search


async def _seed_search_scope(session, source: str, field: str):
    agency_id, foreign_agency_id, user_id, other_user_id = (uuid.uuid4() for _ in range(4))
    session.add_all(
        [
            AgencyModel(id=agency_id, name="Synthetic agency", email=f"{agency_id}@example.test"),
            AgencyModel(
                id=foreign_agency_id,
                name="Foreign agency",
                email=f"{foreign_agency_id}@example.test",
            ),
        ]
    )
    await session.flush()
    session.add_all(
        [
            UserModel(
                id=user_id,
                agency_id=agency_id,
                full_name="Staff",
                email=f"{user_id}@example.test",
                hashed_password="unused",
                role="agency_staff",
            ),
            UserModel(
                id=other_user_id,
                agency_id=agency_id,
                full_name="Other staff",
                email=f"{other_user_id}@example.test",
                hashed_password="unused",
                role="agency_staff",
            ),
        ]
    )
    await session.flush()
    groups = [
        ClientGroupModel(
            id=uuid.uuid4(),
            agency_id=tenant,
            created_by_user_id=owner,
            name="Synthetic group",
            token=uuid.uuid4().hex,
        )
        for tenant, owner in [
            (agency_id, user_id),
            (agency_id, other_user_id),
            (foreign_agency_id, None),
        ]
    ]
    session.add_all(groups)
    await session.flush()
    matches = [
        PassportSubmissionModel(
            id=uuid.uuid4(),
            agency_id=group.agency_id,
            group_id=group.id,
            client_name="Browser Passenger 1",
            image_s3_key="synthetic/front.jpg",
            status="submitted",
            **{source: {field: "MiXeD-SeArCh-NeEdLe"}},
        )
        for group in groups
    ]
    session.add_all(matches)
    await session.flush()
    user = User(
        id=user_id,
        agency_id=agency_id,
        full_name="Staff",
        email="staff@example.test",
        hashed_password="unused",
        role=UserRole.AGENCY_STAFF,
    )
    return user, matches[0]


@pytest.mark.parametrize("source", ["extracted_fields", "confirmed_fields"])
@pytest.mark.parametrize("field", ["passport_number", "surname", "given_names"])
async def test_global_search_executes_json_text_queries_and_preserves_staff_tenant_scope(
    db_session,
    source: str,
    field: str,
) -> None:
    user, expected = await _seed_search_scope(db_session, source, field)
    results = await global_search(
        q="  mixed-SEARCH-needle  ", limit=12, current_user=user, session=db_session
    )
    assert [result.id for result in results] == [expected.id]
    # The reported live crash also occurred on a plain client-name query:
    # every OR operand must compile even when JSON itself is not searched.
    results = await global_search(
        q="Browser Passenger 1", limit=12, current_user=user, session=db_session
    )
    assert [result.id for result in results] == [expected.id]


@pytest.mark.parametrize("source", ["extracted_fields", "confirmed_fields"])
@pytest.mark.parametrize("field", ["passport_number", "surname"])
async def test_group_passport_repository_executes_shared_json_search(
    db_session,
    source: str,
    field: str,
) -> None:
    user, expected = await _seed_search_scope(db_session, source, field)
    results = await PassportSubmissionRepository(db_session).list_by_group(
        agency_id=user.agency_id,
        group_id=expected.group_id,
        search="MiXeD-SeArCh-NeEdLe",
        visible_to_user=user,
    )
    assert [result.id for result in results] == [expected.id]
