from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Response
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app.application.mobile.journey_destination import (
    JourneyDestination,
    MobileJourneyDestinationResponse,
)
from app.core.security.mobile_jwt import MobileAccessClaims, MobilePrincipalType
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes import mobile_journey
from app.presentation.dependencies.mobile_auth import require_unrestricted_mobile_claims


def _claims(role: MobilePrincipalType = "passenger") -> MobileAccessClaims:
    principal_id = uuid.uuid4()
    return MobileAccessClaims(
        principal_id=principal_id,
        account_id=principal_id,
        principal_type=role,
        agency_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        session_generation=1,
        password_change_required=False,
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
    )


def _resolved_destination() -> MobileJourneyDestinationResponse:
    return MobileJourneyDestinationResponse(
        status="resolved",
        destination=JourneyDestination(
            label="Tokyo, Japan",
            country="Japan",
            country_code="JP",
            latitude=35.6762,
            longitude=139.6503,
            place_type="city",
        ),
    )


def _journey_route() -> APIRoute:
    routes = [route for route in mobile_journey.router.routes if isinstance(route, APIRoute)]
    assert len(routes) == 1
    return routes[0]


def test_journey_destination_route_accepts_only_the_trip_locator() -> None:
    route = _journey_route()

    assert route.path == "/trips/{group_id}/journey-destination"
    assert route.methods == {"GET"}
    assert [parameter.name for parameter in route.dependant.path_params] == ["group_id"]
    assert route.dependant.query_params == []
    assert route.dependant.body_params == []


@pytest.mark.asyncio
async def test_journey_destination_denies_trip_before_releasing_or_resolving() -> None:
    claims = _claims()
    group_id = uuid.uuid4()
    session = SimpleNamespace(rollback=AsyncMock())
    resolver = SimpleNamespace(resolve=AsyncMock())
    authorize = AsyncMock(side_effect=AuthorizationError("Mobile trip access is not available"))

    with (
        patch.object(mobile_journey.MobileAccessPolicy, "require_trip_access", new=authorize),
        pytest.raises(AuthorizationError, match="trip access"),
    ):
        await mobile_journey.get_mobile_journey_destination(
            group_id=group_id,
            response=Response(),
            claims=claims,
            session=session,
            resolver=resolver,
        )

    authorize.assert_awaited_once_with(claims, group_id)
    session.rollback.assert_not_awaited()
    resolver.resolve.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["passenger", "client_manager", "coordinator"])
async def test_journey_destination_resolves_saved_trip_after_releasing_transaction(
    role: MobilePrincipalType,
) -> None:
    claims = _claims(role)
    group_id = uuid.uuid4()
    group = SimpleNamespace(destination="Tokyo, Japan")
    trip = SimpleNamespace(group=group)
    expected = _resolved_destination()
    authorize = AsyncMock(return_value=trip)
    events: list[str] = []

    async def rollback() -> None:
        events.append("rollback")
        # ORM rollback expires loaded attributes; the route must preserve the
        # authorized value before leaving the database transaction.
        del group.destination

    async def resolve(destination: str | None) -> MobileJourneyDestinationResponse:
        assert events == ["rollback"]
        events.append("resolve")
        assert destination == "Tokyo, Japan"
        return expected

    session = SimpleNamespace(rollback=AsyncMock(side_effect=rollback))
    resolver = SimpleNamespace(resolve=AsyncMock(side_effect=resolve))
    response = Response()

    with patch.object(mobile_journey.MobileAccessPolicy, "require_trip_access", new=authorize):
        result = await mobile_journey.get_mobile_journey_destination(
            group_id=group_id,
            response=response,
            claims=claims,
            session=session,
            resolver=resolver,
        )

    authorize.assert_awaited_once_with(claims, group_id)
    session.rollback.assert_awaited_once_with()
    resolver.resolve.assert_awaited_once_with("Tokyo, Japan")
    assert events == ["rollback", "resolve"]
    assert result == expected
    assert {value.strip() for value in response.headers["cache-control"].split(",")} == {
        "private",
        "no-store",
    }


@pytest.mark.asyncio
async def test_journey_destination_keeps_missing_saved_destination() -> None:
    trip = SimpleNamespace(group=SimpleNamespace(destination=None))
    session = SimpleNamespace(rollback=AsyncMock())
    expected = MobileJourneyDestinationResponse(status="not_found")
    resolver = SimpleNamespace(resolve=AsyncMock(return_value=expected))

    with patch.object(
        mobile_journey.MobileAccessPolicy,
        "require_trip_access",
        new=AsyncMock(return_value=trip),
    ):
        result = await mobile_journey.get_mobile_journey_destination(
            group_id=uuid.uuid4(),
            response=Response(),
            claims=_claims(),
            session=session,
            resolver=resolver,
        )

    resolver.resolve.assert_awaited_once_with(None)
    assert result == expected


@pytest.mark.asyncio
async def test_http_query_cannot_replace_authorized_saved_destination() -> None:
    claims = _claims()
    group_id = uuid.uuid4()
    trip = SimpleNamespace(group=SimpleNamespace(destination="Tokyo, Japan"))
    session = SimpleNamespace(rollback=AsyncMock())
    resolver = SimpleNamespace(resolve=AsyncMock(return_value=_resolved_destination()))
    authorize = AsyncMock(return_value=trip)
    app = FastAPI()
    app.include_router(mobile_journey.router, prefix="/mobile")
    app.dependency_overrides[require_unrestricted_mobile_claims] = lambda: claims
    app.dependency_overrides[get_db_session] = lambda: session
    app.dependency_overrides[mobile_journey.get_mobile_journey_geocoder] = lambda: resolver

    with patch.object(mobile_journey.MobileAccessPolicy, "require_trip_access", new=authorize):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.get(
                f"/mobile/trips/{group_id}/journey-destination",
                params={"destination": "Attacker supplied destination"},
            )

    assert response.status_code == 200
    assert response.json()["destination"]["label"] == "Tokyo, Japan"
    assert {value.strip() for value in response.headers["cache-control"].split(",")} == {
        "private",
        "no-store",
    }
    authorize.assert_awaited_once_with(claims, group_id)
    session.rollback.assert_awaited_once_with()
    resolver.resolve.assert_awaited_once_with("Tokyo, Japan")
