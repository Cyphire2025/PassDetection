from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.routing import APIRoute

from app.application.my_photos.errors import MyPhotosUnavailable
from app.presentation.api.v1.router import api_v1_router
from app.presentation.api.v1.routes.mobile_my_photos import (
    _authorize,
    _dispatch_committed_job,
    router,
)


def test_my_photos_route_family_is_registered_on_the_mobile_api() -> None:
    routes = [
        route
        for route in api_v1_router.routes
        if (
            isinstance(route, APIRoute)
            and route.path.startswith("/mobile/")
            and "/my-photos" in route.path
        )
    ]
    method_paths = {
        (method, route.path)
        for route in routes
        for method in route.methods
        if method != "HEAD"
    }

    assert ("GET", "/mobile/trips/{group_id}/my-photos") in method_paths
    assert (
        "POST",
        "/mobile/trips/{group_id}/my-photos/liveness-sessions",
    ) in method_paths
    assert ("GET", "/mobile/trips/{group_id}/my-photos/photos") in method_paths
    assert (
        "POST",
        "/mobile/trips/{group_id}/my-photos/download-authorizations",
    ) in method_paths
    assert ("DELETE", "/mobile/trips/{group_id}/my-photos/enrollment") in method_paths
    assert len(routes) == 13


def test_post_commit_publish_failure_is_recovered_without_raising_500() -> None:
    job_id = uuid.uuid4()
    publish = Mock(side_effect=ConnectionError("broker unavailable"))
    with (
        patch(
            "app.presentation.api.v1.routes.mobile_my_photos."
            "my_photos_metrics.dispatch"
        ) as metric,
        patch(
            "app.presentation.api.v1.routes.mobile_my_photos.logger.warning"
        ) as warning,
    ):
        _dispatch_committed_job(
            kind="search",
            job_id=job_id,
            dispatch=publish,
        )

    publish.assert_called_once_with(job_id)
    metric.assert_called_once_with("recovery_pending")
    warning.assert_called_once_with(
        "my_photos_dispatch_deferred_to_recovery",
        job_kind="search",
        error_type="ConnectionError",
    )


def test_successful_post_commit_publish_is_observable() -> None:
    publish = Mock()
    with patch(
        "app.presentation.api.v1.routes.mobile_my_photos."
        "my_photos_metrics.dispatch"
    ) as metric:
        _dispatch_committed_job(
            kind="media",
            job_id=uuid.uuid4(),
            dispatch=publish,
        )

    metric.assert_called_once_with("published")


def test_durable_job_acceptance_routes_advertise_202() -> None:
    status_by_path = {
        route.path: route.status_code
        for route in router.routes
        if isinstance(route, APIRoute)
    }
    assert (
        status_by_path[
            "/trips/{group_id}/my-photos/liveness-sessions/{session_id}/complete"
        ]
        == 202
    )
    assert (
        status_by_path[
            "/trips/{group_id}/my-photos/photos/{asset_id}/prepare"
        ]
        == 202
    )


@pytest.mark.asyncio
async def test_non_summary_authorization_denies_disabled_feature_before_service_work() -> None:
    agency_id, group_id = uuid.uuid4(), uuid.uuid4()
    trip = SimpleNamespace(
        access=SimpleNamespace(id=uuid.uuid4()),
        passenger_identity=SimpleNamespace(id=uuid.uuid4()),
    )
    claims = SimpleNamespace(agency_id=agency_id, principal_type="passenger")
    session = SimpleNamespace(scalar=AsyncMock(return_value=False))
    require_trip_access = AsyncMock(return_value=trip)

    with patch(
        "app.presentation.api.v1.routes.mobile_my_photos.MobileAccessPolicy"
    ) as policy:
        policy.return_value.require_trip_access = require_trip_access
        with pytest.raises(MyPhotosUnavailable) as captured:
            await _authorize(
                group_id=group_id,
                claims=claims,  # type: ignore[arg-type]
                session=session,  # type: ignore[arg-type]
            )

    assert captured.value.code == "MY_PHOTOS_FEATURE_UNAVAILABLE"
    session.scalar.assert_awaited_once()


@pytest.mark.asyncio
async def test_summary_authorization_can_read_authoritative_disabled_capability() -> None:
    trip = SimpleNamespace(
        access=SimpleNamespace(id=uuid.uuid4()),
        passenger_identity=SimpleNamespace(id=uuid.uuid4()),
    )
    claims = SimpleNamespace(agency_id=uuid.uuid4(), principal_type="passenger")
    session = SimpleNamespace(scalar=AsyncMock())

    with patch(
        "app.presentation.api.v1.routes.mobile_my_photos.MobileAccessPolicy"
    ) as policy:
        policy.return_value.require_trip_access = AsyncMock(return_value=trip)
        authorized = await _authorize(
            group_id=uuid.uuid4(),
            claims=claims,  # type: ignore[arg-type]
            session=session,  # type: ignore[arg-type]
            allow_disabled_feature=True,
        )

    assert authorized.trip is trip
    session.scalar.assert_not_awaited()
