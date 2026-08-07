"""Origin-based CSRF protection for cookie-authenticated state changes."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import HTTPException, Request, status

from app.core.config.settings import get_settings

_CSRF_FAILURE_DETAIL = "Cross-site request validation failed."


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
    """Require a trusted Origin/Referer when dashboard auth uses a cookie.

    Bearer-authenticated API clients are not vulnerable to ambient-cookie CSRF
    and therefore bypass this browser-only check.
    """

    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return

    settings = get_settings()
    cookie_names = {
        settings.jwt.access_cookie_name,
        settings.jwt.refresh_cookie_name,
    }
    if not any(request.cookies.get(name) for name in cookie_names):
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
            detail=_CSRF_FAILURE_DETAIL,
        )


async def require_trusted_request_origin(request: Request) -> None:
    """Reject browser cross-site requests without requiring ambient cookies.

    Login needs this pre-authentication variant because a successful response
    establishes the cookies that are absent on the request. Headerless API and
    OAuth password clients remain compatible; browsers that supply an Origin,
    Referer, or Fetch Metadata signal must identify a trusted origin.
    """

    supplied = request.headers.get("origin") or request.headers.get("referer")
    fetch_site = request.headers.get("sec-fetch-site", "").strip().lower()
    if supplied is None:
        if fetch_site == "cross-site":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=_CSRF_FAILURE_DETAIL,
            )
        return

    settings = get_settings()
    supplied_origin = _normalized_origin(supplied)
    allowed = {
        origin
        for configured in settings.allowed_origins
        if (origin := _normalized_origin(configured)) is not None
    }
    if supplied_origin is None or supplied_origin not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_CSRF_FAILURE_DETAIL,
        )
