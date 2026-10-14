"""Fresh drafts publish once, after the same verified contact and form rules."""
import json
import uuid

import pytest
from sqlalchemy import func, select

from app.application.travellers.draft_contracts import DraftPayload, DraftSave
from app.application.travellers.draft_store import FreshDraftStore
from app.application.travellers.draft_uploads import store_draft_document
from app.application.travellers.drafts import draft_view, save_owned_draft
from app.application.travellers.errors import ReuseError
from app.application.travellers.fresh_contact import request_fresh_code, verify_fresh_code
from app.application.travellers.fresh_draft_contracts import FreshDraftComplete
from app.application.travellers.fresh_drafts import (
    fresh_secret,
    require_fresh_draft,
    start_fresh_draft,
)
from app.infrastructure.database.models import (
    PassportPostSubmissionVerificationJobModel,
    PassportSubmissionModel,
)
from app.infrastructure.database.public_upload_contact_model import (
    PublicUploadContactChallengeModel,
)
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftAssetModel as Asset,
)
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftContactProofModel as Proof,
)
from app.presentation.api.v1.routes.fresh_draft_completion import complete
from tests.integration.test_returning_completion import completion_context
from tests.integration.test_returning_drafts import MemoryStorage
from tests.integration.traveller_reuse_fixtures import FakeLimiter, FakeOTP


async def fresh_context(session, settings):
    service, _, group, _, _, review = await completion_context(session, settings)
    store = FreshDraftStore(session, settings, service.crypto)
    browser, member = uuid.uuid4().hex, uuid.uuid4().hex
    secret = fresh_secret(store, group.token, browser, member)
    view = await start_fresh_draft(store, group.token, secret, member)
    fields = {k: v for k, v in review["extracted_fields"].items() if k in {"passport_number", "given_names", "surname", "date_of_birth", "date_of_issue", "date_of_expiry", "nationality", "sex", "place_of_issue"}}
    view = await store_draft_document(store, authorize=lambda: require_fresh_draft(store, group.token, secret), side="front",
        expected_revision=view.revision, idempotency_key=uuid.uuid4().hex, content=b"synthetic-image", content_type="image/jpeg", storage=MemoryStorage())
    asset = await session.scalar(select(Asset).where(Asset.draft_id == view.id))
    asset.extraction_status = "succeeded"
    asset.classification_ciphertext = store.crypto.encrypt(json.dumps({"status": "verified", "available": True}))
    asset.extraction_ciphertext = store.crypto.encrypt(DraftPayload(passport_fields=fields).model_dump_json())
    await session.commit()
    view = await save_owned_draft(store, await require_fresh_draft(store, group.token, secret), DraftSave(
        expected_revision=view.revision, idempotency_key=uuid.uuid4().hex, passport_fields=fields,
        current_details={"client_name": "Synthetic Traveller", "client_email": "person@example.com", "client_phone": "+919876540001"}))
    return store, group, browser, member, secret, view


async def verified_contact(store, group, secret):
    provider = FakeOTP()
    proof, _, _ = await request_fresh_code(store, group.token, secret, email="person@example.com", phone="+919876540001",
        ip_address="127.0.0.1", provider=provider, limiter=FakeLimiter())
    await verify_fresh_code(store, group.token, secret, challenge_id=proof, code=provider.code)
    return proof


@pytest.mark.asyncio
async def test_fresh_resume_owns_images_and_does_not_create_source(db_session, test_settings):
    store, group, browser, member, secret, view = await fresh_context(db_session, test_settings)
    resumed = await start_fresh_draft(store, group.token, secret, member)
    assert resumed.id == view.id and resumed.documents == view.documents
    assert resumed.current_details["client_phone"] == "+919876540001"
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0
    other = fresh_secret(store, group.token, browser, uuid.uuid4().hex)
    with pytest.raises(ReuseError):
        await require_fresh_draft(store, group.token, other)
    another_browser = fresh_secret(store, group.token, uuid.uuid4().hex, member)
    with pytest.raises(ReuseError):
        await require_fresh_draft(store, group.token, another_browser)


@pytest.mark.asyncio
async def test_fresh_final_reuses_normal_proof_and_verification_atomically(db_session, test_settings):
    store, group, _, member, secret, _ = await fresh_context(db_session, test_settings)
    proof = await verified_contact(store, group, secret)
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0
    view = await draft_view(store, await require_fresh_draft(store, group.token, secret))
    body = FreshDraftComplete(expected_revision=view.revision, phone_verification_id=proof,
        idempotency_key=uuid.uuid4().hex, information_confirmed=True)
    result = await complete(group.token, body, secret=secret, session_id=member, service=store)
    assert result.status == "submitted"
    assert await complete(group.token, body, secret=secret, session_id=member, service=store) == result
    source = await db_session.get(PassportSubmissionModel, result.source_submission_id)
    assert source.status == "submitted" and source.client_phone == "+919876540001"
    assert source.image_s3_key.startswith("returning-drafts/") and source.client_reviewed_at is not None
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 1
    assert await db_session.scalar(select(func.count()).select_from(PassportPostSubmissionVerificationJobModel)) == 1
    saved_proof = await db_session.get(PublicUploadContactChallengeModel, source.id)
    assert saved_proof.id == proof and saved_proof.status == "consumed" and saved_proof.verified_at is not None
    asset = await db_session.scalar(select(Asset).where(Asset.draft_id == view.id))
    assert asset.state == "adopted"


