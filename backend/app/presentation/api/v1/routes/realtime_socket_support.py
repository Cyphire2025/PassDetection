"""Shared bounded WebSocket protocol for PII-free realtime hints."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.core.logging.logger import get_logger
from app.infrastructure.mobile_realtime import (
    MobileRealtimeConfig,
    MobileRealtimeConnection,
    MobileRealtimeConnectionClosed,
    MobileRealtimeHub,
)

logger = get_logger(__name__)

MAX_CLIENT_MESSAGE_BYTES = 128
MAX_SERVER_FRAME_BYTES = 1_024


class RealtimeSocketClose(RuntimeError):
    def __init__(self, code: int) -> None:
        super().__init__(f"WebSocket close {code}")
        self.code = code


async def send_bounded_realtime_json(
    websocket: WebSocket,
    payload: dict[str, str | int],
) -> None:
    """Enforce the protocol envelope before handing it to the ASGI server."""

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_SERVER_FRAME_BYTES:
        raise RealtimeSocketClose(1011)
    await websocket.send_json(payload)


async def read_realtime_heartbeats(
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
            raise RealtimeSocketClose(1001) from exc
        if len(value.encode("utf-8")) > MAX_CLIENT_MESSAGE_BYTES:
            raise RealtimeSocketClose(1009)
        try:
            payload = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise RealtimeSocketClose(1008) from exc
        if payload != {"type": "heartbeat_ack"}:
            raise RealtimeSocketClose(1008)


async def write_realtime_hints(
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
                # On CPython 3.11, ``wait_for`` can swallow an external task
                # cancellation when it races with completion of the inner
                # coroutine.  That can leave WebSocket cleanup waiting on a
                # busy writer forever.  The timeout context preserves the
                # distinction between its own deadline and server shutdown.
                async with asyncio.timeout(heartbeat_remaining):
                    hint = await connection.next_hint()
                payload = hint.client_payload()
            except TimeoutError:
                payload = {"type": "heartbeat"}
                next_heartbeat_at = loop.time() + heartbeat_seconds
            except MobileRealtimeConnectionClosed as exc:
                raise RealtimeSocketClose(connection.close_code or 1013) from exc
        try:
            # The timeout context keeps external task cancellation distinct
            # from a stalled ASGI send on the supported CPython 3.11 runtime.
            async with asyncio.timeout(send_timeout_seconds):
                await send_bounded_realtime_json(websocket, payload)
        except TimeoutError as exc:
            raise RealtimeSocketClose(1013) from exc


async def serve_registered_realtime_connection(
    websocket: WebSocket,
    *,
    connection: MobileRealtimeConnection,
    hub: MobileRealtimeHub,
    config: MobileRealtimeConfig,
    refresh_authorization: Callable[[], Coroutine[Any, Any, None]],
    task_prefix: str,
) -> None:
    """Serve one registered connection and always release its hub capacity."""

    close_code = 1000
    tasks: set[asyncio.Task[None]] = set()
    try:
        await websocket.accept()
        async with asyncio.timeout(config.send_timeout_seconds):
            await send_bounded_realtime_json(
                websocket,
                {
                    "type": "ready",
                    "heartbeat_seconds": config.heartbeat_seconds,
                    "idle_timeout_seconds": config.idle_timeout_seconds,
                },
            )
        tasks = {
            asyncio.create_task(
                read_realtime_heartbeats(
                    websocket,
                    idle_timeout_seconds=config.idle_timeout_seconds,
                ),
                name=f"{task_prefix}-reader",
            ),
            asyncio.create_task(
                write_realtime_hints(
                    websocket,
                    connection,
                    heartbeat_seconds=config.heartbeat_seconds,
                    send_timeout_seconds=config.send_timeout_seconds,
                ),
                name=f"{task_prefix}-writer",
            ),
            asyncio.create_task(
                refresh_authorization(),
                name=f"{task_prefix}-authorization",
            ),
        }
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except RealtimeSocketClose as exc:
        close_code = exc.code
    except WebSocketDisconnect:
        close_code = 1000
    except TimeoutError:
        close_code = 1013
    except Exception as exc:
        logger.warning(
            "realtime_connection_failed",
            channel=task_prefix,
            error_type=type(exc).__name__,
        )
        close_code = 1011
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await hub.unregister(connection)
        if websocket.client_state == WebSocketState.CONNECTED:
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await websocket.close(code=close_code)


__all__ = [
    "MAX_CLIENT_MESSAGE_BYTES",
    "MAX_SERVER_FRAME_BYTES",
    "RealtimeSocketClose",
    "read_realtime_heartbeats",
    "send_bounded_realtime_json",
    "serve_registered_realtime_connection",
    "write_realtime_hints",
]
