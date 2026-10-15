"""Prepare final fresh source and truthful contact proof in one transaction."""
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.application.security.public_contact_proof import digest
from app.application.travellers.draft_collection import attach_draft_qualifier
from app.application.travellers.draft_contracts import DraftPayload
from app.application.travellers.draft_publication import SIDE_FIELDS
from app.application.travellers.draft_store import DraftStore
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.fresh_contact import require_fresh_contact
from app.application.travellers.fresh_draft_contracts import FreshCollection
from app.domain.entities.entities import (
    PassportExtractionStatus,
    PassportProcessingStatus,
    PassportSubmission,
)
from app.domain.exceptions.exceptions import ValidationError
from app.domain.value_objects.passport_document_classification import (
    is_accepted_passport_information_page,
)
from app.domain.value_objects.upload_configuration import (
    validate_documents,
    validate_visa_photo_source,
)
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.public_upload_contact_model import (
    PublicUploadContactChallengeModel,
)
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftAssetModel as Asset,
)
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerReturningDraftModel as Draft,
)
from app.infrastructure.mobile_group_capacity import SqlAlchemyGroupPassengerCapacityGuard
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)


async def prepare_fresh_source(service: DraftStore, draft: Draft, group: ClientGroupModel, payload: DraftPayload,
    *, upload_session_id: str, phone_proof_id: uuid.UUID, email: str, phone: str,
) -> tuple[uuid.UUID, PublicUploadContactChallengeModel]:
    proof = await require_fresh_contact(service, draft, proof_id=phone_proof_id, email=email, phone=phone)
    assets = list(await service.session.scalars(select(Asset).where(Asset.draft_id == draft.id,
        Asset.agency_id == draft.agency_id, Asset.is_current.is_(True), Asset.state == "ready").limit(5).with_for_update()))
    pending = await service.session.scalar(select(Asset.id).where(Asset.draft_id == draft.id, Asset.state == "uploading").limit(1))
    if pending:
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    collection, entity_group = payload.collection or FreshCollection(), ClientGroupRepository._to_entity(group)
    keys = {asset.side: asset.object_key for asset in assets}
    validate_documents(entity_group, pages={side: keys.get(side) for side in ("front", "back", "cover", "back_cover")},
        mode=collection.acquisition_mode, photo=keys.get("photo"))
    validate_visa_photo_source(entity_group, photo=keys.get("photo"), source=collection.visa_photo_source)
    front = next((asset for asset in assets if asset.side == "front"), None)
    classification = json.loads(service.crypto.decrypt(front.classification_ciphertext)) if front and front.classification_ciphertext else {}
    if front and (front.extraction_status != "succeeded" or not front.extraction_ciphertext or not is_accepted_passport_information_page(classification)):
        raise ValidationError("Wait for the passport check to finish before submitting.", field="file")
    repository = PassportSubmissionRepository(service.session)
    existing = await repository.get_by_upload_idempotency_key(group.id, upload_session_id)
    if existing:
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    if len(payload.current_details.get("client_name", "")) > 255:
        raise ValidationError("Traveller name must be 255 characters or fewer.", field="client_name")
    await SqlAlchemyGroupPassengerCapacityGuard(service.session).assert_available(agency_id=group.agency_id, group_id=group.id, additional_passengers=1)
    source = PassportSubmission.create(group_id=group.id, agency_id=group.agency_id,
        client_name=payload.current_details.get("client_name") or "Traveller", client_email=None,
        image_s3_key=keys.get("front", ""), acquisition_mode=collection.acquisition_mode, upload_idempotency_key=upload_session_id)
    await attach_draft_qualifier(service, entity_group, source, collection)
    for side, key in keys.items():
        setattr(source, SIDE_FIELDS[side], key)
    source.status, source.extraction_status = PassportProcessingStatus.READY_FOR_CLIENT_REVIEW, PassportExtractionStatus.COMPLETE
    extracted = DraftPayload.model_validate_json(service.crypto.decrypt(front.extraction_ciphertext)).passport_fields if front and front.extraction_ciphertext else {}
    source.extracted_fields = {**extracted, "ai_verification": classification} if front else {}
    await repository.save(source)
    published_proof = PublicUploadContactChallengeModel(submission_id=source.id, id=proof.id,
        group_id=group.id, upload_session_hash=digest("upload-session", upload_session_id), email_hash=proof.email_hash,
        phone_number=phone, code_hash=None, status="verified", attempt_count=proof.attempt_count, max_attempts=proof.max_attempts,
        expires_at=proof.expires_at, resend_available_at=proof.resend_available_at, verified_at=proof.verified_at,
        proof_expires_at=proof.proof_expires_at, created_at=proof.created_at, updated_at=datetime.now(UTC))
    service.session.add(published_proof)
    proof.status = "consumed"
    for asset in assets:
        asset.state = "adopted"
    await service.session.flush()
    return source.id, published_proof
