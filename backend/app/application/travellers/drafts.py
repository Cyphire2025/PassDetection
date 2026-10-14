"""Private autosave, O(1) scoped seeks and at most five current asset rows.

The 24h cookie retains a draft, never extends historical disclosure authority.
Every operation also needs a current person/document-specific grant.
"""
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import select

from app.application.travellers.claims import ReturningClaims
from app.application.travellers.draft_contracts import (
    DraftDocument,
    DraftPayload,
    DraftSave,
    DraftView,
)
from app.application.travellers.draft_requirements import current_answers, refresh_answers
from app.application.travellers.draft_store import DraftStore
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.history import project_history, review_context, review_version
from app.application.travellers.requirements import requirement_signatures
from app.domain.services.traveller_verification import utc
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftAssetModel as Asset,
)
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftContactProofModel as Proof,
)
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerReturningDraftModel as Draft,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerClaimModel,
    TravellerHistoryGrantModel,
)
from app.infrastructure.repositories.platform_policy_repository import PlatformPolicyRepository

DRAFT_LIFETIME = timedelta(hours=24)


async def stage_recovery_contact(service: ReturningClaims, draft: Draft, grant: TravellerHistoryGrantModel) -> None:
    evidence = grant.actor_evidence.get("pending_contact_change")
    if not isinstance(evidence, dict) or draft.verified_contact_claim_id:
        return
    claim = await service.session.scalar(select(TravellerClaimModel).where(TravellerClaimModel.id == grant.claim_id,
        TravellerClaimModel.agency_id == grant.agency_id, TravellerClaimModel.company_id == grant.company_id,
        TravellerClaimModel.group_id == grant.group_id, TravellerClaimModel.traveller_id == grant.traveller_id)
        .with_for_update().execution_options(populate_existing=True))
    if (claim is None or claim.revoked_at is not None or claim.otp_verified_at is None or not claim.phone_ciphertext
            or claim.actor_evidence.get("pending_contact_change") != evidence or evidence.get("purpose") != "pending_contact_change"
            or claim.phone_fingerprint != evidence.get("fingerprint") or claim.expected_contact_revision != draft.contact_revision):
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    draft.verified_contact_claim_id, draft.verified_phone_ciphertext = claim.id, claim.phone_ciphertext
    draft.verified_phone_fingerprint, draft.phone_verified_at = claim.phone_fingerprint, claim.otp_verified_at


def draft_payload(service: DraftStore, draft: Draft) -> DraftPayload:
    return DraftPayload.model_validate_json(service.crypto.decrypt(draft.payload_ciphertext))


async def require_draft(service: ReturningClaims, token: str, secret: str, *, submitted: bool = False) -> Draft:
    grant, _, person, passport, revision, _ = await review_context(service, token)
    if "participation:submit" not in grant.allowed_actions:
        raise ReuseError(ReuseReason.UNAVAILABLE)
    if not 32 <= len(secret) <= 128:
        raise ReuseError(ReuseReason.EXPIRED)
    draft = await service.session.scalar(select(Draft).where(Draft.secret_hash == service.crypto.digest("returning-draft", secret),
        Draft.agency_id == grant.agency_id, Draft.company_id == grant.company_id,
        Draft.group_id == grant.group_id, Draft.traveller_id == person.id).with_for_update().execution_options(populate_existing=True))
    if draft is None or utc(draft.expires_at) <= datetime.now(UTC) or draft.status not in ({"active", "submitted"} if submitted else {"active"}):
        raise ReuseError(ReuseReason.EXPIRED)
    if (passport is None or revision is None or draft.passport_id != passport.id
            or draft.document_revision_id != revision.id or draft.contact_revision != person.contact_revision
            or draft.profile_revision != person.revision or draft.authorization_version != person.authorization_version):
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    return draft


