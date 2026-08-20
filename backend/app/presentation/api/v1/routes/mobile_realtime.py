"""Authenticated, foreground mobile WebSocket for cursor-sync hints only."""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials
from starlette.websockets import WebSocketState

from app.application.mobile.realtime_authorization import (
    MobileRealtimeAuthorization,
    load_mobile_realtime_authorization,
)
from app.core.config.settings import Settings, get_settings
from app.core.logging.logger import get_logger
from app.domain.exceptions.exceptions import AuthenticationError, AuthorizationError
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.mobile_realtime import (
    MobileRealtimeCapacityError,
    MobileRealtimeConnection,
    MobileRealtimeConnectionClosed,
    MobileRealtimeHub,
    get_mobile_realtime_hub,
)
from app.presentation.dependencies.mobile_auth import get_current_mobile_claims

router = APIRouter()
logger = get_logger(__name__)

_MAX_AUTHORIZATION_BYTES = 8_192
_MAX_CLIENT_MESSAGE_BYTES = 128


class _SocketClose(RuntimeError):
    def __init__(self, code: int) -> None:
        super().__init__(f"WebSocket close {code}")
        self.code = code


def _bearer_token(websocket: WebSocket) -> str | None:
    # This endpoint has no query parameters. Rejecting all of them makes it
    # impossible for a future client to accidentally put a bearer token in a
    # URL, proxy access log, analytics event, or crash breadcrumb.
    if websocket.query_params:
        return None
    header = websocket.headers.get("authorization")
    if header is None or len(header.encode("utf-8")) > _MAX_AUTHORIZATION_BYTES:
        return None
    parts = header.split(" ")
    if len(parts) != 2 or parts[0].casefold() != "bearer" or not parts[1]:
        return None
    return str(parts[1])


def _origin_allowed(websocket: WebSocket, settings: Settings) -> bool:
    origin = websocket.headers.get("origin")
    if origin is None:
        # Native Android/iOS clients normally omit Origin and authenticate with
        # a header browsers cannot set through the WebSocket constructor.
        return True
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    normalized = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    allowed = {value.rstrip("/") for value in settings.allowed_origins}
    socket_scheme = "https" if websocket.url.scheme == "wss" else "http"
    allowed.add(f"{socket_scheme}://{websocket.url.netloc}".rstrip("/"))
    return normalized in allowed


async def authorize_mobile_realtime(
    token: str,
    *,
    maximum_trips: int,
) -> MobileRealtimeAuthorization:
    """Authenticate and snapshot grants in a short database transaction."""

    async with AsyncSessionFactory() as session:
        try:
            claims = await get_current_mobile_claims(
                credentials=HTTPAuthorizationCredentials(
                    scheme="Bearer",
                    credentials=token,
                ),
                session=session,
            )
            authorization = await load_mobile_realtime_authorization(
                session,
                claims,
                maximum_trips=maximum_trips,
            )
            await session.commit()
            return authorization
        except Exception:
            await session.rollback()
            raise


async def _read_heartbeats(
    websocket: WebSocket,
    *,
    idle_timeout_seconds: int,
) -> None:
    while True:
        try:
            value = await asyncio.wait_for(
                websocket.receive_text(),
                timeout=idle_timeout_seconds,
            )
        except TimeoutError as exc:
            raise _SocketClose(1001) from exc
        if len(value.encode("utf-8")) > _MAX_CLIENT_MESSAGE_BYTES:
            raise _SocketClose(1009)
        try:
            payload = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise _SocketClose(1008) from exc
        if payload != {"type": "heartbeat_ack"}:
            raise _SocketClose(1008)


async def _write_hints(
    websocket: WebSocket,
    connection: MobileRealtimeConnection,
    *,
    heartbeat_seconds: int,
    send_timeout_seconds: float,
) -> None:
    loop = asyncio.get_running_loop()
    next_heartbeat_at = loop.time() + heartbeat_seconds
    while True:
        heartbeat_remaining = next_heartbeat_at - loop.time()
        payload: dict[str, str | int]
        if heartbeat_remaining <= 0:
            payload = {"type": "heartbeat"}
            next_heartbeat_at = loop.time() + heartbeat_seconds
        else:
            try:
                hint = await asyncio.wait_for(
                    connection.next_hint(),
                    timeout=heartbeat_remaining,
                )
                payload = hint.client_payload()
            except TimeoutError:
                payload = {"type": "heartbeat"}
                next_heartbeat_at = loop.time() + heartbeat_seconds
            except MobileRealtimeConnectionClosed as exc:
                raise _SocketClose(connection.close_code or 1013) from exc
        try:
            # ``asyncio.wait_for`` has a cancellation race on the supported
            # CPython 3.11 runtime when the wrapped send completes at the same
            # instant the writer task is cancelled. A websocket teardown can
            # then wait forever and retain its hub/session capacity lease.
            # The 3.11 timeout context keeps the timeout local to this task and
            # preserves external cancellation deterministically.
            async with asyncio.timeout(send_timeout_seconds):
                await websocket.send_json(payload)
        except TimeoutError as exc:
            raise _SocketClose(1013) from exc


