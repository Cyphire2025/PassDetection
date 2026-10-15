"""One leased export page per tick, controlled retries, deterministic private parts.

Global admission is one lease; pages <=250 people or 16 images/64 MiB. A crash
repeats only its current page. Each output key is reserved before storage; its cursor commits after storage.
Workbook assembly reads encrypted pages sequentially and caps 100,000 people.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.companies.data_exports import require_export
from app.application.companies.export_source import (
    people_export_page,
    retained_image_page,
    source_image_page,
)
from app.application.companies.source_documents import SOURCE_SIDES
from app.application.travellers.asset_policy import (
    MAX_PRIVATE_DOCUMENT_BYTES,
    PRIVATE_DOCUMENT_TYPES,
)
from app.core.config.settings import get_settings
from app.core.config.traveller_reuse import get_traveller_reuse_settings
from app.domain.entities.entities import User
from app.domain.services.traveller_verification import utc
from app.infrastructure.database.company_data_export_models import CompanyDataExportJobModel as Job
from app.infrastructure.database.company_data_export_models import (
    CompanyDataExportPartModel as Part,
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.repositories.user_repository import UserRepository
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.infrastructure.travellers.company_export_render import (
    WorkbookAssembly,
    encode_rows,
    read_rows,
    render_image_volume,
)

LEASE_SECONDS = 240
PAGE_TIMEOUT_SECONDS = 180
MAX_ATTEMPTS = 5


async def reserve_export(factory: async_sessionmaker[AsyncSession]) -> tuple[uuid.UUID, uuid.UUID] | None:
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            if not await session.scalar(text("SELECT pg_try_advisory_xact_lock(913704, 1)")):
                return None
        running = await session.scalar(select(select(Job.id).where(Job.lease_expires_at > now).exists()))
        if running:
            return None
        job = await session.scalar(select(Job).where(Job.status.in_(("queued", "running")), Job.available_at <= now,
            or_(Job.lease_expires_at.is_(None), Job.lease_expires_at <= now)).order_by(Job.available_at, Job.id)
            .limit(1).with_for_update(skip_locked=True))
        if job is None:
            return None
        if job.attempt_count >= MAX_ATTEMPTS or utc(job.expires_at) <= now:
            job.status, job.last_error_code = "failed", "attempts_or_lifetime_exhausted"
            return None
        provider = get_settings().s3
        envelope = (provider.connect_timeout_seconds + provider.read_timeout_seconds) * provider.max_attempts + 30
        job.lease_token, job.lease_expires_at = uuid.uuid4(), now + timedelta(seconds=max(LEASE_SECONDS, PAGE_TIMEOUT_SECONDS + envelope))
        job.status = "running"
        job.attempt_count += 1
        return job.id, job.lease_token


async def export_authority(session: AsyncSession, job: Job) -> User:
    user = await UserRepository(session).get_by_id(job.requested_by_user_id)
    if user is None or not user.is_active or user.credential_state != "active":
        raise ValueError("export_actor_unavailable")
    await require_export(session, user=user, company_id=job.company_id, agency_id=job.agency_id, job_id=job.id)
    if job.status not in {"running", "queued"}:
        raise ValueError("export_cancelled")
    return user


async def assemble_workbook(factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID,
    storage: MinioStorageRepository, crypto: TravellerReuseCrypto, token: uuid.UUID,
) -> tuple[bytes, int]:
    workbook = WorkbookAssembly()
    after = 0
    try:
        while True:
            async with factory() as session:
                job = await session.get(Job, job_id)
                if job is None or job.lease_token != token or not job.lease_expires_at or utc(job.lease_expires_at) <= datetime.now(UTC):
                    raise ValueError("export_lease_changed")
                await export_authority(session, job)
                parts = list((await session.scalars(select(Part).where(Part.job_id == job_id,
                    Part.part_kind == "rows", Part.part_number > after).order_by(Part.part_number).limit(25))).all())
            if not parts:
                break
            for part in parts:
                rows = await read_rows(storage, part.object_key, part.byte_size, crypto)
                await asyncio.to_thread(workbook.append, rows)
                after = part.part_number
        return await asyncio.to_thread(workbook.finish), workbook.count
    finally:
        await asyncio.to_thread(workbook.close)


async def process_export_page(factory: async_sessionmaker[AsyncSession], identifier: uuid.UUID,
    token: uuid.UUID, storage: MinioStorageRepository, crypto: TravellerReuseCrypto,
) -> None:
    async with factory() as session:
        job = await session.get(Job, identifier)
        if job is None or job.lease_token != token or not job.lease_expires_at or utc(job.lease_expires_at) <= datetime.now(UTC):
            return
        user = await export_authority(session, job)
        previous_cursor, phase = job.cursor, job.phase
        last_id, count, content = previous_cursor, 0, None
        part_kind, media = "rows", "application/octet-stream"
        if phase == "people":
            rows, last_id = await people_export_page(session, job, user, crypto)
            if rows:
                content, count = encode_rows(rows, crypto), len(rows)
            else:
                phase, last_id = "finalize", None
        elif phase == "retained_images" or phase.startswith("source_"):
            images = await retained_image_page(session, job, user) if phase == "retained_images" else await source_image_page(session, job, user)
            if not images:
                phases = ["retained_images", *(f"source_{side}" for side in SOURCE_SIDES), "finalize"]
                phase, last_id = phases[phases.index(phase) + 1], None
            else:
                # Session closes before storage I/O below.
                part_kind, media = "images", "application/zip"
        part_number = job.part_count + 1
        key = f"company-data-exports/{job.agency_id}/{job.company_id}/{job.id}/{part_number}"
    if (job.phase == "retained_images" or job.phase.startswith("source_")) and phase == job.phase:
        verified = []
        for row in images:
            if row.size == -1:
                metadata = await storage.stat_file(row.key)
                if metadata.content_type not in PRIVATE_DOCUMENT_TYPES or not 0 < metadata.size_bytes <= MAX_PRIVATE_DOCUMENT_BYTES:
                    raise ValueError("source_document_outside_export_budget")
                row = replace(row, size=metadata.size_bytes, content_type=metadata.content_type or "")
            verified.append(row)
        if any(row.size > 0 or row.key for row in verified):
            rendered = await render_image_volume(verified, storage)
            content, count = rendered.content, rendered.count
            last_id = uuid.UUID(rendered.last_id) if rendered.last_id else None
        else:
            last_id = verified[-1].identifier
    if job.phase == "finalize" and job.kind == "excel":
        content, count = await assemble_workbook(factory, job.id, storage, crypto, token)
        part_kind, media = "workbook", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if content is not None:
        await reserve_part(factory, identifier, token, previous_cursor, part_number,
            part_kind, key, media, content, count)
        await storage.upload_file(content, key, media)
    async with factory() as session, session.begin():
        current = await session.scalar(select(Job).where(Job.id == identifier).with_for_update())
        if current is None or current.lease_token != token or current.cursor != previous_cursor:
            return
        await export_authority(session, current)
        if content is not None:
            current.part_count += 1
            if part_kind != "workbook":
                current.processed_count += count
        completed = job.phase == "finalize"
        current.cursor, current.phase = last_id, phase
        current.status = "succeeded" if completed else "queued"
        current.available_at = datetime.now(UTC)
        current.attempt_count, current.last_error_code = 0, None
        current.lease_token, current.lease_expires_at = None, None
        if completed:
            current.completed_at = datetime.now(UTC)
            current.expires_at = current.completed_at + timedelta(hours=24)


async def reserve_part(factory: async_sessionmaker[AsyncSession], identifier: uuid.UUID,
    token: uuid.UUID, cursor: uuid.UUID | None, number: int, kind: str, key: str,
    media: str, content: bytes, count: int,
) -> None:
    """Own the deterministic destination before any provider write can outlive us.

    A pending receipt is not downloadable. Retrying the uncommitted page replaces
    only its receipt metadata; committed parts are immutable. Expiry cleanup sees
    even a write whose acknowledgement was lost and waits out its provider lease.
    """
    async with factory() as session, session.begin():
        job = await session.scalar(select(Job).where(Job.id == identifier).with_for_update())
        if (job is None or job.lease_token != token or job.cursor != cursor or job.part_count + 1 != number
                or not job.lease_expires_at or utc(job.lease_expires_at) <= datetime.now(UTC)):
            raise ValueError("export_lease_changed")
        await export_authority(session, job)
        part = await session.scalar(select(Part).where(Part.job_id == identifier, Part.part_number == number))
        if part is None:
            part = Part(agency_id=job.agency_id, company_id=job.company_id, job_id=job.id,
                part_number=number, object_key=key)
            session.add(part)
        elif part.object_key != key or part.purged_at is not None:
            raise ValueError("export_part_ownership_changed")
        provider = get_settings().s3
        envelope = (provider.connect_timeout_seconds + provider.read_timeout_seconds) * provider.max_attempts + 30
        job.lease_expires_at = max(utc(job.lease_expires_at or datetime.now(UTC)),
            datetime.now(UTC) + timedelta(seconds=envelope))
        part.part_kind, part.content_type = kind, media
        part.byte_size, part.content_sha256 = len(content), hashlib.sha256(content).hexdigest()
        part.record_count = count


async def run_company_export_tick(*, session_factory: async_sessionmaker[AsyncSession] = AsyncSessionFactory,
    storage: MinioStorageRepository | None = None, crypto: TravellerReuseCrypto | None = None,
) -> int:
    claimed = await reserve_export(session_factory)
    if claimed is None:
        return 0
    identifier, token = claimed
    try:
        async with asyncio.timeout(PAGE_TIMEOUT_SECONDS):
            await process_export_page(session_factory, identifier, token, storage or MinioStorageRepository(),
                crypto or TravellerReuseCrypto(get_traveller_reuse_settings()))
        return 1
    except Exception:
        async with session_factory() as session, session.begin():
            job = await session.scalar(select(Job).where(Job.id == identifier).with_for_update())
            if job is not None and job.lease_token == token and job.status == "running":
                job.status = "failed" if job.attempt_count >= MAX_ATTEMPTS else "queued"
                job.last_error_code = "export_page_failed"
                job.available_at = max(utc(job.lease_expires_at or datetime.now(UTC)),
                    datetime.now(UTC) + timedelta(seconds=min(300, 5 * 2 ** job.attempt_count)))
                # A timed-out provider thread may still run; retain the lease
                # until its bounded provider envelope expires.
        return 0
