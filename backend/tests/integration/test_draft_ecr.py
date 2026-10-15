"""Temporary ECR is real, opt-in, back-only and independent of passport OCR."""
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.travellers.draft_uploads import upload_draft_document
from app.application.travellers.drafts import draft_view, require_draft
from app.infrastructure.ai.gemini_ecr_service import EcrClassification, GeminiEcrService
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.passport_ecr_models import PassportEcrCheckModel
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftAssetModel as Asset,
)
from app.infrastructure.travellers import draft_runtime
from app.infrastructure.travellers.draft_runtime import run_draft_extraction
from tests.integration.test_returning_drafts import draft_context
from tests.integration.test_traveller_draft_runtime import Extractor, StreamStorage


async def back_context(session, settings, enabled=True):
    service, _, group, _, token, _, secret, view = await draft_context(session, settings)
    group.upload_configuration = {**group.upload_configuration, "passport_ecr_enabled": enabled}
    await session.commit()
    storage = StreamStorage()
    view = await upload_draft_document(service, token, secret, side="back", expected_revision=view.revision,
        idempotency_key=uuid.uuid4().hex, content=b"synthetic back image", content_type="image/jpeg", storage=storage)
    return service, token, secret, view, storage, async_sessionmaker(session.bind, expire_on_commit=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("result", ["ECR", "NA", "REVIEW"])
async def test_back_before_front_has_real_isolated_ecr_status(db_session, test_settings, result):
    service, token, secret, view, storage, factory = await back_context(db_session, test_settings)
    assert view.ecr_status == "pending" and view.ecr_result is None
    assert view.extraction_status == "none"
    checker = AsyncMock(spec=GeminiEcrService)
    checker.classify.return_value = EcrClassification(result, "synthetic", "test-model")
    assert await run_draft_extraction(factory=factory, storage=storage, crypto=service.crypto, ecr_checker=checker) == 1
    db_session.expire_all()
    result_view = await draft_view(service, await require_draft(service, token, secret))
    checker.classify.assert_awaited_once_with(b"synthetic back image", "image/jpeg")
    assert result_view.ecr_status == "succeeded" and result_view.ecr_result == result
    assert result_view.revision == view.revision  # A status update cannot conflict with an unrelated form save.
    assert result_view.passport_fields == view.passport_fields and result_view.extracted_fields == {}
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0
    assert await db_session.scalar(select(func.count()).select_from(PassportEcrCheckModel)) == 0


@pytest.mark.asyncio
async def test_disabled_link_does_not_queue_or_pretend_to_run_ecr(db_session, test_settings):
    service, _, _, view, storage, factory = await back_context(db_session, test_settings, enabled=False)
    assert view.ecr_status == "none" and view.ecr_result is None
    checker = AsyncMock(spec=GeminiEcrService)
    assert await run_draft_extraction(factory=factory, storage=storage, crypto=service.crypto, ecr_checker=checker) == 0
    checker.classify.assert_not_awaited()


@pytest.mark.asyncio
async def test_ecr_provider_failures_retry_bounded_and_never_become_no_ecr(db_session, test_settings):
    service, token, secret, view, storage, factory = await back_context(db_session, test_settings)
    checker = AsyncMock(spec=GeminiEcrService)
    checker.classify.return_value = EcrClassification("ERROR", "provider_unavailable", "test-model")
    for attempt in range(3):
        assert await run_draft_extraction(factory=factory, storage=storage, crypto=service.crypto, ecr_checker=checker) == 1
        asset = await db_session.scalar(select(Asset).where(Asset.id == view.documents[0].id).execution_options(populate_existing=True))
        assert asset.attempts == attempt + 1
        asset.available_at = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.commit()
    result = await draft_view(service, await require_draft(service, token, secret))
    assert result.ecr_status == "failed" and result.ecr_result is None
    assert await run_draft_extraction(factory=factory, storage=storage, crypto=service.crypto, ecr_checker=checker) == 0


@pytest.mark.asyncio
async def test_new_back_fences_inflight_result_for_previous_back(db_session, test_settings):
    service, token, secret, view, storage, factory = await back_context(db_session, test_settings)
    checker = AsyncMock(spec=GeminiEcrService)
    async def replace(_content, _media):
        await upload_draft_document(service, token, secret, side="back", expected_revision=view.revision,
            idempotency_key=uuid.uuid4().hex, content=b"newer back", content_type="image/jpeg", storage=storage,
            expected_asset_id=view.documents[0].id)
        return EcrClassification("ECR", "synthetic", "test-model")
    checker.classify.side_effect = replace
    assert await run_draft_extraction(factory=factory, storage=storage, crypto=service.crypto, ecr_checker=checker) == 0
    result = await draft_view(service, await require_draft(service, token, secret))
    assert result.documents[0].id != view.documents[0].id
    assert result.ecr_status == "pending" and result.ecr_result is None


@pytest.mark.asyncio
async def test_previous_front_only_worker_cannot_publish_back_extraction_as_passport_fields(db_session, test_settings, monkeypatch):
    service, token, secret, view, storage, factory = await back_context(db_session, test_settings)
    original_reserve = draft_runtime.reserve_extraction

    async def previous_worker_claim(factory):
        claim = await original_reserve(factory)
        # The retained worker did not carry a side discriminator: all claims
        # followed front OCR, then used fields_revision to authorize publication.
        return replace(claim, side="front") if claim else None

    monkeypatch.setattr(draft_runtime, "reserve_extraction", previous_worker_claim)
    extractor = Extractor({"passport_number": "WRONG_BACK_RESULT",
        "ai_verification": {"status": "verified", "available": True}})
    assert await run_draft_extraction(factory=factory, storage=storage, crypto=service.crypto, extractor=extractor) == 1
    db_session.expire_all()
    result = await draft_view(service, await require_draft(service, token, secret))
    asset = await db_session.get(Asset, view.documents[0].id)
    assert asset.fields_revision == 0 and asset.extraction_status == "succeeded"
    assert result.passport_fields == view.passport_fields
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0
