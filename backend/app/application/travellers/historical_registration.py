"""Bounded historical source registration records operator authority, not consent.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.travellers.enrollment import EnrollmentRequest, enroll_submission
from app.application.travellers.historical_document_generation import (
    historical_enrollment_key,
    registration_is_current,
)
from app.application.travellers.identity_index import (
    IdentityMatch,
    find_exact_identity,
    replace_identity_evidence,
)
from app.application.travellers.retained_authority import OPERATOR_REGISTRATION_VERSION
from app.application.travellers.source_evidence import source_evidence_digest
from app.application.travellers.versioning import EnrollmentError
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES
from app.domain.services.traveller_identity import IdentityEvidence, identity_evidence
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerContactBindingModel,
    TravellerDocumentRevisionModel,
    TravellerIdentifierModel,
    TravellerMatchCaseModel,
    TravellerParticipationModel,
    TravellerPassportModel,
    TravellerProfileModel,
    TravellerReusePolicyModel,
)
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto


async def register_historical_source(session: AsyncSession, *, group: ClientGroupModel,
    source_id: uuid.UUID, policy: TravellerReusePolicyModel | None, crypto: TravellerReuseCrypto,
    now: datetime,
) -> uuid.UUID | None:
    """Group/company locks belong to caller. Per-source work is bounded/indexed."""
    source = await session.scalar(select(PassportSubmissionModel).where(
        PassportSubmissionModel.id == source_id, PassportSubmissionModel.agency_id == group.agency_id,
        PassportSubmissionModel.group_id == group.id,
        PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES)))
    if source is None or group.company_id is None:
        return None
    policy = policy if policy is not None and policy.enabled and policy.configured_by_user_id is not None else None
    case = await session.scalar(select(TravellerMatchCaseModel).where(
        TravellerMatchCaseModel.agency_id == group.agency_id, TravellerMatchCaseModel.company_id == group.company_id,
        TravellerMatchCaseModel.group_id == group.id, TravellerMatchCaseModel.source_kind == "passport_submission",
        TravellerMatchCaseModel.source_row_key == str(source.id)).with_for_update())
    if case is not None and (case.status == "purged" or case.reason_code == "authorized_replacement_candidate"):
        return case.traveller_id
    if "reuse_document_revision_id" in (source.staff_metadata or {}):
        return await _register_reuse_snapshot(session, group, source, case, now)
    fields = {**(source.extracted_fields or {}), **(source.confirmed_fields or {}), **(source.staff_metadata or {})}
    evidence = identity_evidence(fields, name=source.client_name, phone=source.client_phone, email=source.client_email)
    original, already_processed = await _resolved_person(session, case, group, source, crypto)
    if already_processed:
        return case.traveller_id if case else None
    match = await find_exact_identity(session, agency_id=group.agency_id, company_id=group.company_id,
        evidence=evidence, crypto=crypto)
    if original is not None and match.traveller_id != original.id and (
            case is None or case.evidence.get("source_identity_digest") != _identity_digest(crypto, source, evidence)):
        # A durable historical association is never redirected by later edits.
        if case is not None:
            case.evidence = {**case.evidence, "document_registration_reason": "source_identity_changed"}
        return original.id
    person = original or (await session.scalar(select(TravellerProfileModel).where(
        TravellerProfileModel.id == match.traveller_id, TravellerProfileModel.agency_id == group.agency_id,
        TravellerProfileModel.company_id == group.company_id).with_for_update()) if match.traveller_id else None)
    if person is None:
        person = await _new_private_person(session, group, source, evidence, match, crypto)
    document_error = await _register_document(session, group, source, person, policy, crypto, now)
    await _source_membership(session, group, source, person, now)
    _record_source_case(session, group, source, person, case, original, match, policy, document_error, evidence, crypto, now)
    await session.flush()
    return person.id


async def _register_reuse_snapshot(session: AsyncSession, group: ClientGroupModel,
    source: PassportSubmissionModel, case: TravellerMatchCaseModel | None, now: datetime,
) -> uuid.UUID | None:
    """Existing trip linkage, never copied fields, proves this retained snapshot."""
    metadata = source.staff_metadata or {}
    try:
        person_id = uuid.UUID(str(metadata["reuse_traveller_id"]))
        document_id = uuid.UUID(str(metadata["reuse_document_revision_id"]))
    except (ValueError, KeyError, TypeError):
        return None
    linked = await session.scalar(select(TravellerParticipationModel.id).join(TravellerDocumentRevisionModel,
        (TravellerDocumentRevisionModel.id == TravellerParticipationModel.document_revision_id)
        & (TravellerDocumentRevisionModel.traveller_id == TravellerParticipationModel.traveller_id)
        & (TravellerDocumentRevisionModel.agency_id == TravellerParticipationModel.agency_id)
        & (TravellerDocumentRevisionModel.company_id == TravellerParticipationModel.company_id)).where(
        TravellerParticipationModel.agency_id == group.agency_id, TravellerParticipationModel.company_id == group.company_id,
        TravellerParticipationModel.group_id == group.id, TravellerParticipationModel.source_submission_id == source.id,
        TravellerParticipationModel.traveller_id == person_id, TravellerParticipationModel.document_revision_id == document_id))
    if linked is None:
        return None
    if case is None:
        case = TravellerMatchCaseModel(agency_id=group.agency_id, company_id=group.company_id, group_id=group.id,
            source_kind="passport_submission", source_row_key=str(source.id), revision=1)
        session.add(case)
    case.status, case.traveller_id, case.reason_code = "resolved", person_id, "retained_trip_snapshot"
    case.resolved_at = now
    case.source_created_at = source.created_at
    case.evidence = {"source_revision": source.extraction_revision, "document_revision_id": str(document_id),
        "authority_kind": "existing_trip_participation", "information_confirmed": source.client_reviewed_at is not None}
    return person_id


async def _resolved_person(session: AsyncSession, case: TravellerMatchCaseModel | None, group: ClientGroupModel,
    source: PassportSubmissionModel, crypto: TravellerReuseCrypto,
) -> tuple[TravellerProfileModel | None, bool]:
    if case is None or case.status != "resolved" or case.traveller_id is None:
        return None, False
    person = await session.scalar(select(TravellerProfileModel).where(
        TravellerProfileModel.id == case.traveller_id, TravellerProfileModel.agency_id == group.agency_id,
        TravellerProfileModel.company_id == group.company_id).with_for_update())
    if person is None or person.deleted_at is not None:
        return person, True
    await _backfill_index(session, person, crypto)
    document = await session.scalar(select(TravellerDocumentRevisionModel).where(
        TravellerDocumentRevisionModel.agency_id == group.agency_id,
        TravellerDocumentRevisionModel.company_id == group.company_id, TravellerDocumentRevisionModel.traveller_id == person.id,
        TravellerDocumentRevisionModel.source_submission_id == source.id,
        TravellerDocumentRevisionModel.source_provenance["extraction_revision"].as_integer() == source.extraction_revision)
        .order_by(TravellerDocumentRevisionModel.accepted_at.desc(), TravellerDocumentRevisionModel.created_at.desc(), TravellerDocumentRevisionModel.id.desc()).limit(1))
    return person, registration_is_current(document, source, crypto)


async def _new_private_person(session: AsyncSession, group: ClientGroupModel, source: PassportSubmissionModel,
    evidence: IdentityEvidence, match: IdentityMatch, crypto: TravellerReuseCrypto,
) -> TravellerProfileModel:
    assert group.company_id is not None
    person = TravellerProfileModel(agency_id=group.agency_id, company_id=group.company_id,
        status="review_required" if match.status in {"ambiguous", "conflicting"} else "active",
        display_name_ciphertext=crypto.encrypt(source.client_name), reuse_permission_status="unknown",
        reuse_permission_evidence={"authority_kind": "private_history_v1", "source_submission_id": str(source.id)})
    session.add(person)
    await session.flush()
    await replace_identity_evidence(session, person=person, evidence=evidence, crypto=crypto,
        source={"source_submission_id": str(source.id), "source_extraction_revision": source.extraction_revision})
    for kind in ("phone", "email"):
        values = evidence.get(kind)
        if len(values) == 1 and kind not in evidence.conflicts:
            value = next(iter(values))
            session.add(TravellerContactBindingModel(agency_id=group.agency_id, company_id=group.company_id,
                traveller_id=person.id, kind=kind, status="current", value_ciphertext=crypto.encrypt(value),
                value_fingerprint=crypto.scoped_digest(kind, group.agency_id, group.company_id, value),
                fingerprint_key_version=crypto.key_version, verified_at=None,
                verification_evidence={"source": "historical_unverified", "source_submission_id": str(source.id)}))
    return person


async def _register_document(session: AsyncSession, group: ClientGroupModel, source: PassportSubmissionModel,
    person: TravellerProfileModel, policy: TravellerReusePolicyModel | None, crypto: TravellerReuseCrypto, now: datetime,
) -> str | None:
    if policy is None or policy.configured_by_user_id is None:
        return "private_history_only"
    if person.reuse_permission_status == "unknown" and person.reuse_permission_evidence.get("authority_kind") in {
            "private_history_v1", OPERATOR_REGISTRATION_VERSION}:
        person.reuse_permission_evidence = {**person.reuse_permission_evidence,
            "authority_kind": OPERATOR_REGISTRATION_VERSION, "actor_user_id": str(policy.configured_by_user_id),
            "policy_revision": policy.revision, "notice_version": policy.notice_version}
    if person.status != "active":
        return "identity_review_required"
    assert group.company_id is not None
    try:
        # An invalid document must not drop its historical source association.
        async with session.begin_nested():
            await enroll_submission(session, EnrollmentRequest(agency_id=group.agency_id,
                company_id=group.company_id, group_id=group.id, submission_id=source.id,
                actor_id=policy.configured_by_user_id, expected_group_revision=group.company_revision,
                expected_extraction_revision=source.extraction_revision,
                permission_evidence_reference=f"operator-policy:{policy.revision}",
                idempotency_key=historical_enrollment_key(source, group.company_id, crypto),
                traveller_id=person.id, expected_profile_revision=person.revision,
                authority_kind="operator_registration"), crypto, now=now)
    except EnrollmentError as exc:
        await session.refresh(person)
        return str(exc)
    return None


async def _source_membership(session: AsyncSession, group: ClientGroupModel, source: PassportSubmissionModel,
    person: TravellerProfileModel, now: datetime,
) -> None:
    member = await session.scalar(select(TravellerParticipationModel.id).where(
        TravellerParticipationModel.agency_id == group.agency_id, TravellerParticipationModel.company_id == group.company_id,
        TravellerParticipationModel.group_id == group.id, TravellerParticipationModel.traveller_id == person.id))
    if member is None:
        session.add(TravellerParticipationModel(agency_id=group.agency_id, company_id=group.company_id,
            traveller_id=person.id, group_id=group.id, source_submission_id=source.id,
            source_kind="historical_registration", source_row_key=str(source.id), status="accepted",
            profile_revision=person.revision, contact_revision=person.contact_revision,
            question_version="historical_source", answers={},
            confirmations={"authority_kind": "historical_source", "information_confirmed": False},
            idempotency_key=f"history-source:{source.id}", accepted_at=now, trip_started_at=group.travel_date))


def _record_source_case(session: AsyncSession, group: ClientGroupModel, source: PassportSubmissionModel,
    person: TravellerProfileModel, case: TravellerMatchCaseModel | None, original: TravellerProfileModel | None,
    match: IdentityMatch, policy: TravellerReusePolicyModel | None, document_error: str | None,
    evidence: IdentityEvidence, crypto: TravellerReuseCrypto, now: datetime,
) -> None:
    if case is None:
        case = TravellerMatchCaseModel(agency_id=group.agency_id, company_id=group.company_id, group_id=group.id,
            source_kind="passport_submission", source_row_key=str(source.id), revision=1)
        session.add(case)
    if original is None:
        case.status, case.traveller_id, case.reason_code = "resolved", person.id, "operator_historical_registration"
        case.resolved_at = now
    case.source_created_at = source.created_at
    case.evidence = {**(case.evidence or {}), "source_revision": source.extraction_revision,
        "policy_revision": policy.revision if policy else None,
        "actor_user_id": str(policy.configured_by_user_id) if policy else None,
        "possible_duplicate": match.status in {"ambiguous", "conflicting"} or match.reason == "three_independent_types_required",
        "document_registration_reason": document_error,
        "association_reason": match.reason, "matching_types": list(match.matching_types),
        "authority_kind": OPERATOR_REGISTRATION_VERSION if policy else "private_history_v1",
        "source_identity_digest": _identity_digest(crypto, source, evidence)}


def _identity_digest(crypto: TravellerReuseCrypto, source: PassportSubmissionModel, evidence: IdentityEvidence) -> str:
    return crypto.scoped_digest("historical-source-identity", source.agency_id, source.group_id,
        source_evidence_digest(crypto, source), json.dumps(evidence.values), json.dumps(sorted(evidence.conflicts)))


async def _backfill_index(session: AsyncSession, person: TravellerProfileModel, crypto: TravellerReuseCrypto) -> None:
    """Backfill old profiles from their current accepted version, not old trips."""
    if not person.display_name_ciphertext:
        return
    indexed = await session.scalar(select(TravellerIdentifierModel.id).where(
        TravellerIdentifierModel.agency_id == person.agency_id, TravellerIdentifierModel.company_id == person.company_id,
        TravellerIdentifierModel.traveller_id == person.id, TravellerIdentifierModel.identifier_type == "identity_v1:name")
        .limit(1))
    if indexed is not None:
        return
    revision = await session.scalar(select(TravellerDocumentRevisionModel).join(TravellerPassportModel,
        TravellerPassportModel.id == TravellerDocumentRevisionModel.passport_id).where(
        TravellerDocumentRevisionModel.agency_id == person.agency_id,
        TravellerDocumentRevisionModel.company_id == person.company_id,
        TravellerDocumentRevisionModel.traveller_id == person.id,
        TravellerDocumentRevisionModel.status == "accepted", TravellerPassportModel.is_default.is_(True),
        TravellerPassportModel.status == "accepted")
        .order_by(TravellerDocumentRevisionModel.revision_number.desc()).limit(1))
    if revision is None:
        return
    fields = json.loads(crypto.decrypt(revision.fields_ciphertext))
    source = await session.get(PassportSubmissionModel, revision.source_submission_id) if revision.source_submission_id else None
    if source is not None and source.agency_id == person.agency_id:
        fields = {**fields, **(source.staff_metadata or {})}
    contacts = (await session.execute(select(TravellerContactBindingModel.kind, TravellerContactBindingModel.value_ciphertext)
        .where(TravellerContactBindingModel.agency_id == person.agency_id,
            TravellerContactBindingModel.company_id == person.company_id,
            TravellerContactBindingModel.traveller_id == person.id, TravellerContactBindingModel.status == "current")
        .limit(3))).all()
    for kind, value in contacts:
        fields[kind] = crypto.decrypt(value)
    await replace_identity_evidence(session, person=person,
        evidence=identity_evidence(fields, name=crypto.decrypt(person.display_name_ciphertext)), crypto=crypto,
        source={"document_revision_id": str(revision.id), "backfill": True})
