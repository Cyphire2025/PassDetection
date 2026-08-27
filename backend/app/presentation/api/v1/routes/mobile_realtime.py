"""Authenticated, foreground mobile WebSocket for cursor-sync hints only."""

from __future__ import annotations

import asyncio
import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, WebSocket
from fastapi.security import HTTPAuthorizationCredentials

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
    MobileRealtimeHub,
    get_mobile_realtime_hub,
)
from app.presentation.api.v1.routes import realtime_socket_support
from app.presentation.dependencies.mobile_auth import get_current_mobile_claims

router = APIRouter()
logger = get_logger(__name__)

_SocketClose = realtime_socket_support.RealtimeSocketClose
_read_heartbeats = realtime_socket_support.read_realtime_heartbeats
_write_hints = realtime_socket_support.write_realtime_hints
serve_registered_realtime_connection = (
    realtime_socket_support.serve_registered_realtime_connection
)

_MAX_AUTHORIZATION_BYTES = 8_192


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

    await serve_registered_realtime_connection(
        websocket,
        connection=connection,
        hub=hub,
        config=config,
        refresh_authorization=lambda: _refresh_authorization(
            connection,
            hub,
            token,
            interval_seconds=config.authorization_refresh_seconds,
            maximum_trips=config.max_trips_per_connection,
        ),
        task_prefix="mobile-realtime",
    )


__all__ = ["authorize_mobile_realtime", "mobile_realtime_socket", "router"]
