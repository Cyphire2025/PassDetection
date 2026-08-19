from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.realtime_authorization import (
    load_mobile_realtime_authorization,
)
from app.core.security.mobile_jwt import MobileAccessClaims
from app.infrastructure.database.gc_mobile_models import GCGroupAccessModel
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
    UserModel,
)


@pytest.mark.asyncio
async def test_authorization_is_tenant_scoped_and_live_revocation_removes_trip(
    db_session: AsyncSession,
) -> None:
    agency_id = uuid.uuid4()
    other_agency_id = uuid.uuid4()
    principal_id = uuid.uuid4()
    allowed_group_id = uuid.uuid4()
    cross_tenant_group_id = uuid.uuid4()
    db_session.add_all(
        [
            AgencyModel(
                id=agency_id,
                name="Allowed agency",
                email=f"{agency_id}@example.test",
            ),
            AgencyModel(
                id=other_agency_id,
                name="Other agency",
                email=f"{other_agency_id}@example.test",
            ),
            UserModel(
                id=principal_id,
                email=f"{principal_id}@example.test",
                hashed_password="not-used",
                full_name="Coordinator",
                role="agency_coordinator",
                agency_id=agency_id,
            ),
            ClientGroupModel(
                id=allowed_group_id,
                name="Allowed group",
                token=f"allowed-{allowed_group_id}",
                agency_id=agency_id,
                status="active",
            ),
            ClientGroupModel(
                id=cross_tenant_group_id,
                name="Other group",
                token=f"other-{cross_tenant_group_id}",
                agency_id=other_agency_id,
                status="active",
            ),
        ]
    )
    await db_session.flush()
    allowed_access = GCGroupAccessModel(
        agency_id=agency_id,
        group_id=allowed_group_id,
        is_enabled=True,
        coordinator_access_enabled=True,
    )
    cross_tenant_access = GCGroupAccessModel(
        agency_id=other_agency_id,
        group_id=cross_tenant_group_id,
        is_enabled=True,
        coordinator_access_enabled=True,
    )
    db_session.add_all([allowed_access, cross_tenant_access])
    await db_session.flush()
    db_session.add_all(
        [
            CoordinatorGroupAssignmentModel(
                agency_id=agency_id,
                group_id=allowed_group_id,
                coordinator_user_id=principal_id,
                active=True,
            ),
            CoordinatorGroupAssignmentModel(
                agency_id=other_agency_id,
                group_id=cross_tenant_group_id,
                coordinator_user_id=principal_id,
                active=True,
            ),
        ]
    )
    await db_session.flush()
    claims = MobileAccessClaims(
        principal_id=principal_id,
        account_id=principal_id,
        principal_type="coordinator",
        agency_id=agency_id,
        session_id=uuid.uuid4(),
        session_generation=1,
        password_change_required=False,
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=5),
    )

    authorization = await load_mobile_realtime_authorization(
        db_session,
        claims,
        maximum_trips=10,
    )
    assert authorization.trip_ids == frozenset({allowed_group_id})
    assert cross_tenant_group_id not in authorization.trip_ids

    allowed_access.revoked_at = datetime.now(tz=UTC)
    await db_session.flush()
    revoked = await load_mobile_realtime_authorization(
        db_session,
        claims,
        maximum_trips=10,
    )
    assert revoked.trip_ids == frozenset()
