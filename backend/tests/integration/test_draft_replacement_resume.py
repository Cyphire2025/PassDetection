"""Retained replacement text cannot be published with an earlier passport image."""
import pytest
from sqlalchemy import func, select

from app.application.travellers.draft_completion import complete_draft
from app.application.travellers.drafts import draft_view, require_draft, start_draft
from app.application.travellers.history import read_history
from app.domain.exceptions.exceptions import ValidationError
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.traveller_returning_draft_models import TravellerDraftAssetModel
from app.infrastructure.database.traveller_reuse_models import TravellerParticipationModel
from app.infrastructure.travellers.draft_runtime import run_draft_extraction
from tests.integration.test_returning_drafts import completion_body
from tests.integration.test_traveller_draft_runtime import Extractor, runtime_context


@pytest.mark.asyncio
async def test_resumed_replacement_fields_require_reupload_before_final_publication(db_session, test_settings):
    service, token, review, secret, view, storage, factory = await runtime_context(db_session, test_settings)
    original_fields = dict(review["extracted_fields"])
    replacement_fields = {**original_fields, "passport_number": "REPLACEMENT123",
        "ai_verification": {"status": "verified", "available": True}}
    assert await run_draft_extraction(factory=factory, storage=storage,
        extractor=Extractor(replacement_fields), crypto=service.crypto) == 1
    db_session.expire_all()
    extracted = await draft_view(service, await require_draft(service, token, secret))
    assert extracted.passport_fields["passport_number"] == "REPLACEMENT123"
    assert extracted.extraction_status == "succeeded"
    await db_session.commit()

    _, resumed = await start_draft(service, token, expected_review_version=review["review_version"], existing_secret=secret)
    assert resumed.passport_fields["passport_number"] == "REPLACEMENT123"
    assert resumed.documents == []
    with pytest.raises(ValidationError, match="Upload the new passport"):
        await complete_draft(service, token, secret, completion_body(review, resumed))
    await db_session.rollback()

    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0
    assert await db_session.scalar(select(func.count()).select_from(TravellerParticipationModel)) == 0
    asset = await db_session.scalar(select(TravellerDraftAssetModel))
    assert asset.state == "discarded" and not asset.is_current
    current = await draft_view(service, await require_draft(service, token, secret))
    assert current.passport_fields == resumed.passport_fields
    assert current.status == "active"
    saved = await read_history(service, token)
    assert saved["extracted_fields"] == original_fields
    assert saved["documents"] == review["documents"]
