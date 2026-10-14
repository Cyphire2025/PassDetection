"""Same-browser, per-member capabilities with no historical authority."""
from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.travellers.draft_store import FreshDraftStore
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.fresh_drafts import fresh_secret
from app.core.config.settings import Settings, get_settings
from app.core.config.traveller_reuse import get_traveller_reuse_settings
from app.infrastructure.database.session import get_db_session
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto

FRESH_COOKIE = "pd_fresh_drafts"
FRESH_COOKIE_PATH = "/api/v1/public-drafts"


def fresh_store(session: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings)) -> FreshDraftStore:
    return FreshDraftStore(session, settings, TravellerReuseCrypto(get_traveller_reuse_settings()))


def upload_session(value: str = Header(..., alias="X-Upload-Session-ID", min_length=32, max_length=128)) -> str:
    return value


def fresh_token(group_token: str, request: Request, session_id: str = Depends(upload_session),
    service: FreshDraftStore = Depends(fresh_store),
) -> str:
    browser = request.cookies.get(FRESH_COOKIE)
    if not browser:
        raise ReuseError(ReuseReason.EXPIRED)
    return fresh_secret(service, group_token, browser, session_id)
