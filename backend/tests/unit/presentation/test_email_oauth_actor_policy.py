"""The actual initial OAuth eligibility SQL retains its role/agency boundary."""

from __future__ import annotations

import uuid

import pytest

from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import AgencyModel, UserModel
from app.presentation.api.v1.routes.email_oauth_actor import _oauth_actor_is_authorized


@pytest.mark.parametrize(
    ("role", "active_user", "active_agency", "same_agency", "allowed"),
    [
        (UserRole.SUPER_ADMIN, True, False, False, True),
        (UserRole.SUPER_ADMIN, False, True, True, False),
        (UserRole.AGENCY_ADMIN, True, True, True, True),
        (UserRole.AGENCY_MANAGER, True, True, True, True),
        (UserRole.AGENCY_STAFF, True, True, True, True),
        (UserRole.AGENCY_COORDINATOR, True, True, True, False),
        (UserRole.CLIENT_MANAGER, True, True, True, False),
        (UserRole.AGENCY_ADMIN, True, False, True, False),
        (UserRole.AGENCY_STAFF, False, True, True, False),
        (UserRole.AGENCY_STAFF, True, True, False, False),
    ],
)
async def test_initial_actor_query_preserves_live_role_and_agency_predicates(
    db_session, role, active_user, active_agency, same_agency, allowed
):
    agency = uuid.uuid4()
    db_session.add(
        AgencyModel(
            id=agency, name="Synthetic agency", email="agency@example.test", is_active=active_agency
        )
    )
    await db_session.flush()
    user = UserModel(
        id=uuid.uuid4(),
        email="owner@example.test",
        full_name="Owner",
        hashed_password="unused",
        role=role.value,
        is_active=active_user,
        agency_id=agency,
    )
    db_session.add(user)
    await db_session.flush()
    assert (
        await _oauth_actor_is_authorized(
            db_session, user_id=user.id, agency_id=agency if same_agency else uuid.uuid4()
        )
        is allowed
    )


async def test_missing_initial_actor_is_not_eligible(db_session):
    assert not await _oauth_actor_is_authorized(
        db_session, user_id=uuid.uuid4(), agency_id=uuid.uuid4()
    )
