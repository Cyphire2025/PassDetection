"""Transactional trip snapshot publication from an authorized unchanged passport.

O(q+d) input validation for bounded questions/details, plus indexed person/group
lookups. No images are downloaded, OCR rerun, or prior-trip snapshots rewritten.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select

from app.application.travellers.asset_policy import is_reviewable_asset
from app.application.travellers.audit import record_history_action
from app.application.travellers.claims import ReturningClaims
from app.application.travellers.current_details import normalize_current_details
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.history import project_history, review_context, review_version
from app.application.travellers.requirements import TripAnswers, requirement_signatures
from app.domain.exceptions.exceptions import ValidationError
from app.domain.value_objects.custom_questions import (
    normalize_custom_answers,
    normalize_custom_detail_answers,
)
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerChangeEventModel,
    TravellerParticipationModel,
)
from app.infrastructure.repositories.platform_policy_repository import PlatformPolicyRepository


async def complete_reuse(
    service: ReturningClaims, token: str, *, requirements_version: str,
    expected_participation_revision: int | None, custom_answers: dict[str, str],
    custom_detail_answers: dict[str, str], current_details: dict[str, str], idempotency_key: str,
    expected_review_version: str,
) -> tuple[uuid.UUID, str]:
    # Hold one authority transaction through validation and publication. Bind
    # the caller's confirmation to what their browser actually reviewed.
    context = await review_context(service, token)
    grant, scope, person, passport, revision, assets = context
    policies = await PlatformPolicyRepository(service.session).load()
    review = await project_history(service, context, policies)
    if "participation:submit" not in grant.allowed_actions:
        raise ReuseError(ReuseReason.UNAVAILABLE)
    if review["question_version"] != requirements_version or not hmac.compare_digest(
        expected_review_version, review_version(service, context, policies),
    ):
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    if passport is None or revision is None:
        raise ReuseError(ReuseReason.INSUFFICIENT_EVIDENCE)
    suitability = review["suitability"]
    if not isinstance(suitability, dict) or suitability["outcome"] in {"replacement_required", "cannot_assess"} or review["missing_requirements"]:
        raise ReuseError(ReuseReason.INSUFFICIENT_EVIDENCE)
    saved = cast(TripAnswers, review["saved_answers"])
    details = normalize_current_details(scope.group, policies, {**saved["current_details"], **current_details})
    phone = review["contact_phone"]
    if policies.require_client_phone and not phone:
        raise ValidationError("Verify a current phone number before submitting.", field="client_phone")
    questions = normalize_custom_answers(scope.group.custom_questions,
        [{"question_id": key, "value": value} for key, value in {**saved["custom_answers"], **custom_answers}.items()])
    custom_details = normalize_custom_detail_answers(scope.group.custom_details,
        [{"detail_id": key, "value": value} for key, value in {**saved["custom_detail_answers"], **custom_detail_answers}.items()])
    payload_hash = hashlib.sha256(json.dumps({"review": expected_review_version, "questions": questions,
        "custom_details": custom_details, "details": details}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    participation = await service.session.scalar(select(TravellerParticipationModel).where(
        TravellerParticipationModel.agency_id == grant.agency_id,
        TravellerParticipationModel.company_id == grant.company_id,
        TravellerParticipationModel.group_id == grant.group_id,
        TravellerParticipationModel.traveller_id == person.id,
    ).with_for_update().execution_options(populate_existing=True))
    if participation is not None and participation.confirmations.get("completion_key") == idempotency_key:
        if participation.question_version != requirements_version or participation.confirmations.get("payload_hash") != payload_hash:
            raise ReuseError(ReuseReason.REVISION_CONFLICT)
        await service.session.commit()
        return participation.id, participation.status
    if participation is not None and participation.revision != expected_participation_revision:
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    if participation is None and expected_participation_revision is not None:
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    now = datetime.now(UTC)
    if participation is None:
        participation = TravellerParticipationModel(
            id=uuid.uuid4(), agency_id=grant.agency_id, company_id=grant.company_id,
            traveller_id=person.id, group_id=grant.group_id, source_kind="returning_reuse",
            idempotency_key=idempotency_key, profile_revision=person.revision,
            contact_revision=person.contact_revision, question_version=requirements_version,
            revision=1, status="pending", confirmations={}, answers={},
        )
        service.session.add(participation)
    if participation.status == "withdrawn":
        raise ReuseError(ReuseReason.UNAVAILABLE)
    # Accepted/submitted document references are frozen. Requirement edits may
    # refresh only answers on this same document; a changed passport uses review.
    if participation.status in {"submitted", "accepted"} and participation.document_revision_id != revision.id:
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    source = None
    if participation.source_submission_id:
        source = await service.session.scalar(select(PassportSubmissionModel).where(
            PassportSubmissionModel.id == participation.source_submission_id,
            PassportSubmissionModel.group_id == grant.group_id,
            PassportSubmissionModel.agency_id == grant.agency_id,
        ).with_for_update())
        if source is not None and (source.staff_metadata or {}).get("reuse_document_revision_id") != str(revision.id):
            # An independently uploaded/approved submission must stay in its
            # original review workflow, never be silently rewritten by reuse.
            raise ReuseError(ReuseReason.REVISION_CONFLICT)
    if source is None:
        asset_keys = {asset.document_side: asset.object_key for asset in assets if is_reviewable_asset(asset, now)}
        fields = dict(cast(dict[str, str], review["extracted_fields"]))
        source = PassportSubmissionModel(
            id=uuid.uuid4(), agency_id=grant.agency_id, group_id=grant.group_id,
            client_name=str(review["display_name"]), client_email=details.get("client_email"),
            client_phone=str(phone) if phone else None, image_s3_key=asset_keys.get("front") or "",
            passport_back_s3_key=asset_keys.get("back"), passport_cover_s3_key=asset_keys.get("cover"),
            passport_back_cover_s3_key=asset_keys.get("back_cover"), passport_photo_s3_key=asset_keys.get("photo"),
            acquisition_mode="file", upload_idempotency_key=f"reuse:{participation.id}",
            status="client_submitted", extraction_status="extraction_complete", extraction_revision=1,
            extracted_fields=fields, confirmed_fields=fields, client_reviewed_at=now,
            staff_metadata={"reuse_traveller_id": str(person.id), "reuse_document_revision_id": str(revision.id)},
        )
        service.session.add(source)
        await service.session.flush()
        participation.source_submission_id = source.id
    source.custom_answers, source.custom_detail_answers = questions, custom_details
    source.status = "client_submitted"
    source.client_reviewed_at = now
    source.departure_city, source.nearest_domestic_airport = details.get("departure_city"), details.get("nearest_domestic_airport")
    source.client_email = details.get("client_email")
    source.confirmed_fields = {**(source.confirmed_fields or {}), **{key: value for key, value in details.items() if key != "client_email"}}
    participation.passport_id, participation.document_revision_id = passport.id, revision.id
    participation.profile_revision, participation.contact_revision = person.revision, person.contact_revision
    participation.question_version = requirements_version
    participation.answers = {"custom_answers": questions, "custom_detail_answers": custom_details, "current_details": details}
    participation.confirmations = {"completion_key": idempotency_key, "payload_hash": payload_hash, "information_confirmed": True,
        "requirement_signatures": requirement_signatures(scope.group, policies),
        "actor_kind": grant.actor_kind, "suitability": suitability, "confirmed_at": now.isoformat()}
    participation.status = "submitted"
    participation.submitted_at = now
    participation.trip_started_at = scope.group.travel_date
    participation.revision += 1
    service.session.add(TravellerChangeEventModel(
        id=uuid.uuid4(), agency_id=grant.agency_id, company_id=grant.company_id,
        traveller_id=person.id, event_type="added" if participation.revision == 2 else "changed",
        aggregate_id=participation.id, aggregate_revision=participation.revision,
        idempotency_key="participation:" + hashlib.sha256(f"{participation.id}:{idempotency_key}".encode()).hexdigest(),
        reason_code="current_trip_submitted",
    ))
    await record_history_action(service.session, grant, "trip_submitted", reference=str(participation.id))
    await service.session.commit()
    return participation.id, participation.status
