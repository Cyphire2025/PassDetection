"""Processing presence grants no text, historical, or image disclosure."""
from datetime import UTC, datetime

from redis.exceptions import RedisError
from sqlalchemy import select

from app.application.travellers.draft_retention import DraftActivity
from app.application.travellers.draft_store import DraftStore
from app.application.travellers.errors import ReuseError, ReuseReason
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftAssetModel as Asset,
)
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerReturningDraftModel as Draft,
)
from app.infrastructure.observability.metrics import metrics
from app.infrastructure.travellers.draft_presence import draft_presence


async def require_returning_presence(service: DraftStore, secret: str) -> Draft:
    """Exact draft capability may keep processing alive after history expiry."""
    if not 32 <= len(secret) <= 128:
        raise ReuseError(ReuseReason.EXPIRED)
    draft = await service.session.scalar(select(Draft).where(
        Draft.secret_hash == service.crypto.digest("returning-draft", secret),
        Draft.mode == "returning", Draft.status == "active", Draft.expires_at > datetime.now(UTC),
    ).with_for_update().execution_options(populate_existing=True))
    if draft is None:
        raise ReuseError(ReuseReason.EXPIRED)
    return draft


async def record_draft_activity(service: DraftStore, draft: Draft) -> DraftActivity:
    present = draft.status == "active" and await service.session.scalar(select(Asset.id).where(
        Asset.draft_id == draft.id, Asset.agency_id == draft.agency_id,
        Asset.company_id == draft.company_id, Asset.state.in_(("uploading", "ready")),
    ).limit(1)) is not None
    recorded = False
    if present:
        try:
            async with draft_presence(service.settings) as presence:
                await presence.touch(draft.agency_id, draft.id)
            recorded = True
        except (RedisError, TimeoutError, OSError):
            metrics.increment("traveller.draft_presence.unavailable")
    return DraftActivity(images_present=present, presence_recorded=recorded)
