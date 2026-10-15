"""Draft publication uses production's explicit-flush session semantics."""
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.travellers.draft_contracts import DraftSave
from app.application.travellers.draft_store import FreshDraftStore
from app.application.travellers.draft_uploads import store_draft_document
from app.application.travellers.drafts import draft_view, require_draft, save_owned_draft
from app.application.travellers.fresh_drafts import (
    fresh_secret,
    require_fresh_draft,
    start_fresh_draft,
)
from app.infrastructure.ai.gemini_ecr_service import EcrClassification, GeminiEcrService
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftAssetModel as Asset,
)
from app.infrastructure.travellers.draft_runtime import run_draft_extraction
from tests.integration.test_returning_drafts import draft_context, save_body
from tests.integration.test_traveller_draft_runtime import Extractor, StreamStorage, runtime_context


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["returning", "fresh"])
@pytest.mark.parametrize("side", ["front", "back"])
async def test_explicit_flush_upload_is_ready_then_worker_publishes_result(db_session, test_settings, mode, side):
    service, _, group, _, token, _, secret, view = await draft_context(db_session, test_settings)
    group_token = group.token
    if mode == "fresh":
        service = FreshDraftStore(db_session, test_settings, service.crypto)
        member = uuid.uuid4().hex
        secret = fresh_secret(service, group.token, uuid.uuid4().hex, member)
        view = await start_fresh_draft(service, group.token, secret, member)

    async def authorize():
        return await require_fresh_draft(service, group_token, secret) if mode == "fresh" else await require_draft(service, token, secret)
    group.upload_configuration = {**group.upload_configuration, "passport_ecr_enabled": True}
    await db_session.commit()
    db_session.autoflush = False
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, autoflush=False)
    storage = StreamStorage()
    checker = AsyncMock(spec=GeminiEcrService)
    checker.classify.return_value = EcrClassification("NA", "synthetic", "test-model")

    for upload_number in range(2):
        previous_id = next((document.id for document in view.documents if document.side == side), None)
        view = await store_draft_document(service, authorize=authorize, side=side,
            expected_revision=view.revision, expected_asset_id=previous_id, idempotency_key=uuid.uuid4().hex,
            content=f"synthetic-{side}-{upload_number}".encode(), content_type="image/jpeg", storage=storage)
        assert view.documents[0].state == "ready"
        assert (view.extraction_status if side == "front" else view.ecr_status) == "pending"
        asset = await db_session.get(Asset, view.documents[0].id)
        assert asset.state == "ready" and asset.is_current and asset.extraction_status == "pending"
        await db_session.commit()
        view = await save_owned_draft(service, await authorize(), save_body(view,
            current_details={"client_email": "reviewed@example.com"}))

        extractor = Extractor({"given_names": f"EXTRACTED {upload_number}",
            "ai_verification": {"status": "verified", "available": True}})
        assert await run_draft_extraction(factory=factory, storage=storage, extractor=extractor,
            ecr_checker=checker, crypto=service.crypto) == 1
        db_session.expire_all()
        view = await draft_view(service, await authorize())
        if side == "front":
            assert view.extraction_status == "succeeded"
            assert view.passport_fields["given_names"] == f"EXTRACTED {upload_number}"
        else:
            assert view.ecr_status == "succeeded" and view.ecr_result == "NA"
        assert view.current_details == {"client_email": "reviewed@example.com"}
        if previous_id:
            previous = await db_session.scalar(select(Asset).where(Asset.id == previous_id))
            assert previous.state == "discarded" and not previous.is_current
        await db_session.commit()


@pytest.mark.asyncio
async def test_explicit_flush_manual_passport_edit_survives_worker_and_authoritative_read(db_session, test_settings):
    service, token, _, secret, view, storage, _ = await runtime_context(db_session, test_settings)
    db_session.autoflush = False
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, autoflush=False)

    async def manual_edit():
        await save_owned_draft(service, await require_draft(service, token, secret), DraftSave(
            expected_revision=view.revision, idempotency_key=uuid.uuid4().hex,
            passport_fields={"given_names": "MANUAL CORRECTION"}))

    extractor = Extractor({"given_names": "OCR RESULT",
        "ai_verification": {"status": "verified", "available": True}}, callback=manual_edit)
    assert await run_draft_extraction(factory=factory, storage=storage, extractor=extractor, crypto=service.crypto) == 1
    db_session.expire_all()
    current = await draft_view(service, await require_draft(service, token, secret))
    assert current.passport_fields == {"given_names": "MANUAL CORRECTION"}
    assert current.extracted_fields == {"given_names": "OCR RESULT"}
