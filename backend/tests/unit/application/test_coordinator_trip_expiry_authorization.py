from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application import dashboard_realtime_authorization
from app.application.mobile import realtime_authorization
from app.application.security import authorization_policy, mobile_access_policy
from app.core.security.jwt import create_access_token
from app.core.security.mobile_jwt import MobileAccessClaims
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.gc_mobile_models import GCGroupAccessModel
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    CoordinatorAssignmentModel,
    CoordinatorGroupAssignmentModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.repositories.coordinator_assignment_lifecycle import expired_trip_clause
from app.presentation.api.v1.routes import mobile_ops_notification_support, mobile_resources


@pytest.fixture
async def trip_assignments(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch):
    # This is precisely midnight in Kolkata; UTC groups still have their return day.
    now = datetime(2026, 9, 6, 18, 30, tzinfo=UTC)
    for module in (
        authorization_policy,
        mobile_access_policy,
        dashboard_realtime_authorization,
        realtime_authorization,
        mobile_resources,
        mobile_ops_notification_support,
    ):
        monkeypatch.setattr(module, "expired_trip_clause", lambda *_: expired_trip_clause(now))

    agency_id, coordinator_id = uuid.uuid4(), uuid.uuid4()
    db_session.add_all(
        [
            AgencyModel(id=agency_id, name="Expiry checks", email="expiry@example.test"),
            UserModel(
                id=coordinator_id,
                email="coordinator-expiry@example.test",
                hashed_password="not-used",
                full_name="Coordinator",
                role="agency_coordinator",
                agency_id=agency_id,
            ),
        ]
    )
    await db_session.flush()
    specs = (
        ("upcoming", date(2026, 9, 8), date(2026, 9, 10), "Asia/Kolkata", True, True),
        ("ongoing", date(2026, 9, 3), date(2026, 9, 8), "Asia/Kolkata", True, True),
        ("return_today_utc", date(2026, 9, 3), date(2026, 9, 6), "UTC", True, True),
        ("return_ended_india", date(2026, 9, 3), date(2026, 9, 6), "Asia/Kolkata", True, False),
        ("fallback_ended", date(2026, 9, 6), None, "Asia/Kolkata", True, False),
        ("fallback_today", date(2026, 9, 6), None, "UTC", True, True),
        ("undated_existing", None, None, "Asia/Kolkata", True, True),
        ("inactive_future", date(2026, 9, 8), date(2026, 9, 10), "UTC", False, False),
    )
    cases = []
    for name, departure, arrival, timezone, active, expected in specs:
        group = ClientGroupModel(
            id=uuid.uuid4(),
            name=name,
            token=f"expiry-{uuid.uuid4()}",
            agency_id=agency_id,
            status="active",
            travel_date=departure,
            return_date=arrival,
            timezone=timezone,
        )
        passport = PassportSubmissionModel(
            id=uuid.uuid4(),
            agency_id=agency_id,
            group_id=group.id,
            client_name="Test passenger",
            image_s3_key="test-only/not-a-real-object.jpg",
        )
        db_session.add_all([group, passport])
        await db_session.flush()
        group_assignment = CoordinatorGroupAssignmentModel(
            agency_id=agency_id,
            group_id=group.id,
            coordinator_user_id=coordinator_id,
            active=active,
        )
        db_session.add_all(
            [
                group_assignment,
                CoordinatorAssignmentModel(
                    agency_id=agency_id,
                    group_id=group.id,
                    passenger_id=passport.id,
                    coordinator_user_id=coordinator_id,
                    active=active,
                ),
                GCGroupAccessModel(
                    agency_id=agency_id,
                    group_id=group.id,
                    is_enabled=True,
                    coordinator_access_enabled=True,
                ),
            ]
        )
        cases.append((group, passport, group_assignment, expected))
    await db_session.flush()
    coordinator = User(
        id=coordinator_id,
        email="coordinator-expiry@example.test",
        hashed_password="not-used",
        full_name="Coordinator",
        role=UserRole.AGENCY_COORDINATOR,
        agency_id=agency_id,
    )
    return coordinator, cases


