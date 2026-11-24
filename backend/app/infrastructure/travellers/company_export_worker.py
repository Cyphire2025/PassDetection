"""Process one bounded company-export page under its admitted lease."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.companies.data_exports import require_export
from app.core.config.settings import get_settings
from app.core.config.traveller_reuse import get_traveller_reuse_settings
from app.core.storage_write_budget import s3_write_envelope_seconds
from app.domain.entities.entities import User
from app.infrastructure.database.company_data_export_models import CompanyDataExportJobModel as Job
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.repositories.user_repository import UserRepository
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.infrastructure.travellers import company_export_admission as _admission
from app.infrastructure.travellers import company_export_page as _page
from app.infrastructure.travellers import company_export_workbook as _workbook

LEASE_SECONDS = 240
PAGE_TIMEOUT_SECONDS = 180
MAX_ATTEMPTS = 5


def _storage_write_envelope() -> float:
    return s3_write_envelope_seconds(get_settings().s3)


async def reserve_export(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID] | None:
    return await _admission.reserve_export(
        factory,
        lease_seconds=LEASE_SECONDS,
        page_timeout_seconds=PAGE_TIMEOUT_SECONDS,
        max_attempts=MAX_ATTEMPTS,
        write_envelope=_storage_write_envelope,
    )


async def export_authority(session: AsyncSession, job: Job) -> User:
    return await _admission.export_authority(
        session,
        job,
        users=UserRepository(session),
        require_export=require_export,
    )


async def assemble_workbook(
    factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    storage: MinioStorageRepository,
    crypto: TravellerReuseCrypto,
    token: uuid.UUID,
) -> tuple[bytes, int]:
    return await _workbook.assemble_workbook(
        factory,
        job_id,
        storage,
        crypto,
        token,
        export_authority=export_authority,
    )


async def process_export_page(
    factory: async_sessionmaker[AsyncSession],
    identifier: uuid.UUID,
    token: uuid.UUID,
    storage: MinioStorageRepository,
    crypto: TravellerReuseCrypto,
) -> None:
    await _page.process_export_page(
        factory,
        identifier,
        token,
        storage,
        crypto,
        export_authority=export_authority,
        assemble_workbook=assemble_workbook,
        reserve_part=reserve_part,
    )


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
) -> None:
    await _admission.reserve_part(
        factory,
        identifier,
        token,
        cursor,
        number,
        kind,
        key,
        media,
        content,
        count,
        write_envelope=_storage_write_envelope,
        export_authority=export_authority,
    )


async def run_company_export_tick(
    *,
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionFactory,
    storage: MinioStorageRepository | None = None,
    crypto: TravellerReuseCrypto | None = None,
) -> int:
    claimed = await reserve_export(session_factory)
    if claimed is None:
        return 0
    identifier, token = claimed
    try:
        async with asyncio.timeout(PAGE_TIMEOUT_SECONDS):
            await process_export_page(
                session_factory,
                identifier,
                token,
                storage or MinioStorageRepository(),
                crypto or TravellerReuseCrypto(get_traveller_reuse_settings()),
            )
        return 1
    except Exception:
        await _admission.record_export_failure(
            session_factory,
            identifier,
            token,
            max_attempts=MAX_ATTEMPTS,
        )
        # A timed-out provider thread may still run; retain the lease
        # until its bounded provider envelope expires.
        return 0