async def _refresh_authorization(
    connection: MobileRealtimeConnection,
    hub: MobileRealtimeHub,
    token: str,
    *,
    interval_seconds: int,
    maximum_trips: int,
) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            current = await authorize_mobile_realtime(
                token,
                maximum_trips=maximum_trips,
            )
        except (AuthenticationError, AuthorizationError) as exc:
            raise _SocketClose(4401) from exc
        except Exception as exc:
            raise _SocketClose(1013) from exc
        if not await hub.update_authorization(connection, current):
            raise _SocketClose(connection.close_code or 4401)


@router.websocket("/realtime")
async def mobile_realtime_socket(
    websocket: WebSocket,
    settings: Settings = Depends(get_settings),
    hub: MobileRealtimeHub = Depends(get_mobile_realtime_hub),
) -> None:
    """Deliver PII-free hints; the client's durable cursor owns correctness."""

    config = hub.config
    if config is None or not hub.accepting_connections:
        await websocket.close(code=1013)
        return
    if not _origin_allowed(websocket, settings):
        await websocket.close(code=1008)
        return
    token = _bearer_token(websocket)
    if token is None:
        await websocket.close(code=4401)
        return
    authorization_reservation_id: uuid.UUID | None = None
    try:
        authorization_reservation_id = await hub.begin_authorization()
        authorization = await authorize_mobile_realtime(
            token,
            maximum_trips=config.max_trips_per_connection,
        )
    except (AuthenticationError, AuthorizationError):
        await websocket.close(code=4401)
        return
    except MobileRealtimeCapacityError:
        await websocket.close(code=1013)
        return
    except Exception as exc:
        logger.warning(
            "mobile_realtime_authorization_unavailable",
            error_type=type(exc).__name__,
        )
        await websocket.close(code=1013)
        return
    finally:
        if authorization_reservation_id is not None:
            await hub.end_authorization(authorization_reservation_id)

    try:
        connection = await hub.register(authorization)
    except MobileRealtimeCapacityError:
        await websocket.close(code=1013)
        return
    except Exception as exc:
        logger.warning(
            "mobile_realtime_authorization_unavailable",
            error_type=type(exc).__name__,
        )
        await websocket.close(code=1013)
        return

    close_code = 1000
    tasks: set[asyncio.Task[None]] = set()
    try:
        await websocket.accept()
        await asyncio.wait_for(
            websocket.send_json(
                {
                    "type": "ready",
                    "heartbeat_seconds": config.heartbeat_seconds,
                    "idle_timeout_seconds": config.idle_timeout_seconds,
                }
            ),
            timeout=config.send_timeout_seconds,
        )
        tasks = {
            asyncio.create_task(
                _read_heartbeats(
                    websocket,
                    idle_timeout_seconds=config.idle_timeout_seconds,
                ),
                name="mobile-realtime-reader",
            ),
            asyncio.create_task(
                _write_hints(
                    websocket,
                    connection,
                    heartbeat_seconds=config.heartbeat_seconds,
                    send_timeout_seconds=config.send_timeout_seconds,
                ),
                name="mobile-realtime-writer",
            ),
            asyncio.create_task(
                _refresh_authorization(
                    connection,
                    hub,
                    token,
                    interval_seconds=config.authorization_refresh_seconds,
                    maximum_trips=config.max_trips_per_connection,
                ),
                name="mobile-realtime-authorization",
            ),
        }
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except _SocketClose as exc:
        close_code = exc.code
    except WebSocketDisconnect:
        close_code = 1000
    except TimeoutError:
        close_code = 1013
    except Exception as exc:
        logger.warning(
            "mobile_realtime_connection_failed",
            error_type=type(exc).__name__,
        )
        close_code = 1011
    finally:
        for task in tasks:
            task.cancel()
        # A completed task may be the same task whose exception selected the
        # close code above. Drain every task without re-raising during cleanup,
        # so the hub index and per-session capacity counters are always freed.
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await hub.unregister(connection)
        if websocket.client_state == WebSocketState.CONNECTED:
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await websocket.close(code=close_code)


__all__ = ["authorize_mobile_realtime", "mobile_realtime_socket", "router"]
