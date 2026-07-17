"""
Request ID Middleware
=====================
Injects a unique X-Request-ID header on every request and response.

Benefits:
  - Every log entry is correlated to a specific request.
  - Frontend and monitoring systems can trace end-to-end flows.
  - Structlog context vars are used so all log calls in the
    request context automatically include the request_id.
"""

from __future__ import annotations

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.presentation.middleware.request_path import safe_request_path


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Assigns a unique request_id to every incoming request.

    Priority:
      1. Uses X-Request-ID header if provided by the client/load balancer.
      2. Generates a new UUID4 if not provided.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        # Bind to structlog context so all log calls in this request
        # automatically include request_id without manual passing.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=safe_request_path(request),
        )

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
