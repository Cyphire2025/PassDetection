"""The shared encrypted storage context; authority is supplied by each flow."""
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import Settings
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto


class DraftStore(Protocol):
    session: AsyncSession
    settings: Settings
    crypto: TravellerReuseCrypto


@dataclass
class FreshDraftStore:
    session: AsyncSession
    settings: Settings
    crypto: TravellerReuseCrypto
