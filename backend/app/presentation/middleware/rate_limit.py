"""Small Redis-backed fixed-window rate limiter with local fallback."""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import status
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger

logger = get_logger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    _local_counts: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))

    def __init__(self, app, *, window_seconds: int = 60) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._settings = get_settings()
        self._window_seconds = window_seconds
        self._redis: Redis | None = None
        if self._settings.rate_limit_per_minute > 0:
            try:
                self._redis = Redis.from_url(self._settings.redis.url, encoding="utf-8", decode_responses=True)
            except Exception as exc:
                logger.warning("rate_limit_redis_init_failed", error=str(exc))

    async def dispatch(self, request: Request, call_next: object) -> Response:
        limit = self._limit_for(request)
        if limit <= 0 or request.url.path.startswith("/api/v1/health"):
            return await call_next(request)  # type: ignore[arg-type]

        key = self._key_for(request)
        count = await self._increment(key)
        if count > limit:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"error": {"code": "RATE_LIMIT_EXCEEDED", "message": "Rate limit exceeded. Please try again later."}},
                headers={"Retry-After": str(self._window_seconds)},
            )

        response: Response = await call_next(request)  # type: ignore[arg-type]
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - count))
        return response

    def _limit_for(self, request: Request) -> int:
        base = self._settings.rate_limit_per_minute
        if request.method == "POST" and "/api/v1/passports/upload/" in request.url.path:
            return max(10, min(base, 30))
        return base

    def _key_for(self, request: Request) -> str:
        forwarded_for = request.headers.get("x-forwarded-for", "")
        ip = forwarded_for.split(",", 1)[0].strip() or (request.client.host if request.client else "unknown")
        bucket = int(time.time() // self._window_seconds)
        path_group = "passport-upload" if "/api/v1/passports/upload/" in request.url.path else "api"
        return f"rate-limit:{path_group}:{ip}:{bucket}"

    async def _increment(self, key: str) -> int:
        if self._redis is not None:
            try:
                count = await self._redis.incr(key)
                if count == 1:
                    await self._redis.expire(key, self._window_seconds + 1)
                return int(count)
            except Exception as exc:
                logger.warning("rate_limit_redis_failed_using_local", error=str(exc))
                self._redis = None

        count, expires_at = self._local_counts[key]
        now = time.time()
        if now > expires_at:
            count = 0
            expires_at = now + self._window_seconds
        count += 1
        self._local_counts[key] = (count, expires_at)
        return count
