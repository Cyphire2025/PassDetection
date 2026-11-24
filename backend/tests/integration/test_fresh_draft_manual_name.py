"""Cover-only collection reviews the full name without inventing passport data."""
import uuid

import pytest
from sqlalchemy import func, select

from app.application.travellers.draft_contracts import DraftSave
from app.application.travellers.draft_store import FreshDraftStore
from app.application.travellers.draft_uploads import store_draft_document
from app.application.travellers.drafts import draft_view, save_owned_draft
from app.application.travellers.fresh_draft_contracts import FreshCollection, FreshDraftComplete
from app.application.travellers.fresh_drafts import (
    fresh_secret,
    require_fresh_draft,
    start_fresh_draft,
)
from app.domain.exceptions.exceptions import ValidationError
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftAssetModel as Asset,
)
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftContactProofModel as Proof,
)
from app.presentation.api.v1.routes.fresh_draft_completion import complete
from tests.integration.test_fresh_drafts import verified_contact
from tests.integration.test_returning_drafts import MemoryStorage
from tests.integration.traveller_reuse_fixtures import reuse_context


async def manual_draft(session, settings, name):
    service, _, group = await reuse_context(session, settings)
    group.require_selfie = False
    group.upload_configuration = {"passport_upload_pages": ["cover", "back_cover"], "passport_live_scan": False,
        "visa_photo_required": False, "required_fields": {key: False for key in ("base_city", "nearest_domestic_airport",
            "departure_city", "staff_code", "agent_employee_code", "designation", "agency_dealership_name", "meal_preference", "relation_with_qualifier")}}
    await session.commit()
    store = FreshDraftStore(session, settings, service.crypto)
    member = uuid.uuid4().hex
    secret = fresh_secret(store, group.token, uuid.uuid4().hex, member)
    view = await start_fresh_draft(store, group.token, secret, member)
    details = {"client_email": "person@example.com", "client_phone": "+919876540001"}
    if name is not None:
        details["client_name"] = name
    view = await save_owned_draft(store, await require_fresh_draft(store, group.token, secret), DraftSave(
        expected_revision=view.revision, idempotency_key=uuid.uuid4().hex, current_details=details,
        collection=FreshCollection(acquisition_mode="file", submission_mode="single")))
    for side in ("cover", "back_cover"):
        view = await store_draft_document(store, authorize=lambda: require_fresh_draft(store, group.token, secret),
            side=side, expected_revision=view.revision, idempotency_key=uuid.uuid4().hex,
            content=f"synthetic-{side}".encode(), content_type="image/jpeg", storage=MemoryStorage())
    proof = await verified_contact(store, group, secret)
    view = await draft_view(store, await require_fresh_draft(store, group.token, secret))
    body = FreshDraftComplete(expected_revision=view.revision, phone_verification_id=proof,
        idempotency_key=uuid.uuid4().hex, information_confirmed=True)
    return store, group.token, member, secret, view.id, body


@pytest.mark.asyncio
async def test_cover_only_full_name_becomes_reviewed_identity_without_passport_data(db_session, test_settings):
    store, token, member, secret, _, body = await manual_draft(db_session, test_settings, "  Synthetic   Traveller  ")
    result = await complete(token, body, secret=secret, session_id=member, service=store)
    assert await complete(token, body, secret=secret, session_id=member, service=store) == result
    source = await db_session.get(PassportSubmissionModel, result.source_submission_id)
    assert result.status == "needs_review" and source.client_reviewed_at is not None
    assert source.confirmed_fields == {"given_names": "Synthetic Traveller"}
    assert source.extracted_fields == {} and not source.image_s3_key
    assert source.passport_cover_s3_key and source.passport_back_cover_s3_key
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("name", [None, "", " \t \n", "N" * 161])
async def test_cover_only_invalid_name_refuses_publication_and_preserves_proof(db_session, test_settings, name):
    store, token, member, secret, draft_id, body = await manual_draft(db_session, test_settings, name)
    with pytest.raises(ValidationError) as denied:
        await complete(token, body, secret=secret, session_id=member, service=store)
    assert denied.value.field == "given_names"
    await db_session.rollback()
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0
    assert (await db_session.get(Proof, body.phone_verification_id)).status == "verified"
    assets = list(await db_session.scalars(select(Asset).where(Asset.draft_id == draft_id)))
    assert len(assets) == 2 and all(asset.state == "ready" for asset in assets)
    assert (await require_fresh_draft(store, token, secret)).status == "active"
