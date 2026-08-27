from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.routing import APIWebSocketRoute
from starlette.websockets import WebSocketState

from app.application.mobile.realtime_authorization import MobileRealtimeAuthorization
from app.application.mobile.realtime_hints import MobileRealtimeHint
from app.core.config.settings import Settings
from app.infrastructure.mobile_realtime import MobileRealtimeConnection
from app.presentation.api.v1.router import api_v1_router
from app.presentation.api.v1.routes import dashboard_realtime as realtime_route
from app.presentation.api.v1.routes.dashboard_realtime import (
    _dashboard_access_cookie,
    _dashboard_origin_allowed,
    router,
)
from app.presentation.api.v1.routes.realtime_socket_support import (
    MAX_SERVER_FRAME_BYTES,
    RealtimeSocketClose,
    send_bounded_realtime_json,
)


def _settings() -> Settings:
    return Settings(
        app_secret_key="dashboard-realtime-test-secret",
        allowed_origins=["https://app.example.test"],
        _env_file=None,
    )


def test_dashboard_realtime_is_registered_on_one_exact_websocket_path() -> None:
    assert {route.path for route in router.routes} == {"/realtime"}
    paths = {
        route.path
        for route in api_v1_router.routes
        if isinstance(route, APIWebSocketRoute)
    }
    assert "/dashboard/realtime" in paths
    assert "/mobile/realtime" in paths


def test_dashboard_origin_requires_allowlisted_same_authority() -> None:
    allowed = SimpleNamespace(
        headers={
            "origin": "https://app.example.test",
            "host": "app.example.test",
        },
        url=SimpleNamespace(netloc="internal-backend:8000"),
    )
    missing = SimpleNamespace(
        headers={"host": "app.example.test"},
        url=SimpleNamespace(netloc="app.example.test"),
    )
    cross_host = SimpleNamespace(
        headers={
            "origin": "https://app.example.test",
            "host": "api.example.test",
        },
        url=SimpleNamespace(netloc="api.example.test"),
    )
    path_bearing = SimpleNamespace(
        headers={
            "origin": "https://app.example.test/forbidden",
            "host": "app.example.test",
        },
        url=SimpleNamespace(netloc="app.example.test"),
    )
    assert _dashboard_origin_allowed(allowed, _settings()) is True  # type: ignore[arg-type]
    assert _dashboard_origin_allowed(missing, _settings()) is False  # type: ignore[arg-type]
    assert _dashboard_origin_allowed(cross_host, _settings()) is False  # type: ignore[arg-type]
    assert _dashboard_origin_allowed(path_bearing, _settings()) is False  # type: ignore[arg-type]


def test_dashboard_auth_accepts_only_bounded_cookie_without_query_or_bearer() -> None:
    valid = SimpleNamespace(
        query_params={},
        headers={"cookie": "access_token=cookie-token"},
        cookies={"access_token": "cookie-token"},
    )
    bearer = SimpleNamespace(
        query_params={},
        headers={"authorization": "Bearer copied-token"},
        cookies={"access_token": "cookie-token"},
    )
    query = SimpleNamespace(
        query_params={"token": "leaked"},
        headers={"cookie": "access_token=cookie-token"},
        cookies={"access_token": "cookie-token"},
    )
    oversized = SimpleNamespace(
        query_params={},
        headers={"cookie": "x=" + ("a" * 17_000)},
        cookies={"access_token": "cookie-token"},
    )
    assert _dashboard_access_cookie(valid, _settings()) == "cookie-token"  # type: ignore[arg-type]
    assert _dashboard_access_cookie(bearer, _settings()) is None  # type: ignore[arg-type]
    assert _dashboard_access_cookie(query, _settings()) is None  # type: ignore[arg-type]
    assert _dashboard_access_cookie(oversized, _settings()) is None  # type: ignore[arg-type]


