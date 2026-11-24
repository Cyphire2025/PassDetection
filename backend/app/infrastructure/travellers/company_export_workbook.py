"""Sequential bounded private row-page assembly with repeated authority checks."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.entities.entities import User
from app.domain.services.traveller_verification import utc
from app.infrastructure.database.company_data_export_models import CompanyDataExportJobModel as Job
from app.infrastructure.database.company_data_export_models import (
    CompanyDataExportPartModel as Part,
)
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.infrastructure.travellers.company_export_native_work import run_export_native_work
from app.infrastructure.travellers.company_export_render import WorkbookAssembly, read_rows


async def assemble_workbook(
    factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    storage: MinioStorageRepository,
    crypto: TravellerReuseCrypto,
    token: uuid.UUID,
    *,
    export_authority: Callable[[AsyncSession, Job], Awaitable[User]],
) -> tuple[bytes, int]:
    workbook = WorkbookAssembly()
    after = 0
    try:
        while True:
            async with factory() as session:
                job = await session.get(Job, job_id)
                if (
                    job is None
                    or job.lease_token != token
                    or not job.lease_expires_at
                    or utc(job.lease_expires_at) <= datetime.now(UTC)
                ):
                    raise ValueError("export_lease_changed")
                await export_authority(session, job)
                parts = list(
                    (
                        await session.scalars(
                            select(Part)
                            .where(
                                Part.job_id == job_id,
                                Part.part_kind == "rows",
                                Part.part_number > after,
                            )
                            .order_by(Part.part_number)
                            .limit(25)
                        )
                    ).all()
                )
            if not parts:
                break
            for part in parts:
                rows = await read_rows(storage, part.object_key, part.byte_size, crypto)
                await run_export_native_work(lambda: workbook.append(rows))
                after = part.part_number
        return await run_export_native_work(workbook.finish), workbook.count
    finally:
        await run_export_native_work(workbook.close)