@pytest.mark.asyncio
async def test_request_time_expiry_fences_direct_and_list_access_without_waiting_for_worker(
    db_session: AsyncSession, trip_assignments,
) -> None:
    coordinator, cases = trip_assignments
    policy = authorization_policy.AuthorizationPolicy(db_session)
    for group, passport, assignment, expected in cases:
        assert await policy.can_view_group(coordinator, group) is expected, group.name
        assert await policy.can_view_passport(coordinator, passport) is expected, group.name
        attendance = SimpleNamespace(agency_id=group.agency_id, group_id=group.id)
        assert await policy.can_scan_passenger(coordinator, attendance, passport) is expected
        # Read-time authorization must not destroy historical assignment records.
        if group.name == "return_ended_india":
            assert assignment.active is True
            assert assignment.unassigned_at is None

    visible_groups = await db_session.scalars(
        policy.apply_group_visibility_scope(select(ClientGroupModel.id), coordinator)
    )
    visible_passports = await db_session.scalars(
        policy.apply_passport_visibility_scope(select(PassportSubmissionModel.id), coordinator)
    )
    assert set(visible_groups) == {group.id for group, _, _, expected in cases if expected}
    assert set(visible_passports) == {passport.id for _, passport, _, expected in cases if expected}

    for role in (UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER, UserRole.SUPER_ADMIN):
        office_user = User(
            id=uuid.uuid4(), email=f"{role}@example.test", hashed_password="unused",
            full_name="Office user", role=role, agency_id=coordinator.agency_id,
        )
        historical = next(group for group, _, _, _ in cases if group.name == "return_ended_india")
        assert await policy.can_view_group(office_user, historical) is True
        office_groups = await db_session.scalars(
            policy.apply_group_visibility_scope(select(ClientGroupModel.id), office_user)
        )
        assert set(office_groups) == {group.id for group, _, _, _ in cases}


@pytest.mark.asyncio
async def test_mobile_and_realtime_share_trip_expiry_and_keep_current_assignments(
    db_session: AsyncSession, trip_assignments,
) -> None:
    coordinator, cases = trip_assignments
    expected_ids = {group.id for group, _, _, expected in cases if expected}
    claims = MobileAccessClaims(
        principal_id=coordinator.id,
        account_id=coordinator.id,
        principal_type="coordinator",
        agency_id=coordinator.agency_id,
        session_id=uuid.uuid4(),
        session_generation=1,
        password_change_required=False,
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=5),
    )
    policy = mobile_access_policy.MobileAccessPolicy(db_session)
    for group, _, _, expected in cases:
        if expected:
            assert (await policy.require_trip_access(claims, group.id)).group.id == group.id
        else:
            with pytest.raises(AuthorizationError, match="not available"):
                await policy.require_trip_access(claims, group.id)

    trips = await mobile_resources.list_mobile_trips(
        cursor=None, limit=50, claims=claims, session=db_session,
    )
    assert {trip.id for trip in trips.items} == expected_ids
    notification_ids = await db_session.scalars(
        select(ClientGroupModel.id).where(
            ClientGroupModel.id.in_(mobile_ops_notification_support._accessible_group_ids(
                claims, datetime.now(tz=UTC),
            ))
        )
    )
    assert set(notification_ids) == expected_ids
    mobile_live = await realtime_authorization.load_mobile_realtime_authorization(
        db_session, claims, maximum_trips=20,
    )
    assert mobile_live.trip_ids == expected_ids
    token, _ = create_access_token(coordinator.id, coordinator.role.value, coordinator.agency_id)
    dashboard_live = await dashboard_realtime_authorization.load_dashboard_realtime_authorization(
        db_session, token, maximum_trips=20,
    )
    assert dashboard_live.trip_ids == expected_ids