@pytest.mark.asyncio
async def test_contact_attempts_persist_and_phone_change_requires_another_proof(db_session, test_settings):
    store, group, _, member, secret, _ = await fresh_context(db_session, test_settings)
    provider = FakeOTP()
    proof, _, _ = await request_fresh_code(store, group.token, secret, email="person@example.com", phone="+919876540001",
        ip_address="127.0.0.1", provider=provider, limiter=FakeLimiter())
    with pytest.raises(ReuseError):
        await verify_fresh_code(store, group.token, secret, challenge_id=proof, code="000000" if provider.code != "000000" else "000001")
    row = await db_session.get(Proof, proof)
    assert row.attempt_count == 1
    await verify_fresh_code(store, group.token, secret, challenge_id=proof, code=provider.code)
    draft = await require_fresh_draft(store, group.token, secret)
    view = await draft_view(store, draft)
    view = await save_owned_draft(store, draft, DraftSave(expected_revision=view.revision, idempotency_key=uuid.uuid4().hex,
        passport_fields=view.passport_fields, current_details={**view.current_details, "client_phone": "+919876540002"}))
    with pytest.raises(ReuseError):
        await complete(group.token, FreshDraftComplete(expected_revision=view.revision, phone_verification_id=proof,
            idempotency_key=uuid.uuid4().hex, information_confirmed=True), secret=secret, session_id=member, service=store)
    await db_session.rollback()
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("member_index,allowed", [(0, True), (1, False)])
async def test_fresh_family_preserves_verified_head_rule_and_final_rollback(db_session, test_settings, member_index, allowed):
    from fastapi import HTTPException

    from app.application.travellers.fresh_draft_contracts import FreshCollection
    store, group, _, member, secret, view = await fresh_context(db_session, test_settings)
    view = await save_owned_draft(store, await require_fresh_draft(store, group.token, secret), DraftSave(
        expected_revision=view.revision, idempotency_key=uuid.uuid4().hex,
        passport_fields=view.passport_fields, current_details=view.current_details,
        collection=FreshCollection(submission_mode="family", family_group_id=uuid.uuid4(),
            family_member_index=member_index, family_relation="Self" if member_index == 0 else "Spouse",
            family_head_name="Synthetic Traveller", family_head_email="person@example.com", family_head_phone="+919876540001")))
    proof = await verified_contact(store, group, secret)
    view = await draft_view(store, await require_fresh_draft(store, group.token, secret))
    body = FreshDraftComplete(expected_revision=view.revision, phone_verification_id=proof,
        idempotency_key=uuid.uuid4().hex, information_confirmed=True)
    if allowed:
        result = await complete(group.token, body, secret=secret, session_id=member, service=store)
        source = await db_session.get(PassportSubmissionModel, result.source_submission_id)
        assert source.submission_mode == "family" and source.family_member_index == 0
    else:
        with pytest.raises(HTTPException) as denied:
            await complete(group.token, body, secret=secret, session_id=member, service=store)
        assert denied.value.detail["code"] == "FAMILY_CONTACT_VERIFICATION_REQUIRED"
        await db_session.rollback()
        assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0
        row = await db_session.get(Proof, proof)
        assert row.status == "verified"
        assert (await db_session.scalar(select(Asset).where(Asset.draft_id == view.id))).state == "ready"


@pytest.mark.asyncio
async def test_fresh_final_preserves_actual_extraction_separate_from_edited_fields(db_session, test_settings):
    store, group, _, member, secret, view = await fresh_context(db_session, test_settings)
    original = view.passport_fields["surname"]
    view = await save_owned_draft(store, await require_fresh_draft(store, group.token, secret), DraftSave(
        expected_revision=view.revision, idempotency_key=uuid.uuid4().hex,
        passport_fields={**view.passport_fields, "surname": "EDITED SURNAME"}, current_details=view.current_details))
    proof = await verified_contact(store, group, secret)
    view = await draft_view(store, await require_fresh_draft(store, group.token, secret))
    result = await complete(group.token, FreshDraftComplete(expected_revision=view.revision, phone_verification_id=proof,
        idempotency_key=uuid.uuid4().hex, information_confirmed=True), secret=secret, session_id=member, service=store)
    source = await db_session.get(PassportSubmissionModel, result.source_submission_id)
    assert source.confirmed_fields["surname"] == "EDITED SURNAME"
    assert source.extracted_fields["surname"] == original
