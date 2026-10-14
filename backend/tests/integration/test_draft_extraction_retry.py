"""Explicit provider failures share the exception retry budget, never rejection."""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.interfaces.passport_extraction import PassportExtractionResult
from app.application.interfaces.passport_verification import (
    IPassportVerificationService,
    PassportVerificationResult,
)
from app.application.travellers.drafts import draft_payload, require_draft
from app.application.use_cases.passports.passport_ai_verification import verify_passport_fields
from app.domain.services.traveller_verification import utc
from app.domain.value_objects.passport_document_classification import (
    REJECTED_PASSPORT_DOCUMENT_STATUSES,
)
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftAssetModel as Asset,
)
from app.infrastructure.travellers.draft_runtime import run_draft_extraction
from tests.integration.test_traveller_draft_runtime import Extractor, runtime_context


class VerifiedExtractor:
    def __init__(self, verifier):
        self.verifier = verifier

    async def extract(self, content, *, content_type, **_kwargs):
        fields = await verify_passport_fields(self.verifier, image_content=content,
            content_type=content_type, extracted_fields={}, timeout_seconds=1)
        return PassportExtractionResult(fields, 0, {})


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "unavailable"])
async def test_explicit_provider_failure_retries_then_publishes_without_reupload(db_session, test_settings, failure):
    service, token, _, secret, view, storage, _ = await runtime_context(db_session, test_settings)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, autoflush=False)
    verifier = AsyncMock(spec=IPassportVerificationService)
    verifier.verify.side_effect = [
        TimeoutError() if failure == "timeout" else PassportVerificationResult({}, {"status": failure, "available": False}),
        PassportVerificationResult({"given_names": "RECOVERED"}, {"status": "verified", "available": True}),
    ]
    extractor = VerifiedExtractor(verifier)
    before = datetime.now(UTC)
    assert await run_draft_extraction(factory=factory, storage=storage, extractor=extractor, crypto=service.crypto) == 1
    asset = await db_session.scalar(select(Asset).where(Asset.draft_id == view.id).execution_options(populate_existing=True))
    assert asset.extraction_status == "pending" and asset.attempts == 1 and asset.lease_expires_at is None
    assert utc(asset.available_at) >= before + timedelta(seconds=10)
    assert asset.extraction_ciphertext is None and asset.classification_ciphertext is None
    assert await run_draft_extraction(factory=factory, storage=storage, extractor=extractor, crypto=service.crypto) == 0
    assert verifier.verify.await_count == 1
    asset.available_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    assert await run_draft_extraction(factory=factory, storage=storage, extractor=extractor, crypto=service.crypto) == 1
    db_session.expire_all()
    draft = await require_draft(service, token, secret)
    asset = await db_session.scalar(select(Asset).where(Asset.draft_id == view.id))
    assert asset.extraction_status == "succeeded" and asset.attempts == 2
    assert draft_payload(service, draft).passport_fields == {"given_names": "RECOVERED"}
    assert verifier.verify.await_count == 2


@pytest.mark.asyncio
async def test_explicit_provider_unavailable_exhausts_three_attempts_without_publishing_fields(db_session, test_settings):
    service, token, _, secret, view, storage, _ = await runtime_context(db_session, test_settings)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, autoflush=False)
    extractor = Extractor({"given_names": "UNVERIFIED", "ai_verification": {"status": "provider_unavailable", "available": False}})
    for attempt in range(1, 4):
        before = datetime.now(UTC)
        assert await run_draft_extraction(factory=factory, storage=storage, extractor=extractor, crypto=service.crypto) == 1
        asset = await db_session.scalar(select(Asset).where(Asset.draft_id == view.id).execution_options(populate_existing=True))
        assert asset.attempts == attempt and asset.lease_expires_at is None
        assert asset.extraction_status == ("failed" if attempt == 3 else "pending")
        assert utc(asset.available_at) >= before + timedelta(seconds=10 * attempt)
        assert asset.extraction_ciphertext is None and asset.classification_ciphertext is None
        asset.available_at = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.commit()
    assert await run_draft_extraction(factory=factory, storage=storage, extractor=extractor, crypto=service.crypto) == 0
    db_session.expire_all()
    assert draft_payload(service, await require_draft(service, token, secret)).passport_fields == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("status,available", [
    *((status, False) for status in sorted(REJECTED_PASSPORT_DOCUMENT_STATUSES)),
    ("wrong_document", True), ("unknown", False),
])
async def test_document_rejection_or_unknown_classification_never_retries(db_session, test_settings, status, available):
    service, token, _, secret, view, storage, _ = await runtime_context(db_session, test_settings)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, autoflush=False)
    extractor = Extractor({"given_names": "REJECTED", "ai_verification": {"status": status, "available": available}})
    assert await run_draft_extraction(factory=factory, storage=storage, extractor=extractor, crypto=service.crypto) == 1
    asset = await db_session.scalar(select(Asset).where(Asset.draft_id == view.id).execution_options(populate_existing=True))
    assert asset.extraction_status == "failed" and asset.attempts == 1
    assert await run_draft_extraction(factory=factory, storage=storage, extractor=extractor, crypto=service.crypto) == 0
    db_session.expire_all()
    assert draft_payload(service, await require_draft(service, token, secret)).passport_fields == {}
