"""Export owner extraction retains live facade policy and authority seams."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.core.config.settings import S3Settings
from app.infrastructure.database.company_data_export_models import CompanyDataExportJobModel as Job
from app.infrastructure.database.company_data_export_models import (
    CompanyDataExportPartModel as Part,
)
from app.infrastructure.travellers import company_export_worker as worker
from tests.integration.test_company_data_exports import export_fixture


@pytest.mark.parametrize("limit", ["attempts", "lease", "page_timeout"])
async def test_admission_resolves_live_facade_limits_and_settings(db_session, monkeypatch, limit):
    _, _, _, job_id, _, factory = await export_fixture(db_session)
    settings = SimpleNamespace(
        s3=S3Settings(max_attempts=1, connect_timeout_seconds=1, read_timeout_seconds=1)
    )
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    if limit == "attempts":
        monkeypatch.setattr(worker, "MAX_ATTEMPTS", 1)
        async with factory() as session, session.begin():
            (await session.get(Job, job_id)).attempt_count = 1

        def unavailable_settings():
            raise AssertionError("Exhausted jobs must not inspect provider configuration")

        monkeypatch.setattr(worker, "get_settings", unavailable_settings)
    elif limit == "lease":
        monkeypatch.setattr(worker, "LEASE_SECONDS", 900)
    else:
        monkeypatch.setattr(worker, "LEASE_SECONDS", 1)
        monkeypatch.setattr(worker, "PAGE_TIMEOUT_SECONDS", 900)
    before = datetime.now(UTC)

    claimed = await worker.reserve_export(factory)

    async with factory() as session:
        job = await session.get(Job, job_id)
        if limit == "attempts":
            assert claimed is None and job.status == "failed"
            assert job.attempt_count == 1 and job.lease_token is None
        else:
            assert claimed is not None
            assert job.lease_expires_at.replace(tzinfo=UTC) >= before + timedelta(seconds=900)
            if limit == "page_timeout":
                # One two-second I/O attempt and the original thirty-second margin.
                assert job.lease_expires_at.replace(tzinfo=UTC) >= before + timedelta(seconds=932)


async def test_part_reservation_uses_current_facade_authority_before_owning_write(
    db_session,
    monkeypatch,
):
    _, person, _, job_id, storage, factory = await export_fixture(db_session)
    identifier, token = await worker.reserve_export(factory)
    denied = AsyncMock(side_effect=ValueError("synthetic authority revoked"))
    monkeypatch.setattr(worker, "export_authority", denied)
    key = f"company-data-exports/{person.agency_id}/{person.company_id}/{job_id}/1"

    with pytest.raises(ValueError, match="authority revoked"):
        await worker.reserve_part(
            factory,
            identifier,
            token,
            None,
            1,
            "rows",
            key,
            "application/octet-stream",
            b"synthetic",
            1,
        )

    denied.assert_awaited_once()
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Part)) == 0
    assert storage.uploads == []


async def test_workbook_assembly_rechecks_current_facade_authority_before_reading_rows(
    db_session,
    monkeypatch,
):
    context, _, _, job_id, storage, factory = await export_fixture(db_session)
    assert (
        await worker.run_company_export_tick(
            session_factory=factory,
            storage=storage,
            crypto=context.crypto,
        )
        == 1
    )
    identifier, token = await worker.reserve_export(factory)
    denied = AsyncMock(side_effect=ValueError("synthetic authority revoked"))
    monkeypatch.setattr(worker, "export_authority", denied)

    with pytest.raises(ValueError, match="authority revoked"):
        await worker.assemble_workbook(factory, identifier, storage, context.crypto, token)

    denied.assert_awaited_once()
    assert len(storage.uploads) == 1
