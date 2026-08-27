"""Same-origin, cookie-authenticated dashboard realtime invalidation hints."""

from __future__ import annotations

import asyncio
import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, WebSocket

from app.application.dashboard_realtime_authorization import (
    load_dashboard_realtime_authorization,
)
from app.application.mobile.realtime_authorization import MobileRealtimeAuthorization
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
from app.presentation.api.v1.routes.realtime_socket_support import (
    RealtimeSocketClose,
    serve_registered_realtime_connection,
)

router = APIRouter()
logger = get_logger(__name__)

_MAX_COOKIE_HEADER_BYTES = 16_384
_MAX_ACCESS_COOKIE_BYTES = 8_192


def _dashboard_access_cookie(websocket: WebSocket, settings: Settings) -> str | None:
    """Accept only the ambient HttpOnly access cookie, never URL/header auth."""

    if websocket.query_params or websocket.headers.get("authorization") is not None:
        return None
    raw_cookie_header = websocket.headers.get("cookie", "")
    if len(raw_cookie_header.encode("utf-8")) > _MAX_COOKIE_HEADER_BYTES:
        return None
    token = websocket.cookies.get(settings.jwt.access_cookie_name)
    if (
        not isinstance(token, str)
        or not token
        or len(token.encode("utf-8")) > _MAX_ACCESS_COOKIE_BYTES
    ):
        return None
    return token


def _dashboard_origin_allowed(websocket: WebSocket, settings: Settings) -> bool:
    """Require an exact configured origin whose authority matches Host."""

    supplied = _normalized_origin(websocket.headers.get("origin"))
    if supplied is None:
        return False
    allowed = {
        normalized
        for value in settings.allowed_origins
        if (normalized := _normalized_origin(value)) is not None
    }
    if supplied not in allowed:
        return False

    host = websocket.headers.get("host") or websocket.url.netloc
    host_origin = _normalized_origin(f"{supplied[0]}://{host}")
    return host_origin == supplied


def _normalized_origin(value: str | None) -> tuple[str, str, int | None] | None:
    if value is None:
        return None
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return None
    if (parsed.scheme == "http" and port == 80) or (
        parsed.scheme == "https" and port == 443
    ):
        port = None
    return parsed.scheme, parsed.hostname.casefold(), port


async def authorize_dashboard_realtime(
    token: str,
    *,
    maximum_trips: int,
) -> MobileRealtimeAuthorization:
    """Authenticate and resolve current dashboard grants in one short session."""

    async with AsyncSessionFactory() as session:
        try:
            authorization = await load_dashboard_realtime_authorization(
                session,
                token,
                maximum_trips=maximum_trips,
            )
            await session.commit()
            return authorization
        except Exception:
            await session.rollback()
            raise


async def _refresh_dashboard_authorization(
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
            current = await authorize_dashboard_realtime(
                token,
                maximum_trips=maximum_trips,
            )
        except AuthenticationError as exc:
            raise RealtimeSocketClose(4401) from exc
        except AuthorizationError as exc:
            raise RealtimeSocketClose(4403) from exc
        except Exception as exc:
            raise RealtimeSocketClose(1013) from exc
        if not await hub.update_authorization(connection, current):
            raise RealtimeSocketClose(connection.close_code or 4401)


@router.websocket("/realtime")
async def dashboard_realtime_socket(
    websocket: WebSocket,
    settings: Settings = Depends(get_settings),
    hub: MobileRealtimeHub = Depends(get_mobile_realtime_hub),
) -> None:
    """Deliver lossy PII-free hints; durable dashboard reads own correctness."""

    config = hub.config
    if config is None or not hub.accepting_connections:
        await websocket.close(code=1013)
        return
    if not _dashboard_origin_allowed(websocket, settings):
        await websocket.close(code=1008)
        return
    token = _dashboard_access_cookie(websocket, settings)
    if token is None:
        await websocket.close(code=4401)
        return

    authorization_reservation_id: uuid.UUID | None = None
    try:
        authorization_reservation_id = await hub.begin_authorization()
        authorization = await authorize_dashboard_realtime(
            token,
            maximum_trips=config.max_trips_per_connection,
        )
    except AuthenticationError:
        await websocket.close(code=4401)
        return
    except AuthorizationError:
        await websocket.close(code=4403)
        return
    except MobileRealtimeCapacityError:
        await websocket.close(code=1013)
        return
    except Exception as exc:
        logger.warning(
            "dashboard_realtime_authorization_unavailable",
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
            "dashboard_realtime_registration_unavailable",
            error_type=type(exc).__name__,
        )
        await websocket.close(code=1013)
        return

    await serve_registered_realtime_connection(
        websocket,
        connection=connection,
        hub=hub,
        config=config,
        refresh_authorization=lambda: _refresh_dashboard_authorization(
            connection,
            hub,
            token,
            interval_seconds=config.authorization_refresh_seconds,
            maximum_trips=config.max_trips_per_connection,
        ),
        task_prefix="dashboard-realtime",
    )


__all__ = [
    "authorize_dashboard_realtime",
    "dashboard_realtime_socket",
    "router",
]
