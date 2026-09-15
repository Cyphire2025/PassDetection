"""Real PostgreSQL locks fence manual submission, retries, and late AI results."""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.platform_policies import PlatformPolicies
from app.application.use_cases.passports.client_submit_passport_use_case import (
    ClientSubmitPassportUseCase,
)
from app.domain.entities.entities import ClientGroup, PassportSubmission
from app.domain.value_objects.passport_document_classification import MANUAL_REVIEW_REASON_CODE
from app.infrastructure.database.models import AgencyModel, Base
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="requires isolated PostgreSQL"),
]


@pytest.fixture
async def manual_review_pg():
    url = URL.create(
        "postgresql+asyncpg", username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"], host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")), database=os.environ["POSTGRES_DB"],
    )
    # A fresh owned schema prevents interference with other service tests and
    # teardown never touches production/shared tables.
    schema = f"manual_review_{uuid.uuid4().hex}"
    admin = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url, poolclass=NullPool, connect_args={"server_settings": {"search_path": schema}},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        group = ClientGroup.create(
            name="Manual review integration", token=f"review-{uuid.uuid4().hex}",
            agency_id=uuid.uuid4(), created_by_user_id=uuid.uuid4(),
        )
        group.created_by_user_id = None
        submission = PassportSubmission.create(
            group_id=group.id, agency_id=group.agency_id,
            client_name="Synthetic traveller", client_email=None,
            image_s3_key="drafts/synthetic/front.jpg",
        )
        submission.passport_back_s3_key = "drafts/synthetic/back.jpg"
        revision = submission.mark_processing()
        submission.mark_extraction_failed(
            expected_revision=revision, diagnostics={"ai_verification": {
                "status": "timeout", "available": False, "outcome_kind": "provider_failure",
                "extraction_revision": revision,
            }},
        )
        async with factory() as session:
            session.add(AgencyModel(id=group.agency_id, name="Synthetic agency", email="review@example.test"))
            await session.flush()
            await ClientGroupRepository(session).save(group)
            await PassportSubmissionRepository(session).save(submission)
            await session.commit()
        yield factory, group, submission
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


async def _wait_blocked(factory, backend_pid):
    async with factory() as observer:
        for _ in range(100):
            if await observer.scalar(text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": backend_pid}):
                return
            await asyncio.sleep(0.02)
    raise AssertionError("Competing operation did not wait for the submission row lock")


@pytest.mark.parametrize("contender", ["extraction", "duplicate_submit"])
async def test_manual_submission_serializes_against_late_extraction_and_duplicate_submit(manual_review_pg, contender):
    factory, group, submission = manual_review_pg
    entered = asyncio.Event()
    release = asyncio.Event()
    contender_started = asyncio.Event()
    contender_pid = []
    storage = AsyncMock()
    calls = 0

    async def get_image(_key):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
        return b"validated-synthetic-image"

    storage.get_file.side_effect = get_image
    policies = AsyncMock()
    policies.load.return_value = PlatformPolicies(require_client_email=False, require_client_phone=False)

    async def submit(session):
        result = await ClientSubmitPassportUseCase(
            PassportSubmissionRepository(session), ClientGroupRepository(session), storage, policies,
        ).execute(
            submission.id, group_token=group.token, confirmed_fields={"given_names": "AMAN", "passport_number": "P1234567"},
            client_email=None, client_phone="9876543210",
        )
        await session.commit()
        return result

    async def first_submission():
        async with factory() as session:
            return await submit(session)

    async def competing_operation():
        async with factory() as session:
            contender_pid.append(await session.scalar(text("SELECT pg_backend_pid()")))
            contender_started.set()
            if contender == "duplicate_submit":
                return await submit(session)
            result = await PassportSubmissionRepository(session).apply_extraction_result(
                submission_id=submission.id, expected_revision=submission.extraction_revision,
                extracted_fields={"given_names": "LATE AI VALUE", "ai_verification": {"available": True, "status": "verified"}},
                confidence=1.0, confidence_score=None, mrz_raw=None,
            )
            await session.commit()
            return result

    first = asyncio.create_task(first_submission())
    second = None
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        second = asyncio.create_task(competing_operation())
        await asyncio.wait_for(contender_started.wait(), timeout=5)
        await _wait_blocked(factory, contender_pid[0])
        release.set()
        first_result, second_result = await asyncio.wait_for(asyncio.gather(first, second), timeout=8)
        assert first_result.status == "needs_review"
        if contender == "extraction":
            assert second_result is None
        else:
            assert second_result.idempotent_replay
            assert second_result.status == "needs_review"
        assert storage.upload_file.await_count == 2
        async with factory() as session:
            repository = PassportSubmissionRepository(session)
            saved = await repository.get_by_id(submission.id)
            assert saved.status.value == "needs_review"
            assert saved.confirmed_fields["given_names"] == "AMAN"
            assert saved.client_phone == "+919876543210"
            assert saved.post_submission_verification["reason_code"] == MANUAL_REVIEW_REASON_CODE
            assert await repository.apply_post_submission_verification(
                submission_id=saved.id, expected_revision=saved.post_submission_verification_revision,
                decision="ai_approved", verification={"verification_status": "ai_approved"},
            ) is None
            await session.commit()
    finally:
        release.set()
        for task in (first, second):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (first, second) if task is not None), return_exceptions=True)


@pytest.mark.parametrize("legacy_phone", ["9876543210", "919876543210", "00919876543210", "+919876543210"])
async def test_canonical_duplicate_check_matches_legacy_saved_phone(manual_review_pg, legacy_phone):
    factory, group, submission = manual_review_pg
    async with factory() as session:
        repository = PassportSubmissionRepository(session)
        await repository.save(replace(submission, id=uuid.uuid4(), client_phone=legacy_phone))
        assert await repository.exists_contact_in_group(
            group.id, client_email=None, client_phone="+919876543210", exclude_submission_id=submission.id,
        )
        await session.rollback()
