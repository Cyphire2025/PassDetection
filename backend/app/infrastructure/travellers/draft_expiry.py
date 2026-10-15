"""Bounded temporary-draft retention; adopted documents are never deleted."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.travellers.draft_retention import stage_draft_asset_cleanup
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftAssetModel as Asset,
)
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftContactProofModel as Proof,
)
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerReturningDraftModel as Draft,
)
from app.infrastructure.travellers.draft_orphans import discard_orphan_images


async def expire_draft_assets(*, factory: async_sessionmaker[AsyncSession] = AsyncSessionFactory) -> int:
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        # Select owners first: upload/finalization use the same draft -> asset order.
        drafts = list(await session.scalars(select(Draft).where(Draft.status.in_(("active", "submitted")), Draft.expires_at <= now)
            .order_by(Draft.expires_at, Draft.id).limit(20).with_for_update(skip_locked=True)))
        for draft in drafts:
            draft.status = "expired"
            draft.verified_phone_ciphertext = draft.verified_phone_fingerprint = None
            draft.payload_ciphertext = ""  # No retained personal draft text after expiry.
            draft.requirements_ciphertext = None
        # Production disables autoflush; the asset join must see these expiries.
        await session.flush()
        expired_ids = [draft.id for draft in drafts]
        if expired_ids:
            await session.execute(delete(Proof).where(Proof.draft_id.in_(expired_ids)))
            await session.execute(update(Asset).where(Asset.draft_id.in_(expired_ids))
                .values(extraction_ciphertext=None, classification_ciphertext=None))
        assets = list(await session.scalars(select(Asset).join(Draft, Draft.id == Asset.draft_id).where(
            Asset.state.in_(("uploading", "ready")),
            or_(Draft.status == "expired", (Asset.state == "uploading") & (Asset.created_at < now - timedelta(minutes=5))),
        ).order_by(Asset.created_at, Asset.id).limit(100).with_for_update(skip_locked=True, of=Asset)))
        for asset in assets:
            stage_draft_asset_cleanup(session, asset)
        # The orphan pass refreshes rows; never reload a just-discarded upload.
        await session.flush()
        orphaned = await discard_orphan_images(session, limit=100-len(assets)) if len(assets) < 100 else 0
        return len(assets) + orphaned
