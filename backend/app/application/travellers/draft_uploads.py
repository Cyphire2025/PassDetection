"""Reserve before upload; publish one current side after a checked private write."""
import asyncio
import hashlib
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol, cast

from sqlalchemy import func, select

from app.application.travellers.claims import ReturningClaims
from app.application.travellers.draft_contracts import DraftSide, DraftView
from app.application.travellers.draft_retention import stage_draft_asset_cleanup
from app.application.travellers.draft_store import DraftStore
from app.application.travellers.drafts import draft_payload, draft_view, require_draft
from app.application.travellers.errors import ReuseError, ReuseReason
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftAssetModel as Asset,
)
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerReturningDraftModel as Draft,
)

MAX_DRAFT_UPLOADS = 30
MAX_DRAFT_IMAGE_BYTES = 10 * 1024 * 1024


class DraftStorage(Protocol):
    async def upload_file(self, file_content: bytes, file_name: str, content_type: str) -> str: ...


def discard_asset(service: DraftStore, asset: Asset) -> None:
    stage_draft_asset_cleanup(service.session, asset)


async def upload_draft_document(service: ReturningClaims, token: str, secret: str, *, side: DraftSide,
    expected_revision: int, idempotency_key: str, content: bytes, content_type: str, storage: DraftStorage,
    expected_asset_id: uuid.UUID | None = None,
) -> DraftView:
    return await store_draft_document(service, authorize=lambda: require_draft(service, token, secret), side=side,
        expected_revision=expected_revision, idempotency_key=idempotency_key, content=content, content_type=content_type,
        storage=storage, expected_asset_id=expected_asset_id)


async def current_asset(service: DraftStore, draft: Draft, side: DraftSide) -> Asset | None:
    return cast(Asset | None, await service.session.scalar(select(Asset).where(Asset.draft_id == draft.id,
        Asset.agency_id == draft.agency_id, Asset.company_id == draft.company_id,
        Asset.side == side, Asset.is_current.is_(True)).with_for_update().execution_options(populate_existing=True)))


async def cleanup_failed_write(service: DraftStore, asset_id: uuid.UUID, draft_id: uuid.UUID) -> None:
    """Rearm deletion after a late write, even if earlier cleanup already ran."""
    await service.session.rollback()
    draft = await service.session.scalar(select(Draft).where(Draft.id == draft_id).with_for_update())
    if draft is None:
        return
    asset = await service.session.scalar(select(Asset).where(Asset.id == asset_id, Asset.draft_id == draft.id,
        Asset.agency_id == draft.agency_id, Asset.company_id == draft.company_id).with_for_update().execution_options(populate_existing=True))
    if asset is not None and asset.state in {"uploading", "discarded", "purged"}:
        discard_asset(service, asset)
        await service.session.commit()


async def reserve_asset(service: DraftStore, draft: Draft, side: DraftSide, unfinished: list[Asset], *,
    idempotency_key: str, content: bytes, content_type: str, checksum: str,
) -> Asset:
    admission_revision = draft.revision
    count = await service.session.scalar(select(func.count()).select_from(Asset).where(Asset.draft_id == draft.id))
    if (count or 0) >= MAX_DRAFT_UPLOADS:
        raise ReuseError(ReuseReason.RATE_LIMITED)
    for earlier in unfinished:
        discard_asset(service, earlier)
    if side == "front":
        payload = draft_payload(service, draft)
        payload.passport_fields = {}
        draft.fields_revision += 1
        draft.payload_ciphertext = service.crypto.encrypt(payload.model_dump_json())
        draft.revision += 1
    asset_id = uuid.uuid4()
    suffix = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[content_type]
    asset = Asset(id=asset_id, agency_id=draft.agency_id, company_id=draft.company_id, draft_id=draft.id,
        side=side, object_key=f"returning-drafts/{draft.agency_id}/{draft.id}/{asset_id}.{suffix}",
        checksum=checksum, byte_size=len(content), content_type=content_type, idempotency_key=idempotency_key,
        state="uploading", is_current=False, expected_revision=admission_revision,
        # A prior worker may treat a pending back as front OCR after rollback.
        # Draft revisions are always >=1; non-front assets can never own fields.
        fields_revision=draft.fields_revision if side == "front" else 0,
        extraction_status="none", attempts=0, available_at=datetime.now(UTC))
    service.session.add(asset)
    return asset


