from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql
from starlette.requests import Request

from app.presentation.api.v1.routes.rooming import router as rooming_router
from app.presentation.api.v1.routes.tour_operations import (
    get_my_group_passenger_detail,
)
from app.presentation.api.v1.routes.tour_operations import (
    router as tour_operations_router,
)
from app.presentation.api.v1.routes.tour_operations_qr_delivery import (
    router as qr_delivery_router,
)
from app.presentation.dependencies.csrf import require_cookie_csrf

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value

    def scalar_one(self) -> object:
        return self._value


def _route(router: object, path: str, method: str) -> object:
    return next(
        route
        for route in router.routes  # type: ignore[attr-defined]
        if route.path == path and method in route.methods
    )


def _has_csrf_dependency(route: object) -> bool:
    return any(
        dependency.call is require_cookie_csrf
        for dependency in route.dependant.dependencies  # type: ignore[attr-defined]
    )


def _request(*, headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "https",
            "server": ("api.example.test", 443),
            "path": "/api/v1/tour-operations/coordinators",
            "query_string": b"",
            "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
        }
    )


def test_every_tour_operations_mutation_requires_cookie_csrf() -> None:
    guarded_routes = {
        (method, route.path)
        for route in tour_operations_router.routes
        for method in route.methods & MUTATING_METHODS
        if _has_csrf_dependency(route)
    }
    all_mutations = {
        (method, route.path)
        for route in tour_operations_router.routes
        for method in route.methods & MUTATING_METHODS
    }

    assert guarded_routes == all_mutations
    assert len(guarded_routes) == 11


def test_qr_delivery_and_hotel_checkin_mutations_require_cookie_csrf() -> None:
    qr_send = _route(
        qr_delivery_router,
        "/groups/{group_id}/qr-codes/whatsapp-send",
        "POST",
    )
    hotel_scan = _route(
        rooming_router,
        "/hotels/{hotel_id}/check-ins/scan",
        "POST",
    )
    hotel_update = _route(rooming_router, "/check-ins/{checkin_id}", "PATCH")

    assert _has_csrf_dependency(qr_send)
    assert _has_csrf_dependency(hotel_scan)
    assert _has_csrf_dependency(hotel_update)


@pytest.mark.asyncio
async def test_bound_tour_operations_csrf_guard_rejects_cross_site_cookie_and_allows_bearer() -> (
    None
):
    create_route = _route(tour_operations_router, "/coordinators", "POST")
    csrf_guard = next(
        dependency.call
        for dependency in create_route.dependant.dependencies
        if dependency.call is require_cookie_csrf
    )
    settings = SimpleNamespace(
        allowed_origins=["https://office.example.test"],
        jwt=SimpleNamespace(access_cookie_name="access_token"),
    )

    with patch(
        "app.presentation.dependencies.csrf.get_settings",
        return_value=settings,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await csrf_guard(
                _request(
                    headers={
                        "Cookie": "access_token=cookie-token",
                        "Origin": "https://evil.example.test",
                    }
                )
            )
        await csrf_guard(
            _request(
                headers={
                    "Authorization": "Bearer api-token",
                    "Cookie": "access_token=cookie-token",
                    "Origin": "https://evil.example.test",
                }
            )
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Cross-site request validation failed."


@pytest.mark.asyncio
async def test_passenger_detail_counts_family_within_agency_group_and_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    passenger_id = uuid.uuid4()
    family_group_id = uuid.uuid4()
    timestamp = datetime.now(tz=UTC)
    passenger = SimpleNamespace(
        id=passenger_id,
        client_name="Family Member",
        client_email="member@example.test",
        client_phone="+919000000000",
        departure_city="Delhi",
        submission_mode="family",
        family_group_id=family_group_id,
        family_member_index=2,
        family_relation="Child",
        family_gender="Female",
        family_head_name="Family Head",
        status="confirmed",
        created_at=timestamp,
        updated_at=timestamp,
        client_reviewed_at=None,
        confirmed_at=timestamp,
        confirmed_fields={"passport_number": "P1234567"},
        extracted_fields={},
        overall_confidence=0.99,
    )
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _ScalarResult(passenger),
                _ScalarResult(3),
            ]
        )
    )
    ensure_assignment = AsyncMock()
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.tour_operations._ensure_group_assigned_to_coordinator",
        ensure_assignment,
    )

    response = await get_my_group_passenger_detail(
        group_id=group_id,
        passenger_id=passenger_id,
        current_user=SimpleNamespace(id=uuid.uuid4(), agency_id=agency_id),
        session=session,  # type: ignore[arg-type]
    )

    family_count_statement = session.execute.await_args_list[1].args[0]
    compiled = family_count_statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "passport_submissions.agency_id" in sql
    assert "passport_submissions.group_id" in sql
    assert "passport_submissions.family_group_id" in sql
    assert "passport_submissions.status" in sql
    assert agency_id in compiled.params.values()
    assert group_id in compiled.params.values()
    assert family_group_id in compiled.params.values()
    assert response.family_size == 3
    assert response.family_group_label == "Family Head Family (3)"
    ensure_assignment.assert_awaited_once()