def test_invalidation_event_schema_is_pii_free_and_under_one_kibibyte() -> None:
    hint = MobileRealtimeHint(
        agency_id=uuid.uuid4(),
        trip_id=uuid.uuid4(),
        cursor=(1 << 63) - 1,
        invalidation="attendance",
    )
    payload = hint.client_payload()
    assert set(payload) == {"type", "trip_id", "cursor", "invalidation"}
    assert payload["type"] == "sync_hint"
    assert payload["invalidation"] == "attendance"
    assert len(str(payload).encode("utf-8")) < MAX_SERVER_FRAME_BYTES
    for forbidden in (
        "agency_id",
        "account_id",
        "principal_id",
        "passenger_id",
        "name",
        "email",
        "phone",
        "token",
    ):
        assert forbidden not in payload


@pytest.mark.asyncio
async def test_server_frame_guard_rejects_payload_over_one_kibibyte() -> None:
    class _Socket:
        def __init__(self) -> None:
            self.sent = False

        async def send_json(self, _payload: dict[str, str | int]) -> None:
            self.sent = True

    socket = _Socket()
    with pytest.raises(RealtimeSocketClose) as closed:
        await send_bounded_realtime_json(
            socket,  # type: ignore[arg-type]
            {"type": "sync_hint", "trip_id": "x" * MAX_SERVER_FRAME_BYTES},
        )
    assert closed.value.code == 1011
    assert socket.sent is False


@pytest.mark.asyncio
async def test_cookie_authenticated_socket_registers_then_releases_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id = uuid.uuid4()
    authorization = MobileRealtimeAuthorization(
        agency_id=uuid.uuid4(),
        account_id=principal_id,
        principal_id=principal_id,
        principal_type="dashboard",
        session_id=uuid.uuid4(),
        session_generation=2,
        trip_ids=frozenset({uuid.uuid4()}),
    )
    connection = MobileRealtimeConnection(
        authorization=authorization,
        maximum_pending_trips=4,
    )

    async def authorize(token: str, *, maximum_trips: int) -> MobileRealtimeAuthorization:
        assert token == "cookie-token"
        assert maximum_trips == 100
        return authorization

    monkeypatch.setattr(realtime_route, "authorize_dashboard_realtime", authorize)

    class _Hub:
        accepting_connections = True
        config = SimpleNamespace(
            max_trips_per_connection=100,
            heartbeat_seconds=20,
            idle_timeout_seconds=65,
            send_timeout_seconds=1.0,
            authorization_refresh_seconds=60,
        )

        def __init__(self) -> None:
            self.authenticating = 0
            self.registered = False
            self.unregistered = False

        async def begin_authorization(self) -> uuid.UUID:
            self.authenticating += 1
            return uuid.uuid4()

        async def end_authorization(self, _reservation_id: uuid.UUID) -> None:
            self.authenticating -= 1

        async def register(
            self,
            current: MobileRealtimeAuthorization,
        ) -> MobileRealtimeConnection:
            assert current == authorization
            self.registered = True
            return connection

        async def unregister(self, current: MobileRealtimeConnection) -> None:
            assert current is connection
            self.unregistered = True

    class _Socket:
        query_params: dict[str, str] = {}
        headers = {
            "origin": "https://app.example.test",
            "host": "app.example.test",
            "cookie": "access_token=cookie-token",
        }
        cookies = {"access_token": "cookie-token"}
        url = SimpleNamespace(netloc="app.example.test")

        def __init__(self) -> None:
            self.client_state = WebSocketState.CONNECTING
            self.closed_code: int | None = None
            self.frames: list[dict[str, str | int]] = []

        async def accept(self) -> None:
            self.client_state = WebSocketState.CONNECTED

        async def send_json(self, payload: dict[str, str | int]) -> None:
            self.frames.append(payload)

        async def receive_text(self) -> str:
            return '{"type":"not-an-ack"}'

        async def close(self, code: int) -> None:
            self.closed_code = code
            self.client_state = WebSocketState.DISCONNECTED

    hub = _Hub()
    socket = _Socket()
    await realtime_route.dashboard_realtime_socket(
        socket,  # type: ignore[arg-type]
        settings=_settings(),
        hub=hub,  # type: ignore[arg-type]
    )
    assert hub.registered is True
    assert hub.unregistered is True
    assert hub.authenticating == 0
    assert socket.closed_code == 1008
    assert socket.frames == [
        {
            "type": "ready",
            "heartbeat_seconds": 20,
            "idle_timeout_seconds": 65,
        }
    ]
