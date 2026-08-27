from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dashboard_realtime_authorization import (
    load_dashboard_realtime_authorization,
    parse_dashboard_realtime_claims,
)
from app.core.security.jwt import create_access_token
from app.domain.exceptions.exceptions import AuthenticationError, AuthorizationError
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
    ManagerGroupAccessModel,
    UserModel,
    UserSecurityStateModel,
)


def _token(
    user_id: uuid.UUID,
    agency_id: uuid.UUID | None,
    *,
    role: str,
    session_version: int = 1,
) -> str:
    token, _ = create_access_token(
        user_id,
        role,
        agency_id,
        session_version=session_version,
    )
    return token


def test_claim_parser_rejects_non_tenant_dashboard_roles() -> None:
    user_id = uuid.uuid4()
    with pytest.raises(AuthorizationError):
        parse_dashboard_realtime_claims(
            _token(user_id, None, role="super_admin")
        )
    with pytest.raises(AuthorizationError):
        parse_dashboard_realtime_claims(
            _token(user_id, uuid.uuid4(), role="client_manager")
        )


@pytest.mark.asyncio
async def test_staff_snapshot_is_tenant_scoped_and_fenced_by_session_epoch(
    db_session: AsyncSession,
) -> None:
    agency_id = uuid.uuid4()
    other_agency_id = uuid.uuid4()
    user_id = uuid.uuid4()
    owned_id = uuid.uuid4()
    assigned_id = uuid.uuid4()
    hidden_id = uuid.uuid4()
    archived_id = uuid.uuid4()
    other_tenant_id = uuid.uuid4()
    db_session.add_all(
        [
            AgencyModel(
                id=agency_id,
                name="Realtime agency",
                email=f"{agency_id}@example.test",
            ),
            AgencyModel(
                id=other_agency_id,
                name="Other agency",
                email=f"{other_agency_id}@example.test",
            ),
            UserModel(
                id=user_id,
                email=f"{user_id}@example.test",
                hashed_password="not-used",
                full_name="Scoped staff",
                role="agency_staff",
                agency_id=agency_id,
            ),
            UserSecurityStateModel(
                user_id=user_id,
                credential_state="active",
                session_version=3,
            ),
            ClientGroupModel(
                id=owned_id,
                name="Owned",
                token=f"owned-{owned_id}",
                agency_id=agency_id,
                status="active",
                created_by_user_id=user_id,
            ),
            ClientGroupModel(
                id=assigned_id,
                name="Assigned",
                token=f"assigned-{assigned_id}",
                agency_id=agency_id,
                status="closed",
            ),
            ClientGroupModel(
                id=hidden_id,
                name="Hidden",
                token=f"hidden-{hidden_id}",
                agency_id=agency_id,
                status="active",
            ),
            ClientGroupModel(
                id=archived_id,
                name="Archived",
                token=f"archived-{archived_id}",
                agency_id=agency_id,
                status="archived",
                created_by_user_id=user_id,
            ),
            ClientGroupModel(
                id=other_tenant_id,
                name="Other tenant",
                token=f"other-{other_tenant_id}",
                agency_id=other_agency_id,
                status="active",
                created_by_user_id=user_id,
            ),
        ]
    )
    await db_session.flush()
    db_session.add(
        ManagerGroupAccessModel(
            manager_id=user_id,
            group_id=assigned_id,
            agency_id=agency_id,
        )
    )
    await db_session.flush()

    token = _token(
        user_id,
        agency_id,
        role="agency_staff",
        session_version=3,
    )
    authorization = await load_dashboard_realtime_authorization(
        db_session,
        token,
        maximum_trips=10,
    )
    assert authorization.principal_type == "dashboard"
    assert authorization.agency_id == agency_id
    assert authorization.session_generation == 3
    assert authorization.trip_ids == frozenset({owned_id, assigned_id})

    security_state = await db_session.get(UserSecurityStateModel, user_id)
    assert security_state is not None
    security_state.session_version = 4
    await db_session.flush()
    with pytest.raises(AuthenticationError, match="Session is no longer valid"):
        await load_dashboard_realtime_authorization(
            db_session,
            token,
            maximum_trips=10,
        )


@pytest.mark.asyncio
async def test_coordinator_snapshot_uses_only_live_tenant_assignments(
    db_session: AsyncSession,
) -> None:
    agency_id = uuid.uuid4()
    user_id = uuid.uuid4()
    assigned_id = uuid.uuid4()
    unassigned_id = uuid.uuid4()
    db_session.add_all(
        [
            AgencyModel(
                id=agency_id,
                name="Coordinator agency",
                email=f"{agency_id}@example.test",
            ),
            UserModel(
                id=user_id,
                email=f"{user_id}@example.test",
                hashed_password="not-used",
                full_name="Coordinator",
                role="agency_coordinator",
                agency_id=agency_id,
            ),
            ClientGroupModel(
                id=assigned_id,
                name="Assigned",
                token=f"assigned-{assigned_id}",
                agency_id=agency_id,
                status="active",
            ),
            ClientGroupModel(
                id=unassigned_id,
                name="Unassigned",
                token=f"unassigned-{unassigned_id}",
                agency_id=agency_id,
                status="active",
            ),
        ]
    )
    await db_session.flush()
    db_session.add_all(
        [
            CoordinatorGroupAssignmentModel(
                agency_id=agency_id,
                group_id=assigned_id,
                coordinator_user_id=user_id,
                active=True,
            ),
            CoordinatorGroupAssignmentModel(
                agency_id=agency_id,
                group_id=unassigned_id,
                coordinator_user_id=user_id,
                active=False,
            ),
        ]
    )
    await db_session.flush()

    token = _token(user_id, agency_id, role="agency_coordinator")
    authorization = await load_dashboard_realtime_authorization(
        db_session,
        token,
        maximum_trips=10,
    )
    assert authorization.trip_ids == frozenset({assigned_id})

    with pytest.raises(AuthorizationError, match="trip limit"):
        await load_dashboard_realtime_authorization(
            db_session,
            token,
            maximum_trips=0,
        )
