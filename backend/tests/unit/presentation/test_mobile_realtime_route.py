from __future__ import annotations

import asyncio
import contextlib
import uuid
from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketState

from app.application.mobile.realtime_authorization import MobileRealtimeAuthorization
from app.application.mobile.realtime_hints import MobileRealtimeHint
from app.core.config.settings import Settings
from app.domain.exceptions.exceptions import AuthenticationError
from app.infrastructure.mobile_realtime import MobileRealtimeConnection
from app.presentation.api.v1.routes import mobile_realtime as realtime_route
from app.presentation.api.v1.routes.mobile_realtime import (
    _bearer_token,
    _origin_allowed,
    _refresh_authorization,
    _SocketClose,
    _write_hints,
    router,
)


def test_realtime_route_is_websocket_only_and_separate_from_resource_router() -> None:
    assert {route.path for route in router.routes} == {"/realtime"}


def test_bearer_token_must_use_header_and_query_strings_are_rejected() -> None:
    header_socket = SimpleNamespace(
        query_params={},
        headers={"authorization": "Bearer header-token"},
    )
    query_socket = SimpleNamespace(
        query_params={"token": "url-token"},
        headers={"authorization": "Bearer header-token"},
    )
    assert _bearer_token(header_socket) == "header-token"  # type: ignore[arg-type]
    assert _bearer_token(query_socket) is None  # type: ignore[arg-type]


def test_browser_origin_must_match_explicit_allowlist_or_api_origin() -> None:
    settings = Settings(
        app_secret_key="unit-test-secret",
        allowed_origins=["https://app.example.com"],
        _env_file=None,
    )
    allowed = SimpleNamespace(
        headers={"origin": "https://app.example.com"},
        url=SimpleNamespace(scheme="wss", netloc="api.example.com"),
    )
    api_origin = SimpleNamespace(
        headers={"origin": "https://api.example.com"},
        url=SimpleNamespace(scheme="wss", netloc="api.example.com"),
    )
    rejected = SimpleNamespace(
        headers={"origin": "https://evil.example"},
        url=SimpleNamespace(scheme="wss", netloc="api.example.com"),
    )
    native = SimpleNamespace(
        headers={},
        url=SimpleNamespace(scheme="wss", netloc="api.example.com"),
    )
    assert _origin_allowed(allowed, settings) is True  # type: ignore[arg-type]
    assert _origin_allowed(api_origin, settings) is True  # type: ignore[arg-type]
    assert _origin_allowed(rejected, settings) is False  # type: ignore[arg-type]
    assert _origin_allowed(native, settings) is True  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_busy_hint_stream_cannot_starve_protocol_heartbeats() -> None:
    agency_id = uuid.uuid4()
    trip_id = uuid.uuid4()
    principal_id = uuid.uuid4()
    connection = MobileRealtimeConnection(
        authorization=MobileRealtimeAuthorization(
            agency_id=agency_id,
            account_id=principal_id,
            principal_id=principal_id,
            principal_type="coordinator",
            session_id=uuid.uuid4(),
            session_generation=1,
            trip_ids=frozenset({trip_id}),
        ),
        maximum_pending_trips=4,
    )
    cursor = 0
    heartbeat_seen = asyncio.Event()

    class _BusySocket:
        async def send_json(self, payload: dict[str, str | int]) -> None:
            nonlocal cursor
            if payload == {"type": "heartbeat"}:
                heartbeat_seen.set()
                return
            cursor += 1
            connection.offer(
                MobileRealtimeHint(
                    agency_id=agency_id,
                    trip_id=trip_id,
                    cursor=cursor,
                    invalidation="all",
                )
            )
            await asyncio.sleep(0.006)

    connection.offer(
        MobileRealtimeHint(
            agency_id=agency_id,
            trip_id=trip_id,
            cursor=1,
            invalidation="all",
        )
    )
    writer = asyncio.create_task(
        _write_hints(
            _BusySocket(),  # type: ignore[arg-type]
            connection,
            heartbeat_seconds=0.01,  # type: ignore[arg-type]
            send_timeout_seconds=0.1,
        )
    )
    try:
        await asyncio.wait_for(heartbeat_seen.wait(), timeout=0.2)
    finally:
        writer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await writer


@pytest.mark.asyncio
async def test_protocol_failure_always_unregisters_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id = uuid.uuid4()
    authorization = MobileRealtimeAuthorization(
        agency_id=uuid.uuid4(),
        account_id=principal_id,
        principal_id=principal_id,
        principal_type="coordinator",
        session_id=uuid.uuid4(),
        session_generation=1,
        trip_ids=frozenset({uuid.uuid4()}),
    )
    connection = MobileRealtimeConnection(
        authorization=authorization,
        maximum_pending_trips=4,
    )

    async def authorize(_token: str, *, maximum_trips: int) -> MobileRealtimeAuthorization:
        assert maximum_trips == 100
        return authorization

    monkeypatch.setattr(realtime_route, "authorize_mobile_realtime", authorize)

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
            self.unregistered = False
            self.authenticating = 0

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
            return connection

        async def unregister(self, current: MobileRealtimeConnection) -> None:
            assert current is connection
            self.unregistered = True

    class _Socket:
        query_params: dict[str, str] = {}
        headers = {"authorization": "Bearer header-token"}
        url = SimpleNamespace(scheme="wss", netloc="api.example.com")

        def __init__(self) -> None:
            self.client_state = WebSocketState.CONNECTING
            self.closed_code: int | None = None

        async def accept(self) -> None:
            self.client_state = WebSocketState.CONNECTED

        async def send_json(self, _payload: dict[str, str | int]) -> None:
            return None

        async def receive_text(self) -> str:
            return '{"type":"not-an-ack"}'

        async def close(self, code: int) -> None:
            self.closed_code = code
            self.client_state = WebSocketState.DISCONNECTED

    hub = _Hub()
    socket = _Socket()
    await realtime_route.mobile_realtime_socket(
        socket,  # type: ignore[arg-type]
        settings=Settings(app_secret_key="unit-test-secret", _env_file=None),
        hub=hub,  # type: ignore[arg-type]
    )
    assert hub.unregistered is True
    assert hub.authenticating == 0
    assert socket.closed_code == 1008


@pytest.mark.asyncio
async def test_live_session_revocation_closes_socket_as_unauthorized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal_id = uuid.uuid4()
    authorization = MobileRealtimeAuthorization(
        agency_id=uuid.uuid4(),
        account_id=principal_id,
        principal_id=principal_id,
        principal_type="coordinator",
        session_id=uuid.uuid4(),
        session_generation=1,
        trip_ids=frozenset({uuid.uuid4()}),
    )
    connection = MobileRealtimeConnection(
        authorization=authorization,
        maximum_pending_trips=4,
    )

    async def revoked(_token: str, *, maximum_trips: int) -> None:
        assert maximum_trips == 100
        raise AuthenticationError("revoked")

    monkeypatch.setattr(realtime_route, "authorize_mobile_realtime", revoked)
    with pytest.raises(_SocketClose) as closed:
        await _refresh_authorization(
            connection,
            SimpleNamespace(update_authorization=None),  # type: ignore[arg-type]
            "expired-token",
            interval_seconds=0,
            maximum_trips=100,
        )
    assert closed.value.code == 4401
