"""Real worker checkpoints with synthetic private storage and bounded failures."""

import io
import json
from datetime import UTC, datetime, timedelta
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.companies.data_exports import (
    ExportRequest,
    invalidate_company_exports,
    request_export,
    require_export,
)
from app.domain.exceptions.exceptions import AuthorizationError, ConflictError, EntityNotFoundError
from app.infrastructure.database.company_data_export_models import CompanyDataExportJobModel as Job
from app.infrastructure.database.company_data_export_models import (
    CompanyDataExportPartModel as Part,
)
from app.infrastructure.database.traveller_reuse_models import TravellerDocumentAssetModel as Asset
from app.infrastructure.storage.minio_repository import ObjectIntegrityMetadata
from app.infrastructure.travellers.company_export_cleanup import expire_export_parts
from app.infrastructure.travellers.company_export_worker import (
    process_export_page,
    reserve_export,
    run_company_export_tick,
)
from tests.integration.test_company_people import people_fixture


class MemoryStorage:
    def __init__(self):
        self.objects = {}
        self.uploads = []
        self.fail_upload = False

    async def upload_file(self, content, key, content_type):
        self.objects[key] = (content, content_type)
        self.uploads.append(key)
        if self.fail_upload:
            raise TimeoutError("synthetic write acknowledgement loss")
        return key

    async def stat_file(self, key):
        data, media = self.objects[key]
        return ObjectIntegrityMetadata(len(data), None, media)

    async def stream_file(self, key, *, start, expected_bytes, chunk_size=65536):
        data = self.objects[key][0]
        assert len(data) == expected_bytes
        for offset in range(start, len(data), chunk_size):
            yield data[offset:offset + chunk_size]


async def export_fixture(session, kind="excel"):
    ctx, person, user = await people_fixture(session)
    job = await request_export(session, user=user, agency_id=person.agency_id, company_id=person.company_id,
        body=ExportRequest(kind=kind, idempotency_key="synthetic-export"))
    storage = MemoryStorage()
    for asset in (await session.scalars(select(Asset))).all():
        storage.objects[asset.object_key] = (b"synthetic!", "image/jpeg")
    await session.commit()
    return ctx, person, user, job.id, storage, async_sessionmaker(session.bind, expire_on_commit=False)


async def drain(factory, storage, crypto, job_id, maximum=15):
    for _ in range(maximum):
        await run_company_export_tick(session_factory=factory, storage=storage, crypto=crypto)
        async with factory() as session:
            job = await session.get(Job, job_id)
            if job.status == "succeeded":
                return job
    raise AssertionError(f"Export did not complete: {job.status}, {job.phase}, {job.last_error_code}")


@pytest.mark.asyncio
async def test_excel_worker_creates_unique_current_row_and_retains_recoverable_receipt(db_session):
    ctx, person, user, job_id, storage, factory = await export_fixture(db_session)
    completed = await drain(factory, storage, ctx.crypto, job_id)
    assert completed.processed_count == 1
    async with factory() as session:
        parts = list((await session.scalars(select(Part).where(Part.job_id == job_id))).all())
        public = [part for part in parts if part.part_kind == "workbook"]
        assert len(public) == 1 and len(parts) == 2
        assert parts[0].part_kind in {"rows", "workbook"}
        workbook = load_workbook(io.BytesIO(storage.objects[public[0].object_key][0]), read_only=True)
        rows = list(workbook.active.values)
        workbook.close()
        assert len(rows) == 2 and rows[1][0] == str(person.id) and rows[1][1] == "Synthetic Person"
        assert len(rows[0]) == len(rows[1]) == 18
        same = await request_export(session, user=user, agency_id=person.agency_id, company_id=person.company_id,
            body=ExportRequest(kind="excel", idempotency_key="synthetic-export"))
        assert same.id == job_id
        with pytest.raises(ConflictError):
            await request_export(session, user=user, agency_id=person.agency_id, company_id=person.company_id,
                body=ExportRequest(kind="images", idempotency_key="synthetic-export"))


@pytest.mark.asyncio
async def test_write_acknowledgement_loss_resumes_same_part_without_duplicate_rows(db_session):
    ctx, person, user, job_id, storage, factory = await export_fixture(db_session)
    storage.fail_upload = True
    assert await run_company_export_tick(session_factory=factory, storage=storage, crypto=ctx.crypto) == 0
    async with factory() as session, session.begin():
        job = await session.get(Job, job_id)
        assert job.cursor is None and job.part_count == 0 and job.attempt_count == 1
        assert await session.scalar(select(func.count()).select_from(Part)) == 1
        job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
    storage.fail_upload = False
    completed = await drain(factory, storage, ctx.crypto, job_id)
    assert completed.processed_count == 1 and storage.uploads[0] == storage.uploads[1]
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Part)) == 2


@pytest.mark.asyncio
async def test_only_one_global_lease_and_authority_cancellation_blocks_publication(db_session):
    ctx, person, user, job_id, storage, factory = await export_fixture(db_session)
    claimed = await reserve_export(factory)
    assert claimed is not None and await reserve_export(factory) is None
    async with factory() as session, session.begin():
        await invalidate_company_exports(session, person.agency_id, person.company_id)
    with pytest.raises(ValueError, match="cancelled"):
        await process_export_page(factory, *claimed, storage, ctx.crypto)
    assert storage.uploads == []


