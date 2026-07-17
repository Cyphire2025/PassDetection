"""HTTP request metrics middleware."""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.infrastructure.observability import metrics
from app.presentation.middleware.request_path import safe_request_path


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        metrics.record_request(
            method=request.method,
            path=safe_request_path(request, prefer_route_template=True),
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        response.headers["X-Response-Time-Ms"] = str(duration_ms)
        return response
