"""Current durable search/job lease queries."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.my_photos_models import MyPhotoJobModel, MyPhotoSearchRunModel
from app.infrastructure.my_photos.search_job_contracts import _SearchClaim
from app.infrastructure.my_photos.search_job_policy import _utc


async def _locked_claim_rows(
    session: AsyncSession, claim: _SearchClaim
) -> tuple[MyPhotoSearchRunModel | None, MyPhotoJobModel | None]:
    search = (
        await session.execute(
            select(MyPhotoSearchRunModel)
            .where(
                MyPhotoSearchRunModel.id == claim.search_run_id,
                MyPhotoSearchRunModel.status == "searching",
                MyPhotoSearchRunModel.lease_owner == claim.lease_owner,
                MyPhotoSearchRunModel.lease_expires_at > datetime.now(tz=UTC),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    job = (
        await session.execute(
            select(MyPhotoJobModel)
            .where(
                MyPhotoJobModel.id == claim.job_id,
                MyPhotoJobModel.status == "running",
                MyPhotoJobModel.lease_owner == claim.lease_owner,
                MyPhotoJobModel.cancellation_requested_at.is_(None),
                MyPhotoJobModel.lease_expires_at > datetime.now(tz=UTC),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    now = datetime.now(tz=UTC)
    if (
        search is not None
        and job is not None
        and (
            search.lease_expires_at is None
            or job.lease_expires_at is None
            or _utc(search.lease_expires_at) <= now
            or _utc(job.lease_expires_at) <= now
        )
    ):
        return None, None
    return search, job
