"""HTTP request metrics middleware."""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.infrastructure.observability import metrics


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: object) -> Response:
        started = time.perf_counter()
        response: Response = await call_next(request)  # type: ignore[arg-type]
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        metrics.record_request(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        response.headers["X-Response-Time-Ms"] = str(duration_ms)
        return response
