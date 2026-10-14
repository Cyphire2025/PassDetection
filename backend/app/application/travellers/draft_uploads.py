"""Reserve before upload; publish one current side after a checked private write."""
import asyncio
import hashlib
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import func, select

from app.application.travellers.claims import ReturningClaims
from app.application.travellers.draft_contracts import DraftSide, DraftView
from app.application.travellers.draft_store import DraftStore
from app.application.travellers.drafts import draft_payload, draft_view, require_draft
from app.application.travellers.errors import ReuseError, ReuseReason
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftAssetModel as Asset,
)
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerReturningDraftModel as Draft,
)
from app.infrastructure.documents.storage_cleanup import stage_storage_cleanup_jobs

MAX_DRAFT_UPLOADS = 30
MAX_DRAFT_IMAGE_BYTES = 10 * 1024 * 1024


class DraftStorage(Protocol):
    async def upload_file(self, file_content: bytes, file_name: str, content_type: str) -> str: ...


def discard_asset(service: DraftStore, asset: Asset) -> None:
    if asset.state == "adopted":
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    asset.is_current, asset.state = False, "discarded"
    stage_storage_cleanup_jobs(service.session, agency_id=asset.agency_id, source="returning_draft_discard",
        context_id=str(asset.id), storage_keys=[asset.object_key])


async def upload_draft_document(service: ReturningClaims, token: str, secret: str, *, side: DraftSide,
    expected_revision: int, idempotency_key: str, content: bytes, content_type: str, storage: DraftStorage,
) -> DraftView:
    return await store_draft_document(service, authorize=lambda: require_draft(service, token, secret), side=side,
        expected_revision=expected_revision, idempotency_key=idempotency_key, content=content, content_type=content_type, storage=storage)


async def store_draft_document(service: DraftStore, *, authorize: Callable[[], Awaitable[Draft]], side: DraftSide,
    expected_revision: int, idempotency_key: str, content: bytes, content_type: str, storage: DraftStorage,
) -> DraftView:
    if not content or len(content) > MAX_DRAFT_IMAGE_BYTES or content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    draft = await authorize()
    checksum = hashlib.sha256(content).hexdigest()
    asset = await service.session.scalar(select(Asset).where(Asset.draft_id == draft.id,
        Asset.agency_id == draft.agency_id, Asset.company_id == draft.company_id,
        Asset.idempotency_key == idempotency_key).with_for_update())
    if asset:
        if asset.side != side or asset.checksum != checksum or asset.content_type != content_type or asset.expected_revision != expected_revision:
            raise ReuseError(ReuseReason.REVISION_CONFLICT)
        if asset.state == "ready" and asset.is_current:
            result = await draft_view(service, draft)
            await service.session.commit()
            return result
        if asset.state != "uploading":
            raise ReuseError(ReuseReason.REVISION_CONFLICT)
    else:
        if draft.revision != expected_revision:
            raise ReuseError(ReuseReason.REVISION_CONFLICT)
        count = await service.session.scalar(select(func.count()).select_from(Asset).where(Asset.draft_id == draft.id))
        if (count or 0) >= MAX_DRAFT_UPLOADS:
            raise ReuseError(ReuseReason.RATE_LIMITED)
        asset_id = uuid.uuid4()
        suffix = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[content_type]
        asset = Asset(id=asset_id, agency_id=draft.agency_id, company_id=draft.company_id, draft_id=draft.id,
            side=side, object_key=f"returning-drafts/{draft.agency_id}/{draft.id}/{asset_id}.{suffix}",
            checksum=checksum, byte_size=len(content), content_type=content_type, idempotency_key=idempotency_key,
            state="uploading", is_current=False, expected_revision=expected_revision, fields_revision=draft.fields_revision,
            extraction_status="none", attempts=0, available_at=datetime.now(UTC))
        service.session.add(asset)
    asset_id, key = asset.id, asset.object_key
    await service.session.commit()  # Durable owner exists before bytes can exist.
    async with asyncio.timeout(30):
        await storage.upload_file(content, key, content_type)
    draft = await authorize()
    asset = await service.session.scalar(select(Asset).where(Asset.id == asset_id, Asset.draft_id == draft.id,
        Asset.agency_id == draft.agency_id, Asset.company_id == draft.company_id).with_for_update().execution_options(populate_existing=True))
    if asset is None or asset.state not in {"uploading", "ready"}:
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    if asset.state == "ready" and asset.is_current:
        result = await draft_view(service, draft)
        await service.session.commit()
        return result
    if draft.revision != expected_revision:
        discard_asset(service, asset)
        await service.session.commit()
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    previous = await service.session.scalar(select(Asset).where(Asset.draft_id == draft.id,
        Asset.side == side, Asset.is_current.is_(True)).with_for_update())
    if previous:
        discard_asset(service, previous)
        await service.session.flush()
    asset.state, asset.is_current = "ready", True
    if side == "front":
        payload = draft_payload(service, draft)
        payload.passport_fields = {}
        draft.fields_revision += 1
        draft.payload_ciphertext = service.crypto.encrypt(payload.model_dump_json())
        asset.fields_revision, asset.extraction_status = draft.fields_revision, "pending"
    draft.revision += 1
    result = await draft_view(service, draft)
    await service.session.commit()
    return result
