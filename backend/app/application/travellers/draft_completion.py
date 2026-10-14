"""One final atomic publication; drafts never grant historical access."""
import hmac
import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select

from app.application.travellers.claims import ReturningClaims
from app.application.travellers.completion import complete_reuse
from app.application.travellers.current_details import normalize_current_details
from app.application.travellers.draft_contact import staged_contact_claim
from app.application.travellers.draft_contracts import DraftComplete, DraftPayload
from app.application.travellers.draft_publication import (
    apply_draft_documents,
    candidate_source,
    submit_candidate,
)
from app.application.travellers.drafts import draft_payload, require_draft
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.fresh_draft_contracts import FreshCollection
from app.application.travellers.grants import recover_contact
from app.application.travellers.history import (
    ReviewContext,
    project_history,
    review_context,
    review_version,
)
from app.application.travellers.owned_extraction import owned_extraction_candidate
from app.application.travellers.requirements import requirement_signatures
from app.domain.exceptions.exceptions import ValidationError
from app.domain.services.traveller_verification import utc
from app.domain.value_objects.custom_questions import (
    normalize_custom_answers,
    normalize_custom_detail_answers,
)
from app.domain.value_objects.passport_fields import (
    REVIEWABLE_PASSPORT_FIELDS,
    normalize_reviewed_passport_fields,
)
from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftAssetModel as Asset,
)
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerReturningDraftModel as Draft,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerParticipationModel as Participation,
)
from app.infrastructure.database.traveller_reuse_models import TravellerProfileModel as Person
from app.infrastructure.repositories.platform_policy_repository import PlatformPolicyRepository

Result = tuple[uuid.UUID, str, uuid.UUID]


async def completion_receipt(service: ReturningClaims, secret: str, body: DraftComplete) -> Result | None:
    """Exact cookie + request proof may replay only opaque committed receipt IDs."""
    if not 32 <= len(secret) <= 128:
        raise ReuseError(ReuseReason.EXPIRED)
    draft = await service.session.scalar(select(Draft).join(ClientGroupModel, ClientGroupModel.id == Draft.group_id)
        .join(ClientOrganizationModel, ClientOrganizationModel.id == Draft.company_id).join(Person, Person.id == Draft.traveller_id)
        .where(Draft.secret_hash == service.crypto.digest("returning-draft", secret), Draft.status == "submitted",
            ClientGroupModel.agency_id == Draft.agency_id, ClientGroupModel.company_id == Draft.company_id,
            ClientGroupModel.deleted_at.is_(None), ClientGroupModel.status == "active",
            ClientOrganizationModel.agency_id == Draft.agency_id, ClientOrganizationModel.status == "active",
            Person.agency_id == Draft.agency_id, Person.company_id == Draft.company_id, Person.deleted_at.is_(None))
        .execution_options(populate_existing=True))
    if draft is None:
        return None
    digest = service.crypto.digest("returning-draft-complete", body.model_dump_json())
    if (utc(draft.expires_at) <= datetime.now(UTC) or draft.completion_key != body.idempotency_key
            or not hmac.compare_digest(draft.completion_digest or "", digest)
            or not draft.participation_id or not draft.source_submission_id or not draft.result_status):
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    return draft.participation_id, draft.result_status, draft.source_submission_id


async def publish_changed_draft(service: ReturningClaims, context: ReviewContext, draft: Draft,
    body: DraftComplete, payload: DraftPayload, assets: list[Asset], original: dict[str, str], phone: str | None,
) -> Result:
    grant, scope, person, passport, revision, _ = context
    assert passport is not None and revision is not None
    policies = await PlatformPolicyRepository(service.session).load()
    payload.current_details = normalize_current_details(scope.group, policies, payload.current_details)
    if policies.require_client_phone and not phone:
        raise ValidationError("Verify a current phone number before submitting.", field="client_phone")
    questions = normalize_custom_answers(scope.group.custom_questions, [{"question_id": k, "value": v} for k, v in payload.custom_answers.items()])
    details = normalize_custom_detail_answers(scope.group.custom_details, [{"detail_id": k, "value": v} for k, v in payload.custom_detail_answers.items()])
    participation = await service.session.scalar(select(Participation).where(Participation.agency_id == draft.agency_id,
        Participation.company_id == draft.company_id, Participation.group_id == draft.group_id,
        Participation.traveller_id == draft.traveller_id).with_for_update().execution_options(populate_existing=True))
    if participation is not None and (participation.status == "withdrawn" or participation.revision != body.expected_participation_revision):
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    if participation is None:
        if body.expected_participation_revision is not None:
            raise ReuseError(ReuseReason.REVISION_CONFLICT)
        participation = Participation(id=uuid.uuid4(), agency_id=draft.agency_id, company_id=draft.company_id,
            group_id=draft.group_id, traveller_id=person.id, source_kind="returning_reuse", idempotency_key=body.idempotency_key,
            profile_revision=person.revision, contact_revision=person.contact_revision, question_version=body.question_version,
            revision=1, status="pending", confirmations={}, answers={})
        service.session.add(participation)
    fields = normalize_reviewed_passport_fields(payload.passport_fields)
    source = await candidate_source(service, context, participation, fields=fields, phone=phone)
    apply_draft_documents(service, context, source, assets, fields, original, payload.collection or FreshCollection())
    await submit_candidate(service, context, source, payload=payload, fields=fields, phone=phone,
        questions=questions, details=details, idempotency_key=body.idempotency_key)
    participation.passport_id, participation.document_revision_id = passport.id, revision.id
    participation.profile_revision, participation.contact_revision = person.revision, person.contact_revision
    participation.question_version, participation.status = body.question_version, "submitted"
    participation.answers = {"custom_answers": questions, "custom_detail_answers": details, "current_details": payload.current_details}
    participation.confirmations = {"completion_key": body.idempotency_key, "information_confirmed": True,
        "actor_kind": grant.actor_kind, "requirement_signatures": requirement_signatures(scope.group, policies),
        "confirmed_at": datetime.now(UTC).isoformat(), "document_update_pending": True}
    participation.submitted_at, participation.trip_started_at = datetime.now(UTC), scope.group.travel_date
    participation.revision += 1
    for asset in assets:
        asset.state = "adopted"
    return participation.id, participation.status, source.id


