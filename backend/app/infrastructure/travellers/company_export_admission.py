"""Locked global export admission and deterministic private-write receipts.

Only one global lease admits a page. A reserved output key remains owned even
when a provider write outlives its acknowledgement; expiry waits out its lease.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.entities.entities import User
from app.domain.repositories.interfaces import IUserRepository
from app.domain.services.traveller_verification import utc
from app.infrastructure.database.company_data_export_models import CompanyDataExportJobModel as Job
from app.infrastructure.database.company_data_export_models import (
    CompanyDataExportPartModel as Part,
)


async def reserve_export(
    factory: async_sessionmaker[AsyncSession],
    *,
    lease_seconds: int,
    page_timeout_seconds: int,
    max_attempts: int,
    write_envelope: Callable[[], float],
) -> tuple[uuid.UUID, uuid.UUID] | None:
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            if not await session.scalar(text("SELECT pg_try_advisory_xact_lock(913704, 1)")):
                return None
        running = await session.scalar(
            select(select(Job.id).where(Job.lease_expires_at > now).exists())
        )
        if running:
            return None
        job = await session.scalar(
            select(Job)
            .where(
                Job.status.in_(("queued", "running")),
                Job.available_at <= now,
                or_(Job.lease_expires_at.is_(None), Job.lease_expires_at <= now),
            )
            .order_by(Job.available_at, Job.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        if job.attempt_count >= max_attempts or utc(job.expires_at) <= now:
            job.status, job.last_error_code = "failed", "attempts_or_lifetime_exhausted"
            return None
        envelope = write_envelope()
        job.lease_token, job.lease_expires_at = (
            uuid.uuid4(),
            now + timedelta(seconds=max(lease_seconds, page_timeout_seconds + envelope)),
        )
        job.status = "running"
        job.attempt_count += 1
        return job.id, job.lease_token


async def export_authority(
    session: AsyncSession,
    job: Job,
    *,
    users: IUserRepository,
    require_export: Callable[..., Awaitable[Job]],
) -> User:
    user = await users.get_by_id(job.requested_by_user_id)
    if user is None or not user.is_active or user.credential_state != "active":
        raise ValueError("export_actor_unavailable")
    await require_export(
        session, user=user, company_id=job.company_id, agency_id=job.agency_id, job_id=job.id
    )
    if job.status not in {"running", "queued"}:
        raise ValueError("export_cancelled")
    return user


async def reserve_part(
    factory: async_sessionmaker[AsyncSession],
    identifier: uuid.UUID,
    token: uuid.UUID,
    cursor: uuid.UUID | None,
    number: int,
    kind: str,
    key: str,
    media: str,
    content: bytes,
    count: int,
    *,
    write_envelope: Callable[[], float],
    export_authority: Callable[[AsyncSession, Job], Awaitable[User]],
) -> None:
    """Own the deterministic destination before any provider write can outlive us.

    A pending receipt is not downloadable. Retrying the uncommitted page replaces
    only its receipt metadata; committed parts are immutable. Expiry cleanup sees
    even a write whose acknowledgement was lost and waits out its provider lease.
    """
    async with factory() as session, session.begin():
        job = await session.scalar(select(Job).where(Job.id == identifier).with_for_update())
        if (
            job is None
            or job.lease_token != token
            or job.cursor != cursor
            or job.part_count + 1 != number
            or not job.lease_expires_at
            or utc(job.lease_expires_at) <= datetime.now(UTC)
        ):
            raise ValueError("export_lease_changed")
        await export_authority(session, job)
        part = await session.scalar(
            select(Part).where(Part.job_id == identifier, Part.part_number == number)
        )
        if part is None:
            part = Part(
                agency_id=job.agency_id,
                company_id=job.company_id,
                job_id=job.id,
                part_number=number,
                object_key=key,
            )
            session.add(part)
        elif part.object_key != key or part.purged_at is not None:
            raise ValueError("export_part_ownership_changed")
        envelope = write_envelope()
        job.lease_expires_at = max(
            utc(job.lease_expires_at or datetime.now(UTC)),
            datetime.now(UTC) + timedelta(seconds=envelope),
        )
        part.part_kind, part.content_type = kind, media
        part.byte_size, part.content_sha256 = len(content), hashlib.sha256(content).hexdigest()
        part.record_count = count


async def record_export_failure(
    factory: async_sessionmaker[AsyncSession],
    identifier: uuid.UUID,
    token: uuid.UUID,
    *,
    max_attempts: int,
) -> None:
    async with factory() as session, session.begin():
        job = await session.scalar(select(Job).where(Job.id == identifier).with_for_update())
        if job is not None and job.lease_token == token and job.status == "running":
            job.status = "failed" if job.attempt_count >= max_attempts else "queued"
            job.last_error_code = "export_page_failed"
            job.available_at = max(
                utc(job.lease_expires_at or datetime.now(UTC)),
                datetime.now(UTC) + timedelta(seconds=min(300, 5 * 2**job.attempt_count)),
            )
