"""Connection-scoped quotas after authentication; distributed and fail closed in production."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Awaitable
from typing import cast

from mcp.server.auth.middleware.auth_context import get_access_token
from redis.asyncio import Redis
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config.settings import Settings

_COUNT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], 60) end
return count
"""


class MCPConnectionRateLimit:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.redis: Redis | None = None
        self.local: OrderedDict[str, tuple[int, float]] = OrderedDict()

    async def count(self, grant_id: str) -> int:
        key = f"mcp:connection-quota:v1:{grant_id}"
        if self.settings.app_env != "development":
            if self.redis is None:
                self.redis = Redis.from_url(
                    self.settings.redis.security_url,
                    socket_connect_timeout=1,
                    socket_timeout=1,
                    max_connections=4,
                )
            result = await cast(Awaitable[object], self.redis.eval(_COUNT_SCRIPT, 1, key))
            if not isinstance(result, int):
                raise RuntimeError("Invalid connection quota result")
            return result
        now = time.monotonic()
        count, deadline = self.local.get(key, (0, now + 60))
        if deadline <= now:
            count, deadline = 0, now + 60
        self.local[key] = (count + 1, deadline)
        self.local.move_to_end(key)
        while len(self.local) > 2048:
            self.local.popitem(last=False)
        return count + 1

    def middleware(self, app: ASGIApp) -> ASGIApp:
        async def limited(scope: Scope, receive: Receive, send: Send) -> None:
            token = get_access_token()
            if scope["type"] != "http" or scope.get("path") != "/mcp" or token is None:
                await app(scope, receive, send)
                return
            claims = token.claims or {}
            grant_id = claims.get("grant_id")
            if not isinstance(grant_id, str):
                response = JSONResponse({"error": "invalid_token"}, status_code=401)
            else:
                try:
                    count = await self.count(grant_id)
                except Exception:
                    response = JSONResponse(
                        {"error": "temporarily_unavailable"},
                        status_code=503,
                        headers={"Retry-After": "5", "Cache-Control": "no-store"},
                    )
                else:
                    if count <= self.settings.mcp.requests_per_minute:
                        await app(scope, receive, send)
                        return
                    response = JSONResponse(
                        {"error": "rate_limited"},
                        status_code=429,
                        headers={"Retry-After": "60", "Cache-Control": "no-store"},
                    )
            await response(scope, receive, send)

        return limited

    async def close(self) -> None:
        if self.redis is not None:
            await self.redis.aclose()
            self.redis = None
