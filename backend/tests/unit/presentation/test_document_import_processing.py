"""Existing AI bundle gates and caller-owned commit-before-publication remain."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import select, update

from app.application.use_cases.passports import reextract_passport_submission_use_case
from app.infrastructure.database.models import PassportProcessingJobModel, PassportSubmissionModel
from app.presentation.api.v1.routes.passport_routes import document_import as route
from app.presentation.api.v1.routes.passport_routes import document_import_processing as owner
from tests.unit.presentation.document_import_authority_fixture import (
    perform_held_import,
    prepare_authority_import,
)


def row(*, images=True, fields=None, extracted=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        confirmed_fields=fields,
        extracted_fields=extracted,
        image_s3_key="front/source.jpg",
        passport_photo_s3_key="photo/source.jpg" if images else None,
        passport_back_s3_key="back/source.jpg" if images else None,
    )


async def test_ai_selector_requires_all_three_images_and_missing_confirmed_or_extracted_field(
    monkeypatch,
):
    complete = {
        field: "synthetic"
        for field in [
            "passport_number",
            "surname",
            "given_names",
            "date_of_birth",
            "date_of_expiry",
        ]
    }
    incomplete_images = row(images=False)
    confirmed = row(fields=complete)
    extracted = row(extracted=complete)
    needs_ai = row(fields={**complete, "passport_number": "  "})
    execute = AsyncMock(return_value=SimpleNamespace(id=needs_ai.id))
    monkeypatch.setattr(
        owner,
        "ReextractPassportSubmissionUseCase",
        lambda **_kwargs: SimpleNamespace(execute=execute),
    )
    result = await owner._stage_ocr_for_complete_staff_bundles(
        submissions=[incomplete_images, confirmed, extracted, needs_ai],
        session=MagicMock(),
    )
    assert [value.id for value in result] == [needs_ai.id]
    execute.assert_awaited_once_with(needs_ai.id)
    execute.reset_mock()
    assert (
        await owner._stage_ocr_for_complete_staff_bundles(
            submissions=[incomplete_images, confirmed, extracted],
            session=MagicMock(),
        )
        == []
    )
    execute.assert_not_awaited()


async def test_legacy_caller_owned_queue_commits_before_publishing_only_durable_job_ids(
    monkeypatch,
):
    valid = SimpleNamespace(id=uuid.uuid4(), processing_job_id=uuid.uuid4())
    absent = SimpleNamespace(id=uuid.uuid4(), processing_job_id=None)
    order = []

    async def commit():
        order.append("commit")

    async def dispatch(**kwargs):
        order.append(kwargs["job_id"])

    monkeypatch.setattr(
        owner, "_stage_ocr_for_complete_staff_bundles", AsyncMock(return_value=[valid, absent])
    )
    publisher = SimpleNamespace(dispatch_async=AsyncMock(side_effect=dispatch))
    monkeypatch.setattr(owner, "PassportProcessingDispatcher", lambda: publisher)
    session = SimpleNamespace(commit=AsyncMock(side_effect=commit))
    background = BackgroundTasks()
    await owner._queue_ocr_for_complete_staff_bundles(
        submissions=[],
        session=session,
        background_tasks=background,
    )
    assert order == ["commit", valid.processing_job_id]
    publisher.dispatch_async.assert_awaited_once_with(
        job_id=valid.processing_job_id,
        submission_id=valid.id,
        background_tasks=background,
    )


@pytest.mark.parametrize("publisher_unavailable", [False, True])
async def test_completed_bundle_commits_real_ai_intent_before_best_effort_publication(
    db_session,
    monkeypatch,
    test_settings,
    publisher_unavailable,
):
    context = await prepare_authority_import(
        db_session,
        monkeypatch,
        test_settings,
        "unchanged",
        "put",
    )
    await db_session.execute(
        update(PassportSubmissionModel)
        .where(
            PassportSubmissionModel.id == context.passenger_id,
        )
        .values(
            status="uploaded",
            passport_back_s3_key="back/synthetic-source.jpg",
            confirmed_fields={},
            extracted_fields={},
        )
    )
    await db_session.commit()
    monkeypatch.setattr(
        reextract_passport_submission_use_case, "get_settings", lambda: test_settings
    )
    published = []

    async def publish(*, job_id, submission_id, background_tasks):
        async with context.factory() as fresh:
            job = await fresh.get(PassportProcessingJobModel, job_id)
            stored = await fresh.get(PassportSubmissionModel, submission_id)
            assert job is not None and job.status == "queued"
            assert job.extraction_revision == stored.extraction_revision == 1
            assert stored.image_s3_key in context.objects
            published.append(job_id)
        if publisher_unavailable:
            raise ConnectionError("Synthetic broker unavailable")

    publisher = SimpleNamespace(dispatch_async=AsyncMock(side_effect=publish))
    monkeypatch.setattr(route, "PassportProcessingDispatcher", lambda: publisher)
    result = await perform_held_import(context, db_session, "put")
    assert not isinstance(result, BaseException), repr(result)
    assert result.saved_count == 1 and len(published) == 1
    async with context.factory() as fresh:
        jobs = list(await fresh.scalars(select(PassportProcessingJobModel)))
    assert len(jobs) == 1 and jobs[0].id == published[0]
    assert jobs[0].queue_name == "passport_ocr" and jobs[0].status == "queued"
