"""Publish a reviewed draft through the ordinary submission transition.

Only a current, unreviewed automatic trip snapshot may be changed in place.
Historical accepted revisions remain immutable; this source needs new review.
"""
import json
from datetime import UTC, datetime

from sqlalchemy import select

from app.application.travellers.asset_policy import is_reviewable_asset
from app.application.travellers.claims import ReturningClaims
from app.application.travellers.draft_collection import attach_draft_qualifier
from app.application.travellers.draft_contracts import DraftPayload
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.fresh_draft_contracts import FreshCollection
from app.application.travellers.history import ReviewContext
from app.application.travellers.replacement import record_replacement_candidate
from app.application.travellers.requirements import missing_document_requirements
from app.application.travellers.submission_snapshot import new_reuse_submission
from app.domain.exceptions.exceptions import ValidationError
from app.domain.value_objects.custom_questions import (
    CustomAnswerSnapshot,
    CustomDetailAnswerSnapshot,
)
from app.domain.value_objects.passport_document_classification import (
    is_accepted_passport_information_page,
)
from app.domain.value_objects.passport_fields import normalize_passport_number_identity
from app.domain.value_objects.upload_configuration import (
    configuration_for,
    validate_documents,
    validate_visa_photo_source,
)
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftAssetModel as Asset,
)
from app.infrastructure.database.traveller_reuse_models import TravellerParticipationModel
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.coordinator_assignment_lifecycle import current_trip_clause
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.verification.job_repository import PostSubmissionVerificationJobRepository

SIDE_FIELDS = {"front": "image_s3_key", "back": "passport_back_s3_key", "cover": "passport_cover_s3_key",
    "back_cover": "passport_back_cover_s3_key", "photo": "passport_photo_s3_key"}


def apply_draft_documents(service: ReturningClaims, context: ReviewContext, source: PassportSubmissionModel,
    assets: list[Asset], fields: dict[str, str], original_fields: dict[str, str], collection: FreshCollection,
) -> None:
    changed_number = normalize_passport_number_identity(fields.get("passport_number", "")) != normalize_passport_number_identity(original_fields.get("passport_number", ""))
    front = next((asset for asset in assets if asset.side == "front"), None)
    if changed_number and front is None:
        raise ValidationError("Upload the new passport before changing its number.", field="file")
    if changed_number:
        for field in SIDE_FIELDS.values():
            setattr(source, field, None if field != "image_s3_key" else "")
    if front:
        classification = json.loads(service.crypto.decrypt(front.classification_ciphertext)) if front.classification_ciphertext else {}
        if front.extraction_status != "succeeded" or not front.extraction_ciphertext or not is_accepted_passport_information_page(classification):
            raise ValidationError("Wait for the passport check to finish before submitting.", field="file")
        extracted = DraftPayload.model_validate_json(service.crypto.decrypt(front.extraction_ciphertext)).passport_fields
        source.extracted_fields = {**extracted, "ai_verification": classification}
        source.thumbnail_s3_key, source.mrz_raw = None, None
    for asset in assets:
        setattr(source, SIDE_FIELDS[asset.side], asset.object_key)
    group = ClientGroupRepository._to_entity(context.scope.group)
    config = configuration_for(group)
    new_pages = any(asset.side != "photo" for asset in assets)
    mode = collection.acquisition_mode if new_pages else "file"
    selected_pages = {"front", "back"} if new_pages and mode == "camera" else set(config.passport_upload_pages)
    supplied_pages = {asset.side for asset in assets if asset.side != "photo"}
    pages: dict[str, object] = {side: getattr(source, column) for side, column in SIDE_FIELDS.items()
        if side in selected_pages | supplied_pages}
    retained = frozenset(asset.document_side for asset in context.assets
        if is_reviewable_asset(asset, datetime.now(UTC)) and pages.get(asset.document_side) == asset.object_key)
    new_photo = any(asset.side == "photo" for asset in assets)
    validate_documents(group, pages=pages, mode=mode,
        photo=source.passport_photo_s3_key if group.require_selfie or new_photo else None, retained_pages=retained)
    if "fresh_photo" in missing_document_requirements(context.scope.group, set(retained)) and not new_photo:
        raise ValidationError("Add a current traveller photo for this trip.", field="passport_photo_file")
    if new_photo:
        validate_visa_photo_source(group, photo=source.passport_photo_s3_key, source=collection.visa_photo_source)
    if new_pages:
        source.acquisition_mode = mode


async def candidate_source(service: ReturningClaims, context: ReviewContext, participation: TravellerParticipationModel,
    *, fields: dict[str, str], phone: str | None,
) -> PassportSubmissionModel:
    grant, scope, person, _, revision, assets = context
    assert revision is not None
    source = None
    if participation.source_submission_id:
        row = (await service.session.execute(select(PassportSubmissionModel,
            current_trip_clause(datetime.now(UTC), group_model=scope.group)).where(
            PassportSubmissionModel.id == participation.source_submission_id,
            PassportSubmissionModel.agency_id == grant.agency_id, PassportSubmissionModel.group_id == grant.group_id,
        ).with_for_update().execution_options(populate_existing=True))).one_or_none()
        if row is None or not row[1]:
            raise ReuseError(ReuseReason.REVISION_CONFLICT)
        source = row[0]
        metadata = source.staff_metadata or {}
        if (metadata.get("reuse_assignment") != "automatic" or metadata.get("reuse_document_revision_id") != str(revision.id)
                or metadata.get("reuse_traveller_id") != str(person.id)):
            raise ReuseError(ReuseReason.REVISION_CONFLICT)
    if source is None:
        source = new_reuse_submission(group=scope.group, person=person, revision=revision, assets=assets,
            fields=fields, display_name=" ".join([fields.get("given_names", ""), fields.get("surname", "")]).strip(),
            phone=phone, email=None, participation_id=participation.id, now=datetime.now(UTC), traveller_confirmed=False)
        service.session.add(source)
        await service.session.flush()
        participation.source_submission_id = source.id
    return source


async def submit_candidate(service: ReturningClaims, context: ReviewContext, source: PassportSubmissionModel,
    *, payload: DraftPayload, fields: dict[str, str], phone: str | None, questions: list[CustomAnswerSnapshot], details: list[CustomDetailAnswerSnapshot],
    idempotency_key: str,
) -> None:
    entity = PassportSubmissionRepository._to_entity(source)
    await attach_draft_qualifier(service, ClientGroupRepository._to_entity(context.scope.group),
        entity, payload.collection or FreshCollection())
    entity.submit_client_review({**fields, **{k: v for k, v in payload.current_details.items() if k != "client_email"}},
        client_phone=phone, client_email=payload.current_details.get("client_email"),
        departure_city=payload.current_details.get("departure_city"), nearest_domestic_airport=payload.current_details.get("nearest_domestic_airport"),
        custom_answers=questions, custom_detail_answers=details, allow_returning_snapshot_review=True)
    entity.staff_metadata = {**(entity.staff_metadata or {}), "reuse_assignment": "traveller_update"}
    await PassportSubmissionRepository(service.session).update(entity)
    await record_replacement_candidate(service, context, source, change_kind="correction", idempotency_key=idempotency_key)
    await PostSubmissionVerificationJobRepository(service.session).enqueue(submission_id=source.id,
        verification_revision=source.post_submission_verification_revision)