async def publish_asset(service: DraftStore, draft: Draft, asset: Asset, previous_id: uuid.UUID | None) -> DraftView:
    previous = await current_asset(service, draft, cast(DraftSide, asset.side))
    if (previous.id if previous else None) != previous_id:
        discard_asset(service, asset)
        await service.session.commit()
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    if previous:
        discard_asset(service, previous)
        await service.session.flush()
    asset.state, asset.is_current = "ready", True
    if asset.side == "front":
        asset.extraction_status = "pending"
    elif asset.side == "back":
        config = await service.session.scalar(select(ClientGroupModel.upload_configuration).where(
            ClientGroupModel.id == draft.group_id, ClientGroupModel.agency_id == draft.agency_id))
        if (config or {}).get("passport_enabled", True) is True and (config or {}).get("passport_ecr_enabled", False) is True:
            asset.extraction_status = "pending"
    draft.revision += 1
    result = await draft_view(service, draft)
    await service.session.commit()
    return result


async def store_draft_document(service: DraftStore, *, authorize: Callable[[], Awaitable[Draft]], side: DraftSide,
    expected_revision: int, idempotency_key: str, content: bytes, content_type: str, storage: DraftStorage,
    expected_asset_id: uuid.UUID | None = None,
) -> DraftView:
    if not content or len(content) > MAX_DRAFT_IMAGE_BYTES or content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    draft = await authorize()
    checksum = hashlib.sha256(content).hexdigest()
    asset = await service.session.scalar(select(Asset).where(Asset.draft_id == draft.id,
        Asset.agency_id == draft.agency_id, Asset.company_id == draft.company_id,
        Asset.idempotency_key == idempotency_key).with_for_update().execution_options(populate_existing=True))
    if asset:
        if asset.side != side or asset.checksum != checksum or asset.content_type != content_type:
            raise ReuseError(ReuseReason.REVISION_CONFLICT)
        if asset.state == "ready" and asset.is_current:
            result = await draft_view(service, draft)
            await service.session.commit()
            return result
        if asset.state != "uploading":
            raise ReuseError(ReuseReason.REVISION_CONFLICT)
    previous = await current_asset(service, draft, side)
    previous_id = previous.id if previous else None
    unfinished = list(await service.session.scalars(select(Asset).where(Asset.draft_id == draft.id,
        Asset.agency_id == draft.agency_id, Asset.company_id == draft.company_id,
        Asset.side == side, Asset.state == "uploading").order_by(Asset.created_at.desc(), Asset.id.desc())
        .limit(MAX_DRAFT_UPLOADS).with_for_update())) if asset is None else []
    visible_id = unfinished[0].id if unfinished else previous_id
    if expected_asset_id is not None and visible_id != expected_asset_id:
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    if draft.revision != expected_revision and (expected_revision > draft.revision or visible_id != expected_asset_id
            or (asset is None and expected_asset_id is None)):
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    if asset is None:
        asset = await reserve_asset(service, draft, side, unfinished, idempotency_key=idempotency_key,
            content=content, content_type=content_type, checksum=checksum)
    asset_id, key = asset.id, asset.object_key
    await service.session.commit()  # Durable owner exists before bytes can exist.
    draft_id = draft.id
    async with asyncio.timeout(30):
        await storage.upload_file(content, key, content_type)
    try:
        draft = await authorize()
    except Exception:
        await cleanup_failed_write(service, asset_id, draft_id)
        raise
    asset = await service.session.scalar(select(Asset).where(Asset.id == asset_id, Asset.draft_id == draft.id,
        Asset.agency_id == draft.agency_id, Asset.company_id == draft.company_id).with_for_update().execution_options(populate_existing=True))
    if asset is None or asset.state not in {"uploading", "ready"}:
        await cleanup_failed_write(service, asset_id, draft_id)
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    if asset.state == "ready" and asset.is_current:
        result = await draft_view(service, draft)
        await service.session.commit()
        return result
    return await publish_asset(service, draft, asset, previous_id)
