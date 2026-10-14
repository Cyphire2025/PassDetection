"""Lease-fenced draft OCR and expiry; no canonical profiles or history writes.

One image <=10MiB per worker, globally <=2 extraction leases, <=3 attempts.
Expiry stages <=100 isolated asset deletions per tick in the existing outbox.
"""
import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.interfaces.passport_extraction import IPassportExtractionService
from app.application.travellers.draft_contracts import DraftPayload
from app.core.config.traveller_reuse import get_traveller_reuse_settings
from app.domain.services.traveller_verification import utc
from app.domain.value_objects.passport_document_classification import (
    is_accepted_passport_information_page,
)
from app.domain.value_objects.passport_fields import REVIEWABLE_PASSPORT_FIELDS
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
from app.infrastructure.documents.storage_cleanup import stage_storage_cleanup_jobs
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.infrastructure.travellers.draft_extraction import (
    DraftExtractionDeferred,
    draft_classification,
    extract_draft_front,
)


@dataclass(frozen=True)
class DraftExtractionClaim:
    asset_id: uuid.UUID
    draft_id: uuid.UUID
    key: str
    size: int
    checksum: str
    media: str
    lease: datetime


async def reserve_extraction(factory: async_sessionmaker[AsyncSession]) -> DraftExtractionClaim | None:
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        if session.bind and session.bind.dialect.name == "postgresql":
            await session.execute(text("SELECT pg_advisory_xact_lock(73196421)"))
        exhausted = select(Asset.id).where(Asset.extraction_status == "running", Asset.attempts >= 3,
            Asset.lease_expires_at <= now).order_by(Asset.available_at, Asset.id).limit(2).with_for_update(skip_locked=True)
        await session.execute(update(Asset).where(Asset.id.in_(exhausted)).values(extraction_status="failed", lease_expires_at=None))
        running = await session.scalar(select(func.count()).select_from(Asset).where(Asset.extraction_status == "running", Asset.lease_expires_at > now))
        if (running or 0) >= 2:
            return None
        row = await session.scalar(select(Asset).join(Draft, Draft.id == Asset.draft_id).where(
            Asset.state == "ready", Asset.is_current.is_(True), Asset.extraction_status.in_(("pending", "running")),
            Asset.available_at <= now, Asset.attempts < 3, Draft.status == "active", Draft.expires_at > now,
            or_(Asset.lease_expires_at.is_(None), Asset.lease_expires_at <= now),
        ).order_by(Asset.available_at, Asset.id).limit(1).with_for_update(skip_locked=True, of=Asset))
        if row is None:
            return None
        row.attempts += 1
        row.extraction_status, row.lease_expires_at = "running", now + timedelta(seconds=60)
        row.available_at = row.lease_expires_at
        return DraftExtractionClaim(row.id, row.draft_id, row.object_key, row.byte_size, row.checksum, row.content_type, row.lease_expires_at)


async def run_draft_extraction(*, factory: async_sessionmaker[AsyncSession] = AsyncSessionFactory,
    storage: MinioStorageRepository | None = None, extractor: IPassportExtractionService | None = None,
    crypto: TravellerReuseCrypto | None = None,
) -> int:
    claim = await reserve_extraction(factory)
    if claim is None:
        return 0
    storage = storage or MinioStorageRepository()
    crypto = crypto or TravellerReuseCrypto(get_traveller_reuse_settings())
    fields: dict[str, str] | None = None
    classification: dict[str, object] = {}
    deferred = False
    try:
        async with asyncio.timeout(35):
            content = bytearray()
            async for chunk in storage.stream_file(claim.key, start=0, expected_bytes=claim.size):
                content.extend(chunk)
            if hashlib.sha256(content).hexdigest() != claim.checksum:
                raise ValueError("draft_content_changed")
            result = await extractor.extract(bytes(content), filename="passport.jpg", content_type=claim.media) if extractor else await extract_draft_front(str(claim.asset_id), bytes(content), claim.media)
            classification = draft_classification(result.extracted_fields)
            fields = {key: value for key, value in result.extracted_fields.items()
                if key in REVIEWABLE_PASSPORT_FIELDS and isinstance(value, str) and len(value) <= 160}
    except DraftExtractionDeferred:
        deferred = True
    except Exception:
        fields = None  # Never log provider output, document keys or extracted data.
    async with factory() as session, session.begin():
        draft = await session.scalar(select(Draft).where(Draft.id == claim.draft_id).with_for_update())
        asset = await session.scalar(select(Asset).where(Asset.id == claim.asset_id).with_for_update())
        if asset is None or asset.lease_expires_at is None or utc(asset.lease_expires_at) != claim.lease:
            return 0
        if draft is None or draft.status != "active" or utc(draft.expires_at) <= datetime.now(UTC) or not asset.is_current or asset.state != "ready":
            return 0
        asset.lease_expires_at = None
        if deferred:
            asset.attempts -= 1
            asset.extraction_status, asset.available_at = "pending", datetime.now(UTC) + timedelta(seconds=5)
        elif fields is None:
            asset.extraction_status = "failed" if asset.attempts >= 3 else "pending"
            asset.available_at = datetime.now(UTC) + timedelta(seconds=10 * asset.attempts)
        else:
            extracted = DraftPayload(passport_fields=fields)
            asset.extraction_ciphertext = crypto.encrypt(extracted.model_dump_json())
            asset.classification_ciphertext = crypto.encrypt(json.dumps(classification, sort_keys=True))
            asset.extraction_status = "succeeded" if is_accepted_passport_information_page(classification) else "failed"
            if asset.extraction_status == "succeeded" and draft.fields_revision == asset.fields_revision:
                payload = DraftPayload.model_validate_json(crypto.decrypt(draft.payload_ciphertext))
                payload.passport_fields = fields
                draft.payload_ciphertext = crypto.encrypt(payload.model_dump_json())
                draft.fields_revision += 1
        draft.revision += 1
    return 1


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
            asset.state, asset.is_current = "discarded", False
            asset.extraction_ciphertext = None
            asset.classification_ciphertext = None
            stage_storage_cleanup_jobs(session, agency_id=asset.agency_id, source="returning_draft_discard",
                context_id=str(asset.id), storage_keys=[asset.object_key])
        return len(assets)
