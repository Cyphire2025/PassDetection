"""Indexed keyset sweep of at most 100 old temporary assets per tick.

The Redis cursor avoids repeatedly checking the oldest still-open forms. It is
only a scan hint: loss restarts the scan, and every deletion rechecks DB owners.
"""
from datetime import UTC, datetime, timedelta

from redis.exceptions import RedisError
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.travellers.draft_retention import stage_draft_asset_cleanup
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftAssetModel as Asset,
)
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerReturningDraftModel as Draft,
)
from app.infrastructure.observability.metrics import metrics
from app.infrastructure.travellers.draft_presence import (
    PRESENCE_SECONDS,
    DraftPresence,
    draft_presence,
)


async def discard_orphan_images(session: AsyncSession, *, limit: int = 100) -> int:
    if not 1 <= limit <= 100:
        raise ValueError("draft_cleanup_batch_exceeded")
    try:
        async with draft_presence() as presence:
            return await _scan_orphans(session, presence, limit)
    except (RedisError, TimeoutError, OSError, ValueError):
        # Presence is not authority. Losing it must not evict an open form.
        metrics.increment("traveller.draft_presence.cleanup_unavailable")
        return 0


async def _scan_orphans(session: AsyncSession, presence: DraftPresence, limit: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(seconds=PRESENCE_SECONDS)
    query = select(Asset.id, Asset.draft_id, Asset.created_at).where(
        Asset.state.in_(("uploading", "ready")), Asset.created_at <= cutoff)
    cursor = await presence.cursor()
    if cursor:
        query = query.where(or_(Asset.created_at > cursor[0],
            and_(Asset.created_at == cursor[0], Asset.id > cursor[1])))
    candidates = (await session.execute(query.order_by(Asset.created_at, Asset.id).limit(limit))).all()
    if not candidates:
        await presence.advance(None)
        return 0
    owners = list(await session.scalars(select(Draft).where(
        Draft.id.in_({row.draft_id for row in candidates}), Draft.status == "active",
        Draft.expires_at > datetime.now(UTC),
    ).order_by(Draft.id).with_for_update(skip_locked=True).execution_options(populate_existing=True)))
    active = await presence.active([(draft.agency_id, draft.id) for draft in owners])
    abandoned = {draft.id: draft for draft in owners if draft.id not in active}
    assets = list(await session.scalars(select(Asset).where(
        Asset.id.in_([row.id for row in candidates]), Asset.draft_id.in_(abandoned),
        Asset.state.in_(("uploading", "ready")), Asset.created_at <= cutoff,
    ).order_by(Asset.id).with_for_update().execution_options(populate_existing=True)))
    # Advance the disposable scan hint before staging any mutations. A Redis
    # failure then leaves every active draft untouched in this transaction.
    await presence.advance((candidates[-1].created_at, candidates[-1].id))
    for asset in assets:
        stage_draft_asset_cleanup(session, asset)
    for owner_id in {asset.draft_id for asset in assets}:
        abandoned[owner_id].revision += 1
    return len(assets)