@pytest.mark.asyncio
async def test_images_include_versioned_names_manifest_and_no_storage_locators(db_session):
    ctx, person, user, job_id, storage, factory = await export_fixture(db_session, kind="images")
    completed = await drain(factory, storage, ctx.crypto, job_id)
    assert completed.processed_count == 2
    async with factory() as session:
        part = await session.scalar(select(Part).where(Part.part_kind == "images"))
        with ZipFile(io.BytesIO(storage.objects[part.object_key][0])) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            assert len(manifest["documents"]) == 2
            assert all(entry["revision_number"] == 1 for entry in manifest["documents"])
            assert all(entry["traveller_id"] == str(person.id) for entry in manifest["documents"])
            assert "travellers/" not in archive.read("manifest.json").decode()


@pytest.mark.asyncio
async def test_export_scope_and_expiry_are_checked_on_each_access(db_session):
    ctx, person, user, job_id, storage, factory = await export_fixture(db_session)
    async with factory() as session, session.begin():
        with pytest.raises(EntityNotFoundError):
            await require_export(session, user=user, company_id=person.company_id,
                agency_id=person.agency_id, job_id=__import__("uuid").uuid4())
        job = await session.get(Job, job_id)
        job.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        with pytest.raises(AuthorizationError):
            await require_export(session, user=user, company_id=person.company_id,
                agency_id=person.agency_id, job_id=job_id)


@pytest.mark.asyncio
async def test_cancel_after_provider_write_keeps_owned_cleanup_receipt(db_session):
    ctx, person, user, job_id, storage, factory = await export_fixture(db_session)
    original = storage.upload_file

    async def cancel_after_write(content, key, content_type):
        await original(content, key, content_type)
        async with factory() as session, session.begin():
            await invalidate_company_exports(session, person.agency_id, person.company_id)

    storage.upload_file = cancel_after_write
    assert await run_company_export_tick(session_factory=factory, storage=storage, crypto=ctx.crypto) == 0
    async with factory() as session:
        job = await session.get(Job, job_id)
        part = await session.scalar(select(Part).where(Part.job_id == job_id))
        assert job.status == "cancelled" and job.part_count == 0 and job.cursor is None
        assert part.object_key in storage.objects and part.purged_at is None
    assert await expire_export_parts(session_factory=factory) == 1
    from app.infrastructure.database.models import StorageCleanupJobModel
    async with factory() as session:
        part = await session.scalar(select(Part).where(Part.job_id == job_id))
        cleanup = await session.scalar(select(StorageCleanupJobModel).where(StorageCleanupJobModel.source == "company_data_export_expiry"))
        assert part.purged_at is not None and cleanup is not None
        from app.infrastructure.documents.storage_cleanup import StorageCleanupCipher
        assert StorageCleanupCipher.from_settings().decrypt(cleanup.storage_keys_ciphertext, key_version=cleanup.encryption_key_version) == (part.object_key,)
        assert cleanup.next_attempt_at.replace(tzinfo=UTC) >= job.lease_expires_at.replace(tzinfo=UTC)


@pytest.mark.asyncio
async def test_provider_failures_stop_after_five_attempts_and_own_every_write(db_session):
    ctx, person, user, job_id, storage, factory = await export_fixture(db_session)
    storage.fail_upload = True
    for attempt in range(5):
        assert await run_company_export_tick(session_factory=factory, storage=storage, crypto=ctx.crypto) == 0
        async with factory() as session, session.begin():
            job = await session.get(Job, job_id)
            assert job.attempt_count == attempt + 1
            job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            job.available_at = datetime.now(UTC) - timedelta(seconds=1)
    async with factory() as session:
        job = await session.get(Job, job_id)
        assert job.status == "failed" and job.processed_count == 0
        assert await session.scalar(select(func.count()).select_from(Part)) == 1
    assert await reserve_export(factory) is None and len(set(storage.uploads)) == 1




@pytest.mark.asyncio
async def test_expiry_cleanup_drains_bounded_parts_and_skips_retained_receipts(db_session):
    ctx, person, user, job_id, storage, factory = await export_fixture(db_session)
    async with factory() as session, session.begin():
        job = await session.get(Job, job_id)
        job.status = "cancelled"
        for number in range(1, 151):
            session.add(Part(agency_id=person.agency_id, company_id=person.company_id, job_id=job_id,
                part_number=number, part_kind="images", object_key=f"company-data-exports/{person.agency_id}/{person.company_id}/{job_id}/{number}",
                content_type="application/zip", byte_size=1, content_sha256="a" * 64, record_count=1))
    assert await expire_export_parts(session_factory=factory) == 100
    async with factory() as session:
        assert (await session.get(Job, job_id)).status == "cancelled"
        assert await session.scalar(select(func.count()).select_from(Part).where(Part.purged_at.is_(None))) == 50
    assert await expire_export_parts(session_factory=factory) == 50
    async with factory() as session:
        assert (await session.get(Job, job_id)).status == "expired"
        assert await session.scalar(select(func.count()).select_from(Part)) == 150
    assert await expire_export_parts(session_factory=factory) == 0
