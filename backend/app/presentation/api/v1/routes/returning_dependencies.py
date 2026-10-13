"""Cookie, CSRF and safe exception boundaries for returning travellers."""

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.travellers.claims import ReturningClaims
from app.application.travellers.errors import ReuseError, ReuseReason
from app.core.config.settings import Settings, get_settings
from app.core.config.traveller_reuse import get_traveller_reuse_settings
from app.infrastructure.database.session import get_db_session
from app.infrastructure.security.traveller_request_rate_limiter import get_traveller_request_limiter
from app.presentation.dependencies.csrf import require_trusted_request_origin
from app.presentation.security.client_ip import trusted_client_ip

CLAIM_COOKIE = "pd_returning_claim"
GRANT_COOKIE = "pd_returning_history"
CONTACT_COOKIE = "pd_returning_contact"
COOKIE_PATH = "/api/v1/returning"


def claim_secret(request: Request) -> str:
    secret = request.cookies.get(CLAIM_COOKIE)
    if not secret:
        raise ReuseError(ReuseReason.EXPIRED)
    return secret


def grant_secret(request: Request) -> str:
    secret = request.cookies.get(GRANT_COOKIE)
    if not secret:
        raise ReuseError(ReuseReason.EXPIRED)
    return secret


def set_secret_cookie(response: Response, name: str, secret: str, lifetime: int) -> None:
    settings = get_settings()
    response.set_cookie(name, secret, max_age=lifetime, httponly=True,
        secure=settings.is_production or settings.jwt.cookie_secure,
        samesite="strict", path=COOKIE_PATH)


async def private_boundary(request: Request, response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    await require_trusted_request_origin(request)
    # A stable claim cookie cannot evade its quota by moving between networks.
    # The independent network quota remains effective when cookies are rotated.
    secret = request.cookies.get(CLAIM_COOKIE) or request.cookies.get(GRANT_COOKIE)
    await get_traveller_request_limiter().consume(
        ip_address=trusted_client_ip(request), session_secret=secret,
    )


def returning_service(
    session: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
) -> ReturningClaims:
    return ReturningClaims(session, settings, get_traveller_reuse_settings())
