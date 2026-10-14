"""Discard only unfinished draft images; text retains its fixed 24-hour lifetime.

The draft owner is locked by the caller before at most 30 asset locks. A leave
revision is a cutoff, so delayed requests cannot delete a newer view's uploads.
"""
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.travellers.draft_store import DraftStore
from app.application.travellers.errors import ReuseError, ReuseReason
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftAssetModel as Asset,
)
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerReturningDraftModel as Draft,
)
from app.infrastructure.documents.storage_cleanup import stage_storage_cleanup_jobs


class DraftDiscard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)


class DraftActivity(BaseModel):
    images_present: bool
    presence_recorded: bool
    heartbeat_after_seconds: int = 60


def stage_draft_asset_cleanup(session: AsyncSession, asset: Asset) -> None:
    """Never admit historical/adopted keys into the storage deletion outbox."""
    prefix = f"returning-drafts/{asset.agency_id}/{asset.draft_id}/{asset.id}."
    if asset.state == "adopted" or asset.object_key not in {
        prefix + "jpg", prefix + "png", prefix + "webp"
    }:
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    asset.is_current, asset.state = False, "discarded"
    asset.extraction_status, asset.lease_expires_at = "none", None
    asset.extraction_ciphertext = asset.classification_ciphertext = None
    stage_storage_cleanup_jobs(session, agency_id=asset.agency_id, source="returning_draft_discard",
        context_id=str(asset.id), storage_keys=[asset.object_key])


async def discard_draft_images(service: DraftStore, draft: Draft, *, through_revision: int | None = None) -> int:
    if draft.status != "active":
        return 0
    if through_revision is not None and through_revision > draft.revision:
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    query = select(Asset).where(Asset.draft_id == draft.id, Asset.agency_id == draft.agency_id,
        Asset.company_id == draft.company_id, Asset.state.in_(("uploading", "ready")))
    if through_revision is not None:
        query = query.where(Asset.expected_revision <= through_revision)
    assets = list(await service.session.scalars(query.order_by(Asset.id).limit(31).with_for_update()))
    if len(assets) > 30:
        raise ReuseError(ReuseReason.UNAVAILABLE)
    for asset in assets:
        stage_draft_asset_cleanup(service.session, asset)
    if through_revision is None or through_revision == draft.revision:
        # Also fence a request still scanning before it creates its asset row.
        draft.fields_revision += 1
        draft.revision += 1
    elif assets:
        draft.revision += 1
    await service.session.flush()
    return len(assets)
