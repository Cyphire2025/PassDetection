"""Stage at most 100 private export objects for existing durable deletion."""

from datetime import UTC, datetime

from sqlalchemy import literal, select, union_all, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.database.company_data_export_models import CompanyDataExportJobModel as Job
from app.infrastructure.database.company_data_export_models import (
    CompanyDataExportPartModel as Part,
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.documents.storage_cleanup import stage_storage_cleanup_jobs


async def expire_export_parts(*, session_factory: async_sessionmaker[AsyncSession] = AsyncSessionFactory) -> int:
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        # Both branches seek their own queue index; no scan through retained
        # expired receipts. Even jobs with no output receive a terminal cursor.
        expired = select(Job.id).where(Job.status != literal("expired", literal_execute=True), Job.expires_at <= now).order_by(Job.expires_at, Job.id).limit(100).subquery()
        cancelled = select(Job.id).where(Job.status.in_(("cancelled", "failed"))).order_by(Job.available_at, Job.id).limit(100).subquery()
        candidates = union_all(select(expired.c.id), select(cancelled.c.id)).subquery()
        identifiers = list((await session.scalars(select(candidates.c.id).distinct().limit(100))).all())
        if not identifiers:
            return 0
        rows = list((await session.execute(select(Part, Job.lease_expires_at).join(Job, Job.id == Part.job_id).where(
            Part.job_id.in_(identifiers), Part.purged_at.is_(None))
            .order_by(Part.job_id, Part.id).limit(100).with_for_update(of=Part, skip_locked=True))).all())
        for part, lease_expires_at in rows:
            stage_storage_cleanup_jobs(session, agency_id=part.agency_id, source="company_data_export_expiry",
                context_id=str(part.id), storage_keys=[part.object_key], not_before=lease_expires_at)
            part.purged_at = now
        await session.flush()
        unpurged = select(Part.id).where(Part.job_id == Job.id, Part.purged_at.is_(None)).exists()
        await session.execute(update(Job).where(Job.id.in_(identifiers), ~unpurged).values(status="expired"))
        return len(rows)
