"""Origin-based CSRF protection for cookie-authenticated state changes."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import HTTPException, Request, status

from app.core.config.settings import get_settings


def _normalized_origin(value: str) -> tuple[str, str, int | None] | None:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    port = parsed.port
    if (parsed.scheme == "http" and port == 80) or (
        parsed.scheme == "https" and port == 443
    ):
        port = None
    return parsed.scheme, parsed.hostname.lower(), port


async def require_cookie_csrf(request: Request) -> None:
    """Require a trusted Origin/Referer only when access auth uses a cookie.

    Bearer-authenticated API clients are not vulnerable to ambient-cookie CSRF
    and therefore bypass this browser-only check.
    """

    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return

    settings = get_settings()
    if not request.cookies.get(settings.jwt.access_cookie_name):
        return

    supplied = request.headers.get("origin") or request.headers.get("referer")
    supplied_origin = _normalized_origin(supplied) if supplied else None
    allowed = {
        origin
        for configured in settings.allowed_origins
        if (origin := _normalized_origin(configured)) is not None
    }
    if supplied_origin is None or supplied_origin not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-site request validation failed.",
        )
