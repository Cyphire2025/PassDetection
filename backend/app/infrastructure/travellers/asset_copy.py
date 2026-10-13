"""Server-side copies into independent private ownership, with bounded leases.

No document bytes are loaded into the worker. At most two unexpired copy leases
exist globally in PostgreSQL. Retries reuse the same private destination key.
Source extraction and current retention authority are rechecked before copying
and before publication. A crash consumes an attempt and leaves an expiring lease.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.travellers.asset_policy import (
    MAX_PRIVATE_DOCUMENT_BYTES,
    PRIVATE_DOCUMENT_SUFFIXES,
    PRIVATE_DOCUMENT_TYPES,
)
from app.application.travellers.accepted_source import retained_source_is_current
from app.application.travellers.retained_authority import has_retained_authority
from app.core.config.settings import get_settings
from app.domain.services.traveller_verification import utc
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentAssetModel,
    TravellerDocumentRevisionModel,
    TravellerProfileModel,
)
from app.infrastructure.documents.storage_cleanup import stage_storage_cleanup_jobs
from app.infrastructure.storage.minio_repository import (
    MinioStorageRepository,
    ObjectIntegrityMetadata,
)
from app.infrastructure.travellers.staff_record_asset_copy import has_staff_copy_authority

MAX_COPY_ATTEMPTS = 5
COPY_LEASE_SECONDS = 90


class AssetStorage(Protocol):
    async def stat_file(self, key: str) -> ObjectIntegrityMetadata: ...
    async def copy_file(self, source_key: str, destination_key: str) -> str: ...


@dataclass(frozen=True, slots=True)
class CopyClaim:
    asset_id: uuid.UUID
    source_key: str
    destination_key: str
    lease_expires_at: datetime


async def _has_copy_authority(session: AsyncSession, asset: TravellerDocumentAssetModel, now: datetime) -> bool:
    """One indexed bounded join checks both initial and publication authority."""
    row = (await session.execute(select(TravellerProfileModel, TravellerDocumentRevisionModel,
        PassportSubmissionModel, ClientGroupModel).select_from(TravellerDocumentRevisionModel)
        .join(TravellerProfileModel, TravellerProfileModel.id == TravellerDocumentRevisionModel.traveller_id)
        .join(PassportSubmissionModel, PassportSubmissionModel.id == TravellerDocumentRevisionModel.source_submission_id)
        .join(ClientGroupModel, ClientGroupModel.id == PassportSubmissionModel.group_id)
        .where(TravellerDocumentRevisionModel.id == asset.document_revision_id))).first()
    if row is None:
        return await has_staff_copy_authority(session, asset, now)
    person, revision, source, group = row
    scope = (asset.agency_id, asset.company_id, asset.traveller_id)
    return bool(
        (person.agency_id, person.company_id, person.id) == scope
        and (revision.agency_id, revision.company_id, revision.traveller_id) == scope
        and revision.passport_id == asset.passport_id and revision.status == "accepted"
        and source.agency_id == asset.agency_id and source.group_id == revision.source_group_id
        and group.agency_id == asset.agency_id and group.deleted_at is None and group.status != "deleted"
        and retained_source_is_current(revision, source)
        and source.extraction_revision == asset.source_extraction_revision
        and has_retained_authority(person)
        and (person.retention_until is None or utc(person.retention_until) > now)
        and asset.retention_basis and asset.purged_at is None
        and (asset.retention_until is None or utc(asset.retention_until) > now)
        and asset.source_object_key and asset.object_key
        and asset.source_object_key in {source.image_s3_key, source.passport_back_s3_key,
            source.passport_cover_s3_key, source.passport_back_cover_s3_key, source.passport_photo_s3_key}
    )


async def _reserve(session: AsyncSession, now: datetime) -> CopyClaim | None:
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        if not await session.scalar(text("SELECT pg_try_advisory_xact_lock(913701, 1)")):
            return None
    running = await session.scalar(select(func.count()).select_from(TravellerDocumentAssetModel).where(
        TravellerDocumentAssetModel.lease_expires_at > now,
    ))
    if int(running or 0) >= 2:
        return None
    asset = await session.scalar(select(TravellerDocumentAssetModel).where(
        TravellerDocumentAssetModel.availability == "pending",
        or_(TravellerDocumentAssetModel.next_attempt_at.is_(None), TravellerDocumentAssetModel.next_attempt_at <= now),
        or_(TravellerDocumentAssetModel.lease_expires_at.is_(None), TravellerDocumentAssetModel.lease_expires_at <= now),
    ).order_by(TravellerDocumentAssetModel.next_attempt_at, TravellerDocumentAssetModel.id)
        .limit(1).with_for_update(skip_locked=True))
    if asset is None:
        return None
    if asset.copy_attempt_count >= MAX_COPY_ATTEMPTS:
        asset.availability, asset.lease_expires_at = "unreadable", None
        return None
    if not await _has_copy_authority(session, asset, now) or not asset.source_object_key or not asset.object_key:
        asset.availability, asset.lease_expires_at = "unreadable", None
        return None
    asset.copy_attempt_count += 1
    settings = get_settings().s3
    provider_envelope = (settings.connect_timeout_seconds + settings.read_timeout_seconds) * settings.max_attempts + 30
    asset.lease_expires_at = now + timedelta(seconds=max(COPY_LEASE_SECONDS, provider_envelope))
    return CopyClaim(asset.id, asset.source_object_key, asset.object_key, asset.lease_expires_at)


async def _bind_destination(factory: async_sessionmaker[AsyncSession], claim: CopyClaim,
    metadata: ObjectIntegrityMetadata,
) -> CopyClaim:
    """Persist a MIME-derived stable destination before external I/O can create it."""
    async with factory() as session, session.begin():
        asset = await session.scalar(select(TravellerDocumentAssetModel).where(
            TravellerDocumentAssetModel.id == claim.asset_id).with_for_update())
        if (asset is None or asset.lease_expires_at is None or utc(asset.lease_expires_at) != claim.lease_expires_at
                or not await _has_copy_authority(session, asset, datetime.now(UTC))):
            raise ValueError("retained_document_copy_authority_changed")
        destination = (f"travellers/{asset.agency_id}/{asset.company_id}/{asset.traveller_id}/"
            f"{asset.document_revision_id}/{asset.id}{PRIVATE_DOCUMENT_SUFFIXES[metadata.content_type or '']}")
        # A previous attempt may have begun writing the prior MIME destination.
        # Freeze that type after its first reservation; do not create orphan keys.
        if asset.content_type in PRIVATE_DOCUMENT_TYPES and asset.content_type != metadata.content_type:
            raise ValueError("retained_document_content_type_changed")
        asset.object_key, asset.content_type = destination, metadata.content_type or "application/octet-stream"
        return CopyClaim(claim.asset_id, claim.source_key, destination, claim.lease_expires_at)


async def copy_next_asset(
    *, session_factory: async_sessionmaker[AsyncSession] = AsyncSessionFactory,
    storage: AssetStorage | None = None,
) -> bool:
    async with session_factory() as session, session.begin():
        claim = await _reserve(session, datetime.now(UTC))
    if claim is None:
        return False
    storage = storage or MinioStorageRepository()
    metadata = None
    succeeded = False
    timed_out = False
    try:
        async with asyncio.timeout(45):
            metadata = await storage.stat_file(claim.source_key)
            if metadata.size_bytes <= 0 or metadata.size_bytes > MAX_PRIVATE_DOCUMENT_BYTES:
                raise ValueError("retained_document_size_limit")
            if metadata.content_type not in PRIVATE_DOCUMENT_TYPES:
                raise ValueError("retained_document_content_type")
            claim = await _bind_destination(session_factory, claim, metadata)
            await storage.copy_file(claim.source_key, claim.destination_key)
            copied = await storage.stat_file(claim.destination_key)
            if copied.size_bytes != metadata.size_bytes:
                raise ValueError("retained_document_size_mismatch")
            if copied.content_type != metadata.content_type:
                raise ValueError("retained_document_content_type_mismatch")
            if metadata.checksum_sha256 and copied.checksum_sha256 != metadata.checksum_sha256:
                raise ValueError("retained_document_checksum_mismatch")
            succeeded = True
    except TimeoutError:
        timed_out = True
    except Exception:
        # No provider message, source key or content enters logs or stored errors.
        succeeded = False
    async with session_factory() as session, session.begin():
        asset = await session.scalar(select(TravellerDocumentAssetModel).where(
            TravellerDocumentAssetModel.id == claim.asset_id,
        ).with_for_update())
        if asset is None:
            return False
        lease = asset.lease_expires_at
        if lease is not None and lease.tzinfo is None:
            lease = lease.replace(tzinfo=UTC)
        if lease != claim.lease_expires_at:
            return False
        valid = await _has_copy_authority(session, asset, datetime.now(UTC))
        if succeeded and valid and metadata is not None:
            asset.availability = "available"
            asset.byte_size = metadata.size_bytes
            asset.content_sha256 = metadata.checksum_sha256
            asset.content_type = metadata.content_type or "application/octet-stream"
            asset.source_object_key = None
        elif not valid:
            asset.availability = "purged"
            asset.purged_at = datetime.now(UTC)
            stage_storage_cleanup_jobs(session, agency_id=asset.agency_id, source="traveller_copy_revoked",
                context_id=str(asset.id), storage_keys=[claim.destination_key],
                not_before=claim.lease_expires_at if timed_out else None)
        elif asset.copy_attempt_count >= MAX_COPY_ATTEMPTS:
            asset.availability = "unreadable"
        else:
            asset.next_attempt_at = datetime.now(UTC) + timedelta(seconds=min(300, 5 * 2 ** asset.copy_attempt_count))
        if timed_out:
            # asyncio cannot kill a boto thread; preserve admission until the
            # configured provider timeout envelope has elapsed.
            asset.next_attempt_at = claim.lease_expires_at
        else:
            asset.lease_expires_at = None
        return succeeded and valid
