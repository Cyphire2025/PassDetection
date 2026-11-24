"""One bounded export page: read, render, own its write, then commit its cursor."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
from app.domain.entities.entities import User
from app.domain.services.traveller_verification import utc
from app.infrastructure.database.company_data_export_models import CompanyDataExportJobModel as Job
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.infrastructure.travellers.company_export_render import encode_rows, render_image_volume


async def process_export_page(
    factory: async_sessionmaker[AsyncSession],
    identifier: uuid.UUID,
    token: uuid.UUID,
    storage: MinioStorageRepository,
    crypto: TravellerReuseCrypto,
    *,
    export_authority: Callable[[AsyncSession, Job], Awaitable[User]],
    assemble_workbook: Callable[
        [
            async_sessionmaker[AsyncSession],
            uuid.UUID,
            MinioStorageRepository,
            TravellerReuseCrypto,
            uuid.UUID,
        ],
        Awaitable[tuple[bytes, int]],
    ],
    reserve_part: Callable[
        [
            async_sessionmaker[AsyncSession],
            uuid.UUID,
            uuid.UUID,
            uuid.UUID | None,
            int,
            str,
            str,
            str,
            bytes,
            int,
        ],
        Awaitable[None],
    ],
) -> None:
    async with factory() as session:
        job = await session.get(Job, identifier)
        if (
            job is None
            or job.lease_token != token
            or not job.lease_expires_at
            or utc(job.lease_expires_at) <= datetime.now(UTC)
        ):
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
            images = (
                await retained_image_page(session, job, user)
                if phase == "retained_images"
                else await source_image_page(session, job, user)
            )
            if not images:
                phases = [
                    "retained_images",
                    *(f"source_{side}" for side in SOURCE_SIDES),
                    "finalize",
                ]
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
                if (
                    metadata.content_type not in PRIVATE_DOCUMENT_TYPES
                    or not 0 < metadata.size_bytes <= MAX_PRIVATE_DOCUMENT_BYTES
                ):
                    raise ValueError("source_document_outside_export_budget")
                row = replace(
                    row, size=metadata.size_bytes, content_type=metadata.content_type or ""
                )
            verified.append(row)
        if any(row.size > 0 or row.key for row in verified):
            rendered = await render_image_volume(verified, storage)
            content, count = rendered.content, rendered.count
            last_id = uuid.UUID(rendered.last_id) if rendered.last_id else None
        else:
            last_id = verified[-1].identifier
    if job.phase == "finalize" and job.kind == "excel":
        content, count = await assemble_workbook(factory, job.id, storage, crypto, token)
        part_kind, media = (
            "workbook",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    if content is not None:
        await reserve_part(
            factory,
            identifier,
            token,
            previous_cursor,
            part_number,
            part_kind,
            key,
            media,
            content,
            count,
        )
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