async def start_draft(service: ReturningClaims, token: str, *, expected_review_version: str, existing_secret: str | None = None) -> tuple[str, DraftView]:
    context = await review_context(service, token)
    grant, scope, person, passport, revision, _ = context
    policies = await PlatformPolicyRepository(service.session).load()
    current_version = review_version(service, context, policies)
    if passport is None or revision is None or not hmac.compare_digest(expected_review_version, current_version):
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    if existing_secret:
        previous = await service.session.scalar(select(Draft.id).where(Draft.secret_hash == service.crypto.digest("returning-draft", existing_secret),
            Draft.agency_id == grant.agency_id, Draft.company_id == grant.company_id, Draft.group_id == grant.group_id,
            Draft.traveller_id == person.id, Draft.passport_id == passport.id, Draft.document_revision_id == revision.id,
            Draft.status == "active", Draft.expires_at > datetime.now(UTC)))
        if previous:
            draft = await require_draft(service, token, existing_secret)
            if draft.review_version != current_version:
                refresh_answers(service, draft, scope.group, policies)
                draft.review_version, draft.revision = current_version, draft.revision + 1
            await stage_recovery_contact(service, draft, grant)
            result = await draft_view(service, draft)
            await service.session.commit()
            return existing_secret, result
    secret = service.crypto.digest("returning-draft-secret", grant.secret_hash, str(passport.id), str(revision.id))
    digest = service.crypto.digest("returning-draft", secret)
    previous = await service.session.scalar(select(Draft).where(Draft.secret_hash == digest).with_for_update())
    if previous:
        draft = await require_draft(service, token, secret, submitted=True)
    else:
        review = await project_history(service, context, policies)
        saved = cast(dict[str, dict[str, str]], review["saved_answers"])
        fields = {key: value for key, value in cast(dict[str, str], review["extracted_fields"]).items()
            if key in {"surname", "given_names", "passport_number", "nationality", "place_of_issue", "date_of_birth", "date_of_issue", "date_of_expiry", "sex"}}
        payload = DraftPayload.model_validate({"passport_fields": fields, **saved})
        if existing_secret:
            earlier = await service.session.scalar(select(Draft).where(Draft.secret_hash == service.crypto.digest("returning-draft", existing_secret),
                Draft.agency_id == grant.agency_id, Draft.company_id == grant.company_id, Draft.group_id == grant.group_id,
                Draft.traveller_id == person.id, Draft.status == "active", Draft.expires_at > datetime.now(UTC),
                Draft.profile_revision == person.revision, Draft.contact_revision == person.contact_revision,
                Draft.authorization_version == person.authorization_version).with_for_update())
            if earlier:
                payload = payload.model_copy(update=current_answers(service, earlier, scope.group, policies))
        now = datetime.now(UTC)
        draft = Draft(id=uuid.uuid4(), agency_id=grant.agency_id, company_id=grant.company_id,
            group_id=grant.group_id, traveller_id=person.id, passport_id=passport.id, document_revision_id=revision.id,
            secret_hash=digest, revision=1, fields_revision=1, status="active", created_at=now,
            expires_at=now + DRAFT_LIFETIME, contact_revision=person.contact_revision,
            profile_revision=person.revision, authorization_version=person.authorization_version,
            review_version=current_version, payload_ciphertext=service.crypto.encrypt(payload.model_dump_json()))
        draft.requirements_ciphertext = service.crypto.encrypt(json.dumps(requirement_signatures(scope.group, policies), sort_keys=True))
        service.session.add(draft)
        await service.session.flush()
    await stage_recovery_contact(service, draft, grant)
    result = await draft_view(service, draft)
    await service.session.commit()
    return secret, result


async def draft_view(service: DraftStore, draft: Draft) -> DraftView:
    proof = None
    if draft.mode == "fresh":
        proof = await service.session.scalar(select(Proof).where(Proof.draft_id == draft.id,
            Proof.agency_id == draft.agency_id, Proof.status == "verified", Proof.proof_expires_at > datetime.now(UTC)))
    assets = list(await service.session.scalars(select(Asset).where(Asset.draft_id == draft.id,
        Asset.agency_id == draft.agency_id, Asset.company_id == draft.company_id,
        Asset.is_current.is_(True), Asset.state == "ready").order_by(Asset.side).limit(5)))
    front = next((asset for asset in assets if asset.side == "front"), None)
    fields = DraftPayload.model_validate_json(service.crypto.decrypt(front.extraction_ciphertext)).passport_fields if front and front.extraction_ciphertext else {}
    return DraftView.model_validate({**draft_payload(service, draft).model_dump(), "id": draft.id,
        "revision": draft.revision, "expires_at": draft.expires_at, "status": draft.status,
        "verified_phone": service.crypto.decrypt(draft.verified_phone_ciphertext) if draft.verified_phone_ciphertext else None,
        "phone_verification_id": proof.id if proof else None,
        "phone_verification_expires_at": proof.proof_expires_at if proof else None,
        "participation_id": draft.participation_id if draft.status == "submitted" else None,
        "source_submission_id": draft.source_submission_id if draft.status == "submitted" else None,
        "result_status": draft.result_status if draft.status == "submitted" else None,
        "documents": [DraftDocument.model_validate({"id": asset.id, "side": asset.side, "state": asset.state}).model_dump() for asset in assets],
        "extraction_status": front.extraction_status if front else "none", "extracted_fields": fields})


async def save_draft(service: ReturningClaims, token: str, secret: str, body: DraftSave) -> DraftView:
    draft = await require_draft(service, token, secret)
    return await save_owned_draft(service, draft, body)


async def save_owned_draft(service: DraftStore, draft: Draft, body: DraftSave) -> DraftView:
    payload = DraftPayload.model_validate(body.model_dump(exclude={"expected_revision", "idempotency_key"}))
    digest = service.crypto.digest("returning-draft-save", payload.model_dump_json(), str(body.expected_revision))
    if draft.last_save_key == body.idempotency_key:
        if not hmac.compare_digest(draft.last_save_digest or "", digest):
            raise ReuseError(ReuseReason.REVISION_CONFLICT)
    else:
        if draft.revision != body.expected_revision:
            raise ReuseError(ReuseReason.REVISION_CONFLICT)
        if draft_payload(service, draft).passport_fields != payload.passport_fields:
            draft.fields_revision += 1
        draft.payload_ciphertext = service.crypto.encrypt(payload.model_dump_json())
        draft.revision += 1
        draft.last_save_key, draft.last_save_digest = body.idempotency_key, digest
    result = await draft_view(service, draft)
    await service.session.commit()
    return result