async def complete_draft(service: ReturningClaims, token: str, secret: str, body: DraftComplete, *, upload_session_id: str | None = None) -> Result:
    receipt = await completion_receipt(service, secret, body)
    if receipt:
        await service.session.commit()
        return receipt
    try:
        context = await review_context(service, token)
    except ReuseError:
        # Another identical final request may have committed while this request
        # waited for the person lock and revoked its original contact grant.
        # Only the exact committed receipt is recoverable; no history is read.
        receipt = await completion_receipt(service, secret, body)
        if receipt:
            await service.session.commit()
            return receipt
        raise
    if body.owned_source and (not upload_session_id or await owned_extraction_candidate(service.session,
            group=context.scope.group, source_submission_id=body.owned_source.source_submission_id,
            expected_extraction_revision=body.owned_source.expected_extraction_revision, upload_session_id=upload_session_id,
            crypto=service.crypto, lock_source=True) != context.person.id):
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    draft = await require_draft(service, token, secret)
    if "participation:submit" not in context.grant.allowed_actions:
        raise ReuseError(ReuseReason.UNAVAILABLE)
    policies = await PlatformPolicyRepository(service.session).load()
    review = await project_history(service, context, policies)
    if (draft.revision != body.expected_revision or review["question_version"] != body.question_version
            or not hmac.compare_digest(body.review_version, review_version(service, context, policies))):
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    pending_upload = await service.session.scalar(select(Asset.id).where(Asset.draft_id == draft.id,
        Asset.agency_id == draft.agency_id, Asset.state == "uploading").limit(1))
    if pending_upload:
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    assets = list(await service.session.scalars(select(Asset).where(Asset.draft_id == draft.id,
        Asset.agency_id == draft.agency_id, Asset.company_id == draft.company_id, Asset.is_current.is_(True),
        Asset.state == "ready").limit(5).with_for_update()))
    payload = draft_payload(service, draft)
    original = {k: v for k, v in cast(dict[str, str], review["extracted_fields"]).items() if k in REVIEWABLE_PASSPORT_FIELDS}
    contact = await staged_contact_claim(service, draft)
    phone = service.crypto.decrypt(draft.verified_phone_ciphertext) if draft.verified_phone_ciphertext else cast(str | None, review["contact_phone"])
    if assets or context.scope.group.relation_with_qualifier_enabled or normalize_reviewed_passport_fields(payload.passport_fields) != normalize_reviewed_passport_fields(original):
        suitability = cast(dict[str, object], review["suitability"])
        if not any(asset.side == "front" for asset in assets) and suitability["outcome"] in {"replacement_required", "cannot_assess"}:
            raise ReuseError(ReuseReason.INSUFFICIENT_EVIDENCE)
        result = await publish_changed_draft(service, context, draft, body, payload, assets, original, phone)
    else:
        result = await complete_reuse(service, token, requirements_version=body.question_version,
            expected_participation_revision=body.expected_participation_revision, custom_answers=payload.custom_answers,
            custom_detail_answers=payload.custom_detail_answers, current_details=payload.current_details,
            idempotency_key=body.idempotency_key, expected_review_version=body.review_version,
            owned_source_id=body.owned_source.source_submission_id if body.owned_source else None,
            owned_source_revision=body.owned_source.expected_extraction_revision if body.owned_source else None,
            upload_session_id=upload_session_id,
            commit=False, verified_phone_override=phone)
    if contact:
        await recover_contact(service, contact, context.person, datetime.now(UTC))
        participant = await service.session.get(Participation, result[0])
        assert participant is not None
        participant.contact_revision = context.person.contact_revision
    draft.status, draft.completion_key = "submitted", body.idempotency_key
    draft.completion_digest = service.crypto.digest("returning-draft-complete", body.model_dump_json())
    draft.participation_id, draft.result_status, draft.source_submission_id = result
    await service.session.commit()
    return result
