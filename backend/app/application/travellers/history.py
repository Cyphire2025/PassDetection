"""Allowlisted review data with lazy protected assets and frozen revision IDs."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import NamedTuple

from sqlalchemy import select

from app.application.platform_policies import PlatformPolicies
from app.application.travellers.asset_policy import is_reviewable_asset
from app.application.travellers.audit import record_history_action
from app.application.travellers.authority import ReuseScope, accepted_document
from app.application.travellers.claims import ReturningClaims
from app.application.travellers.current_details import detail_fields
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.grants import require_grant
from app.application.travellers.passport_selection import available_passports
from app.application.travellers.requirements import (
    missing_document_requirements,
    saved_current_answers,
)
from app.domain.services.traveller_suitability import TravelDocument, assess_document
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerContactBindingModel,
    TravellerDocumentAssetModel,
    TravellerDocumentRevisionModel,
    TravellerHistoryGrantModel,
    TravellerParticipationModel,
    TravellerPassportModel,
    TravellerProfileModel,
)
from app.infrastructure.repositories.platform_policy_repository import PlatformPolicyRepository

PASSPORT_REVIEW_FIELDS = frozenset({
    "surname", "given_names", "full_name", "passport_number", "nationality", "sex", "gender",
    "date_of_birth", "place_of_birth", "date_of_issue", "issue_date", "date_of_expiry", "expiry_date",
    "place_of_issue", "issuing_country", "issuing_authority", "document_type",
})


def question_version(group: ClientGroupModel, policies: PlatformPolicies | None = None) -> str:
    """Content version changes only when current collection requirements change."""
    configuration = {
        "questions": group.custom_questions, "details": group.custom_details,
        "upload_configuration": group.upload_configuration, "require_selfie": group.require_selfie,
        "base_city_enabled": group.base_city_enabled, "staff_code_enabled": group.staff_code_enabled,
        "agent_employee_code_enabled": group.agent_employee_code_enabled,
        "designation_enabled": group.designation_enabled, "meal_preference_enabled": group.meal_preference_enabled,
        "agency_dealership_name_enabled": group.agency_dealership_name_enabled,
        "relation_with_qualifier_enabled": group.relation_with_qualifier_enabled,
        "departure_cities": group.departure_cities,
        "ask_nearest_domestic_airport": group.ask_nearest_domestic_airport,
        "nearest_international_airport_enabled": group.nearest_international_airport_enabled,
        "require_client_email": policies.require_client_email if policies else False,
        "require_client_phone": policies.require_client_phone if policies else False,
    }
    return hashlib.sha256(json.dumps(configuration, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class ReviewContext(NamedTuple):
    grant: TravellerHistoryGrantModel
    scope: ReuseScope
    person: TravellerProfileModel
    passport: TravellerPassportModel | None
    revision: TravellerDocumentRevisionModel | None
    assets: list[TravellerDocumentAssetModel]


async def review_context(service: ReturningClaims, token: str) -> ReviewContext:
    grant, scope, person = await require_grant(service, token, "history:read")
    selected = grant.actor_evidence.get("review_passport_id")
    try:
        selected_id = uuid.UUID(str(selected)) if selected else None
    except ValueError as exc:
        raise ReuseError(ReuseReason.UNAVAILABLE) from exc
    passport = await service.session.scalar(select(TravellerPassportModel).where(
        TravellerPassportModel.agency_id == grant.agency_id,
        TravellerPassportModel.company_id == grant.company_id,
        TravellerPassportModel.traveller_id == person.id,
        TravellerPassportModel.status == "accepted",
        TravellerPassportModel.id == selected_id if selected_id else TravellerPassportModel.is_default.is_(True),
    ))
    if passport is None:
        # Historical proof may identify the person, but cannot reactivate an old
        # superseded passport as a future-trip default.
        return ReviewContext(grant, scope, person, None, None, [])
    _, revision = await accepted_document(service.session, agency_id=grant.agency_id,
        company_id=grant.company_id, traveller_id=person.id, passport_id=passport.id, crypto=service.crypto)
    assets = list((await service.session.scalars(select(TravellerDocumentAssetModel).where(
        TravellerDocumentAssetModel.agency_id == grant.agency_id,
        TravellerDocumentAssetModel.company_id == grant.company_id,
        TravellerDocumentAssetModel.traveller_id == person.id,
        TravellerDocumentAssetModel.document_revision_id == revision.id,
        TravellerDocumentAssetModel.kind == "original",
    ).order_by(TravellerDocumentAssetModel.id).limit(16))).all())
    return ReviewContext(grant, scope, person, passport, revision, assets)


async def read_history(service: ReturningClaims, token: str, *, commit: bool = True, expected_group_token: str | None = None) -> dict[str, object]:
    context = await review_context(service, token)
    grant, scope, person, passport, revision, assets = context
    if expected_group_token is not None and scope.group.token != expected_group_token:
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    policies = await PlatformPolicyRepository(service.session).load()
    result = await project_history(service, context, policies)
    if commit:
        await record_history_action(service.session, grant, "history_viewed")
        await service.session.commit()
    return result


def review_version(service: ReturningClaims, context: ReviewContext, policies: PlatformPolicies) -> str:
    """Bind a confirmation to the exact reviewed identity, document and trip."""
    grant, scope, person, passport, revision, _ = context
    return service.crypto.digest("review-version", json.dumps({
        "grant": str(grant.id), "person": str(person.id), "profile_revision": person.revision,
        "contact_revision": person.contact_revision, "authorization_version": person.authorization_version,
        "passport": str(passport.id) if passport else None,
        "document_revision": str(revision.id) if revision else None,
        "questions": question_version(scope.group, policies),
        "travel_date": str(scope.group.travel_date), "destination": scope.group.destination,
    }, sort_keys=True, separators=(",", ":")))


async def project_history(service: ReturningClaims, context: ReviewContext, policies: PlatformPolicies) -> dict[str, object]:
    """Project an already locked context without committing/releasing authority."""
    grant, scope, person, passport, revision, assets = context
    now = datetime.now(UTC)
    raw_fields = json.loads(service.crypto.decrypt(revision.fields_ciphertext)) if revision is not None else {}
    if not isinstance(raw_fields, dict):
        raise ReuseError(ReuseReason.INFRASTRUCTURE)
    fields = {key: value for key, value in raw_fields.items() if key in PASSPORT_REVIEW_FIELDS and isinstance(value, str)}
    phone_ciphertext = await service.session.scalar(select(TravellerContactBindingModel.value_ciphertext).where(
        TravellerContactBindingModel.agency_id == grant.agency_id,
        TravellerContactBindingModel.company_id == grant.company_id,
        TravellerContactBindingModel.traveller_id == person.id,
        TravellerContactBindingModel.kind == "phone", TravellerContactBindingModel.status == "current",
    ).limit(1))
    participation = await service.session.scalar(select(TravellerParticipationModel).where(
        TravellerParticipationModel.agency_id == grant.agency_id,
        TravellerParticipationModel.company_id == grant.company_id,
        TravellerParticipationModel.group_id == grant.group_id,
        TravellerParticipationModel.traveller_id == person.id,
    ).limit(1))
    available_sides = {asset.document_side for asset in assets if is_reviewable_asset(asset, now)}
    missing = missing_document_requirements(scope.group, available_sides)
    suitability = assess_document(TravelDocument(
        issuing_country=passport.issuing_country if passport else None,
        nationality=fields.get("nationality"), document_type=passport.document_type if passport else None,
        issue_date=revision.issue_date if revision else None, expiry_date=revision.expiry_date if revision else None,
        accepted=revision is not None, available="front" in available_sides,
        lifecycle=passport.status if passport else "unusable",
    ), travel_date=scope.group.travel_date, today=now.date(),
       destinations=(scope.group.destination,) if scope.group.destination else (), rules=())
    result: dict[str, object] = {
        "display_name": service.crypto.decrypt(person.display_name_ciphertext) if person.display_name_ciphertext else "Traveller",
        "contact_phone": service.crypto.decrypt(phone_ciphertext) if phone_ciphertext else None,
        "passport": {
            "id": passport.id,
            "number": service.crypto.decrypt(passport.number_ciphertext),
            "issuing_country": passport.issuing_country, "document_type": passport.document_type,
            "date_of_birth": revision.date_of_birth, "issue_date": revision.issue_date,
            "expiry_date": revision.expiry_date, "revision": revision.revision_number,
        } if passport is not None and revision is not None else None,
        "extracted_fields": fields,
        "documents": [{"id": str(asset.id), "label": asset.document_side.replace("_", " ").title(),
            "content_type": asset.content_type, "available": is_reviewable_asset(asset, now)} for asset in assets],
        "suitability": {"outcome": suitability.outcome.value, "reason_codes": list(suitability.reason_codes)},
        "group_requirements": {"custom_questions": scope.group.custom_questions,
            "custom_details": scope.group.custom_details, "require_selfie": scope.group.require_selfie,
            "require_contact_phone": policies.require_client_phone,
            "current_detail_fields": detail_fields(scope.group, policies)},
        "missing_requirements": missing,
        "question_version": question_version(scope.group, policies),
        "review_version": review_version(service, context, policies),
        "participation_revision": participation.revision if participation else None,
        "saved_answers": saved_current_answers(participation, scope.group, policies),
        "available_passports": await available_passports(service, agency_id=grant.agency_id,
            company_id=grant.company_id, traveller_id=person.id),
    }
    return result
