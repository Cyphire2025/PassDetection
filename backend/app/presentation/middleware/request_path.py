"""Low-cardinality, secret-safe request path labels."""

from __future__ import annotations

import re

from starlette.requests import Request

_PUBLIC_TOKEN_SEGMENTS = (
    re.compile(r"^(/api/v1/passports/upload/)[^/]+"),
    re.compile(r"^(/api/v1/upload-links/token/)[^/]+"),
)
_UUID_SEGMENT = re.compile(
    r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}"
    r"-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}(?=/|$)"
)


def safe_request_path(request: Request, *, prefer_route_template: bool = False) -> str:
    """Return a route template or redact token/UUID path segments."""

    if prefer_route_template:
        route = request.scope.get("route")
        route_path = getattr(route, "path", None)
        if isinstance(route_path, str) and route_path:
            return route_path

    path = request.url.path
    for pattern in _PUBLIC_TOKEN_SEGMENTS:
        path = pattern.sub(r"\1{token}", path)
    return _UUID_SEGMENT.sub("/{id}", path)
