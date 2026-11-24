"""The disposable browser helper captures delivery without manufacturing proof."""
import hashlib
import importlib
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.application.travellers.draft_contracts import DraftSave
from app.application.travellers.draft_store import FreshDraftStore
from app.application.travellers.draft_uploads import store_draft_document
from app.application.travellers.drafts import draft_view, save_owned_draft
from app.application.travellers.errors import ReuseError
from app.application.travellers.fresh_contact import verify_fresh_code
from app.application.travellers.fresh_draft_contracts import FreshCollection, FreshDraftComplete
from app.application.travellers.fresh_drafts import (
    fresh_secret,
    require_fresh_draft,
    start_fresh_draft,
)
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftContactProofModel as Proof,
)
from app.presentation.api.v1.routes.fresh_draft_completion import complete
from tests.integration.test_returning_drafts import MemoryStorage
from tests.integration.traveller_reuse_fixtures import FakeLimiter, reuse_context


class StoredImages(MemoryStorage):
    async def get_file(self, key):
        return self.files[key]


@pytest.fixture
async def qualification(db_session, test_settings, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts/qa"))
    fixture = importlib.import_module("fresh_browser_workflow")
    monkeypatch.setattr(fixture, "get_settings", lambda: SimpleNamespace(database=SimpleNamespace(db="passdetection_ci_browser")))
    limiter = FakeLimiter()
    monkeypatch.setattr(fixture, "PublicUploadOTPRateLimiter", lambda: limiter)
    storage = StoredImages()
    monkeypatch.setattr(fixture, "MinioStorageRepository", lambda: storage)
    service, _, group = await reuse_context(db_session, test_settings)
    group.token = "enterprise-browser-public-chromium-qa"
    group.require_selfie = False
    group.upload_configuration = {"passport_upload_pages": ["cover", "back_cover"], "passport_live_scan": False,
        "visa_photo_required": False, "required_fields": {key: False for key in ("base_city", "nearest_domestic_airport",
            "departure_city", "staff_code", "agent_employee_code", "designation", "agency_dealership_name", "meal_preference", "relation_with_qualifier")}}
    await db_session.commit()
    store = FreshDraftStore(db_session, test_settings, service.crypto)
    body = {"group_token": group.token, "browser_secret": uuid.uuid4().hex, "session_id": uuid.uuid4().hex,
        "email": "qualification@example.com", "phone_number": "+919876540001"}
    secret = fresh_secret(store, group.token, body["browser_secret"], body["session_id"])
    view = await start_fresh_draft(store, group.token, secret, body["session_id"])
    await save_owned_draft(store, await require_fresh_draft(store, group.token, secret), DraftSave(
        expected_revision=view.revision, idempotency_key=uuid.uuid4().hex,
        current_details={"client_name": "Synthetic Traveller", "client_email": body["email"], "client_phone": body["phone_number"]},
        collection=FreshCollection(acquisition_mode="file", submission_mode="single")))
    return fixture, store, body, secret, storage


@pytest.mark.asyncio
async def test_capture_requires_real_code_and_publishes_actual_stored_covers_once(qualification):
    fixture, store, body, secret, storage = qualification
    for side in ("cover", "back_cover"):
        view = await draft_view(store, await require_fresh_draft(store, body["group_token"], secret))
        await store_draft_document(store, authorize=lambda: require_fresh_draft(store, body["group_token"], secret),
            side=side, expected_revision=view.revision, idempotency_key=uuid.uuid4().hex,
            content=f"synthetic-{side}".encode(), content_type="image/jpeg", storage=storage)
    delivered = await fixture.request_contact(store, body)
    proof_id = uuid.UUID(delivered["response"]["challenge_id"])
    proof = await store.session.get(Proof, proof_id)
    assert proof.status == "pending" and proof.verified_at is None
    assert proof.phone_ciphertext != body["phone_number"]
    wrong = "000000" if delivered["delivered_code"] != "000000" else "000001"
    with pytest.raises(ReuseError):
        await verify_fresh_code(store, body["group_token"], secret, challenge_id=proof_id, code=wrong)
    assert proof.attempt_count == 1 and proof.status == "pending"
    assert await store.session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0
    await verify_fresh_code(store, body["group_token"], secret, challenge_id=proof_id, code=delivered["delivered_code"])
    view = await draft_view(store, await require_fresh_draft(store, body["group_token"], secret))
    submission = FreshDraftComplete(expected_revision=view.revision, phone_verification_id=proof_id,
        idempotency_key=uuid.uuid4().hex, information_confirmed=True)
    result = await complete(body["group_token"], submission, secret=secret, session_id=body["session_id"], service=store)
    assert await complete(body["group_token"], submission, secret=secret, session_id=body["session_id"], service=store) == result
    body["source_submission_id"] = str(result.source_submission_id)
    evidence = await fixture.inspect_publication(store, body)
    assert evidence["source_status"] == "needs_review"
    assert evidence["source_count"] == 1 and evidence["reviewed"] and evidence["upload_session_bound"]
    assert evidence["draft_status"] == "submitted" and evidence["same_proof"]
    assert evidence["draft_proof_status"] == evidence["published_proof_status"] == "consumed"
    assert {item["side"] for item in evidence["documents"]} == {"cover", "back_cover"}
    for item in evidence["documents"]:
        content = f"synthetic-{item['side']}".encode()
        assert item["state"] == "adopted" and item["checksum_matches"] and not item["legacy_temporary_key"]
        assert item["bytes"] == len(content) and item["sha256"] == hashlib.sha256(content).hexdigest()
    # Inspection really reads stored bytes, rather than trusting DB checksums.
    storage.files[next(iter(storage.files))] = b"changed-object"
    assert any(not item["checksum_matches"] for item in (await fixture.inspect_publication(store, body))["documents"])
    with pytest.raises(RuntimeError, match="not this submitted draft"):
        await fixture.inspect_publication(store, {**body, "source_submission_id": str(uuid.uuid4())})


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["browser_secret", "session_id"])
async def test_delivery_refuses_another_browser_or_member(qualification, field):
    fixture, store, body, _, _ = qualification
    with pytest.raises(ReuseError):
        await fixture.request_contact(store, {**body, field: uuid.uuid4().hex})
    assert await store.session.scalar(select(func.count()).select_from(Proof)) == 0


@pytest.mark.asyncio
async def test_helper_refuses_other_groups_and_nondisposable_database(qualification, monkeypatch):
    fixture, store, body, _, _ = qualification
    with pytest.raises(RuntimeError, match="dedicated browser upload groups"):
        await fixture.request_contact(store, {**body, "group_token": "unrelated-group-token"})
    monkeypatch.setattr(fixture, "get_settings", lambda: SimpleNamespace(database=SimpleNamespace(db="production")))
    with pytest.raises(RuntimeError, match="disposable"):
        await fixture.request_contact(store, body)
    assert await store.session.scalar(select(func.count()).select_from(Proof)) == 0
