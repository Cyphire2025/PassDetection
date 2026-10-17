"""Explicit staff acceptance of retained evidence; public uploads never call this.

One transaction stores immutable field revisions and pending independent asset
copies. Exact identity lookup is indexed and capped at two records. Existing
traveller association for renewal is an explicit reviewed operation with an
expected revision, never an inferred name/phone merge.
"""

from __future__ import annotations

import hmac
import json
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from typing import Literal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.travellers.reconciliation import TRUSTED_FIELD_STATUSES
from app.application.travellers.source_evidence import source_evidence_digest
from app.domain.services.traveller_verification import (
    exact_passport_number,
    issuing_context,
    parse_answer,
)
from app.domain.value_objects.passport_fields import normalize_passport_date
from app.domain.value_objects.phone_number import normalize_phone_number
from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerChangeEventModel,
    TravellerContactBindingModel,
    TravellerDocumentAssetModel,
    TravellerDocumentRevisionModel,
    TravellerGroupReuseConfigModel,
    TravellerIdentifierModel,
    TravellerMatchCaseModel,
    TravellerParticipationModel,
    TravellerPassportModel,
    TravellerProfileModel,
    TravellerReusePolicyModel,
)
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto


class EnrollmentError(ValueError):
    """Safe reason code; callers must not include source field values."""


@dataclass(frozen=True, slots=True)
class EnrollmentRequest:
    agency_id: uuid.UUID
    company_id: uuid.UUID
    group_id: uuid.UUID
    submission_id: uuid.UUID
    actor_id: uuid.UUID
    expected_group_revision: int
    expected_extraction_revision: int
    permission_evidence_reference: str
    idempotency_key: str
    traveller_id: uuid.UUID | None = None
    expected_profile_revision: int | None = None
    change_kind: Literal["initial", "renewal", "scan", "correction"] = "initial"
    reviewed_issuing_country: str | None = None
    reviewed_document_type: str | None = None
    reviewed_context_confirmed: bool = False
    candidate_association_confirmed: bool = False


@dataclass(frozen=True, slots=True)
class EnrollmentResult:
    traveller_id: uuid.UUID
    passport_id: uuid.UUID
    document_revision_id: uuid.UUID
    copies_pending: int


async def enroll_submission(
    session: AsyncSession, request: EnrollmentRequest, crypto: TravellerReuseCrypto,
    *, now: datetime | None = None,
) -> EnrollmentResult:
    current_time = now or datetime.now(UTC)
    request_digest = crypto.scoped_digest("enrollment-request", request.agency_id, request.company_id,
        json.dumps(asdict(request), sort_keys=True, separators=(",", ":"), default=str))
    group = await session.scalar(select(ClientGroupModel).where(
        ClientGroupModel.id == request.group_id, ClientGroupModel.agency_id == request.agency_id,
        ClientGroupModel.company_id == request.company_id, ClientGroupModel.status != "deleted",
    ).with_for_update())
    if group is None or group.company_revision != request.expected_group_revision:
        raise EnrollmentError("group_revision_conflict")
    company = await session.scalar(select(ClientOrganizationModel).where(
        ClientOrganizationModel.id == request.company_id,
        ClientOrganizationModel.agency_id == request.agency_id,
        ClientOrganizationModel.status == "active",
    ).with_for_update())
    if company is None:
        raise EnrollmentError("company_unavailable")
    policy = await session.scalar(select(TravellerReusePolicyModel).where(
        TravellerReusePolicyModel.company_id == request.company_id,
        TravellerReusePolicyModel.agency_id == request.agency_id,
        TravellerReusePolicyModel.enabled.is_(True),
    ).with_for_update(read=True))
    if policy is None or policy.retention_mode != "until_withdrawn" or not request.permission_evidence_reference.strip():
        raise EnrollmentError("explicit_reuse_authority_required")
    previous = await session.scalar(select(TravellerDocumentRevisionModel).where(
        TravellerDocumentRevisionModel.agency_id == request.agency_id,
        TravellerDocumentRevisionModel.company_id == request.company_id,
        TravellerDocumentRevisionModel.idempotency_key == request.idempotency_key,
    ))
    if previous is not None:
        if not hmac.compare_digest(str(previous.source_provenance.get("request_digest", "")), request_digest):
            raise EnrollmentError("idempotency_conflict")
        pending = await session.scalar(select(func.count()).select_from(TravellerDocumentAssetModel).where(
            TravellerDocumentAssetModel.document_revision_id == previous.id,
            TravellerDocumentAssetModel.availability == "pending",
        ))
        return EnrollmentResult(previous.traveller_id, previous.passport_id, previous.id, int(pending or 0))
    source = await session.scalar(select(PassportSubmissionModel).where(
        PassportSubmissionModel.id == request.submission_id,
        PassportSubmissionModel.agency_id == request.agency_id,
        PassportSubmissionModel.group_id == request.group_id,
    ).with_for_update())
    if source is None or source.status not in TRUSTED_FIELD_STATUSES or source.extraction_revision != request.expected_extraction_revision:
        raise EnrollmentError("accepted_source_revision_required")
    request = await _resolve_reviewed_candidate(session, request, source, crypto)
    fields = dict(source.confirmed_fields or {})
    reviewed_context: dict[str, str] | None = None
    if request.reviewed_issuing_country is not None or request.reviewed_document_type is not None:
        if not request.reviewed_context_confirmed or not request.reviewed_issuing_country or not request.reviewed_document_type:
            raise EnrollmentError("reviewed_issuing_context_required")
        try:
            reviewed_issuer, reviewed_kind = issuing_context(request.reviewed_issuing_country, request.reviewed_document_type)
            import pycountry
            if pycountry.countries.get(alpha_3=reviewed_issuer) is None:
                raise ValueError("unknown_issuing_country")
        except ValueError as exc:
            raise EnrollmentError("reliable_issuing_context_required") from exc
        reviewed_context = {"issuing_country": reviewed_issuer, "document_type": reviewed_kind,
            "actor_user_id": str(request.actor_id), "confirmed_at": current_time.isoformat()}
        fields.update(issuing_country=reviewed_issuer, document_type=reviewed_kind)
    try:
        number = exact_passport_number(fields.get("passport_number", ""))
        issuer, kind = issuing_context(fields.get("issuing_country", ""), fields.get("document_type", ""))
    except ValueError as exc:
        raise EnrollmentError("reliable_issuing_context_required") from exc
    dates = _accepted_dates(fields)
    fingerprint = crypto.passport_fingerprint(request.agency_id, request.company_id, number, issuer, kind)
    passports = list((await session.scalars(select(TravellerPassportModel).where(
        TravellerPassportModel.agency_id == request.agency_id,
        TravellerPassportModel.company_id == request.company_id,
        TravellerPassportModel.fingerprint_key_version == crypto.key_version,
        TravellerPassportModel.number_fingerprint == fingerprint,
    ).limit(2))).all())
    if len(passports) > 1:
        raise EnrollmentError("ambiguous_passport_identity")
    passport = passports[0] if passports else None
    target_id = request.traveller_id or (passport.traveller_id if passport else None)
    if passport is not None and target_id != passport.traveller_id:
        raise EnrollmentError("conflicting_passport_owner")
    person = await _person(session, request, target_id, source, policy, crypto)
    config = await session.get(TravellerGroupReuseConfigModel, group.id)
    if config is not None and config.company_id == request.company_id and config.individual_identifier_type:
        value = (source.staff_metadata or {}).get(config.individual_identifier_type)
        if isinstance(value, str) and value.strip():
            code_fingerprint = crypto.scoped_digest("identifier", request.agency_id, request.company_id,
                config.individual_identifier_type, value.strip())
            existing_code = await session.scalar(select(TravellerIdentifierModel.id).where(
                TravellerIdentifierModel.traveller_id == person.id,
                TravellerIdentifierModel.identifier_type == config.individual_identifier_type,
                TravellerIdentifierModel.value_fingerprint == code_fingerprint,
                TravellerIdentifierModel.fingerprint_key_version == crypto.key_version,
            ).limit(1))
            if existing_code is None:
                session.add(TravellerIdentifierModel(agency_id=request.agency_id, company_id=request.company_id,
                    traveller_id=person.id, identifier_type=config.individual_identifier_type,
                    value_ciphertext=crypto.encrypt(value), value_fingerprint=code_fingerprint,
                    fingerprint_key_version=crypto.key_version, is_individual=True, effective_from=group.travel_date,
                    source_evidence={"submission_id": str(source.id), "staff_reviewed": True}))
    if passport is None:
        passport = TravellerPassportModel(agency_id=request.agency_id, company_id=request.company_id,
            traveller_id=person.id, issuing_country=issuer, document_type=kind,
            number_ciphertext=crypto.encrypt(number), number_fingerprint=fingerprint,
            fingerprint_key_version=crypto.key_version, status="candidate")
        session.add(passport)
        await session.flush()
    elif passport.status in {"lost", "cancelled", "compromised", "rejected", "disputed"}:
        raise EnrollmentError("unusable_document_cannot_be_reactivated")
    last_number = await session.scalar(select(func.max(TravellerDocumentRevisionModel.revision_number)).where(
        TravellerDocumentRevisionModel.passport_id == passport.id,
    ))
    revision = TravellerDocumentRevisionModel(agency_id=request.agency_id, company_id=request.company_id,
        traveller_id=person.id, passport_id=passport.id, revision_number=int(last_number or 0) + 1,
        status="accepted", fields_ciphertext=crypto.encrypt(json.dumps(fields, ensure_ascii=False)),
        source_submission_id=source.id, source_group_id=source.group_id,
        source_provenance={"submission_id": str(source.id), "group_id": str(source.group_id),
            "extraction_revision": source.extraction_revision, "change_kind": request.change_kind,
            "accepted_by_user_id": str(request.actor_id), "reviewed_issuing_context": reviewed_context,
            "request_digest": request_digest},
        reliable_fields={key: {"accepted": True, "source": "staff_review"} for key in dates},
        date_of_birth=dates.get("date_of_birth"), issue_date=dates.get("issue_date"), expiry_date=dates.get("expiry_date"),
        accepted_by_user_id=request.actor_id, accepted_at=current_time, idempotency_key=request.idempotency_key)
    session.add(revision)
    await session.flush()
    await _promote_default(session, person, passport, revision)
    pending = _stage_assets(session, request, source, revision, policy.purpose_version or "", current_time)
    await _historical_membership(session, group, source, person, passport, revision, current_time)
    await session.execute(update(TravellerMatchCaseModel).where(
        TravellerMatchCaseModel.agency_id == request.agency_id,
        TravellerMatchCaseModel.company_id == request.company_id,
        TravellerMatchCaseModel.group_id == request.group_id,
        TravellerMatchCaseModel.source_kind == "passport_submission",
        TravellerMatchCaseModel.source_row_key == str(source.id),
    ).values(status="resolved", reason_code="explicit_staff_enrollment", traveller_id=person.id,
             revision=TravellerMatchCaseModel.revision + 1, resolved_at=current_time))
    session.add(TravellerChangeEventModel(agency_id=request.agency_id, company_id=request.company_id,
        traveller_id=person.id, event_type="document_promoted", aggregate_id=passport.id,
        aggregate_revision=passport.revision, idempotency_key=f"enrollment:{revision.id}",
        reason_code=f"staff_accepted_{request.change_kind}"))
    await session.flush()
    return EnrollmentResult(person.id, passport.id, revision.id, pending)


async def _resolve_reviewed_candidate(
    session: AsyncSession, request: EnrollmentRequest, source: PassportSubmissionModel, crypto: TravellerReuseCrypto,
) -> EnrollmentRequest:
    case = await session.scalar(select(TravellerMatchCaseModel).where(
        TravellerMatchCaseModel.agency_id == request.agency_id,
        TravellerMatchCaseModel.company_id == request.company_id,
        TravellerMatchCaseModel.group_id == request.group_id,
        TravellerMatchCaseModel.source_kind == "passport_submission",
        TravellerMatchCaseModel.source_row_key == str(source.id),
        TravellerMatchCaseModel.reason_code == "authorized_replacement_candidate",
    ).with_for_update())
    if case is None:
        return request
    expected = case.evidence.get("profile_revision")
    kind = case.evidence.get("change_kind")
    if (not request.candidate_association_confirmed or case.status != "provisional" or case.traveller_id is None or not isinstance(expected, int)
            or kind not in {"renewal", "scan", "correction"}
            or case.evidence.get("group_revision") != request.expected_group_revision
            or case.evidence.get("fingerprint_key_version") != crypto.key_version
            or not hmac.compare_digest(str(case.evidence.get("source_evidence_digest", "")), source_evidence_digest(crypto, source))
            or (request.traveller_id is not None and request.traveller_id != case.traveller_id)
            or (request.expected_profile_revision is not None and request.expected_profile_revision != expected)
            or request.change_kind not in {"initial", kind}):
        raise EnrollmentError("replacement_association_changed")
    return replace(request, traveller_id=case.traveller_id, expected_profile_revision=expected, change_kind=kind)


def _accepted_dates(fields: dict[str, str]) -> dict[str, date]:
    values: dict[str, date] = {}
    for key, source_key in (("date_of_birth", "date_of_birth"), ("issue_date", "date_of_issue"), ("expiry_date", "date_of_expiry")):
        raw = fields.get(source_key) or fields.get(key)
        if raw:
            try:
                values[key] = parse_answer(normalize_passport_date(raw, field=source_key))
            except ValueError as exc:
                raise EnrollmentError("invalid_accepted_date") from exc
    if values.get("issue_date") and values.get("expiry_date") and values["expiry_date"] < values["issue_date"]:
        raise EnrollmentError("invalid_accepted_date")
    return values


async def _person(
    session: AsyncSession, request: EnrollmentRequest, target_id: uuid.UUID | None,
    source: PassportSubmissionModel, policy: TravellerReusePolicyModel, crypto: TravellerReuseCrypto,
) -> TravellerProfileModel:
    if target_id is not None:
        person = await session.scalar(select(TravellerProfileModel).where(
            TravellerProfileModel.id == target_id, TravellerProfileModel.agency_id == request.agency_id,
            TravellerProfileModel.company_id == request.company_id,
        ).with_for_update())
        if person is None or person.status != "active" or person.deleted_at is not None:
            raise EnrollmentError("traveller_unavailable")
        if request.expected_profile_revision is None or person.revision != request.expected_profile_revision:
            raise EnrollmentError("profile_revision_conflict")
        person.revision += 1
        person.authorization_version += 1
        return person
    if request.change_kind != "initial":
        raise EnrollmentError("reviewed_traveller_required")
    person = TravellerProfileModel(agency_id=request.agency_id, company_id=request.company_id,
        status="active", display_name_ciphertext=crypto.encrypt(source.client_name),
        name_fingerprint=crypto.scoped_digest("name", request.agency_id, request.company_id, source.client_name.strip().casefold()),
        fingerprint_key_version=crypto.key_version, reuse_permission_status="granted",
        reuse_permission_evidence={"reference": request.permission_evidence_reference,
            "purpose_version": policy.purpose_version, "notice_version": policy.notice_version,
            "processing_basis": policy.processing_basis, "actor_user_id": str(request.actor_id)})
    session.add(person)
    await session.flush()
    if source.client_phone:
        # Legacy phone retention is not historical OTP provenance.
        phone = normalize_phone_number(source.client_phone)
        if phone:
            session.add(TravellerContactBindingModel(agency_id=request.agency_id, company_id=request.company_id,
                traveller_id=person.id, kind="phone", value_ciphertext=crypto.encrypt(phone),
                value_fingerprint=crypto.scoped_digest("phone", request.agency_id, request.company_id, phone),
                fingerprint_key_version=crypto.key_version, status="current", verified_at=None,
                verification_evidence={"source": "legacy_unverified"}))
    return person


async def _promote_default(
    session: AsyncSession, person: TravellerProfileModel, passport: TravellerPassportModel,
    revision: TravellerDocumentRevisionModel,
) -> None:
    current = await session.scalar(select(TravellerPassportModel).where(
        TravellerPassportModel.traveller_id == person.id, TravellerPassportModel.is_default.is_(True),
    ).with_for_update())
    choose = current is None or current.id == passport.id
    if current is not None and current.id != passport.id:
        current_revision = await session.scalar(select(TravellerDocumentRevisionModel).where(
            TravellerDocumentRevisionModel.passport_id == current.id,
            TravellerDocumentRevisionModel.status == "accepted",
        ).order_by(TravellerDocumentRevisionModel.revision_number.desc()).limit(1))
        choose = (revision.issue_date is not None and current_revision is not None
                  and current_revision.issue_date is not None and revision.issue_date > current_revision.issue_date)
    if choose and current is not None and current.id != passport.id:
        current.is_default = False
        await session.flush()
    passport.status = "accepted"
    passport.is_default = choose
    passport.revision += 1


def _stage_assets(
    session: AsyncSession, request: EnrollmentRequest, source: PassportSubmissionModel,
    revision: TravellerDocumentRevisionModel, basis: str, now: datetime,
) -> int:
    count = 0
    for attribute, side in (("image_s3_key", "front"), ("passport_back_s3_key", "back"),
                            ("passport_cover_s3_key", "cover"), ("passport_back_cover_s3_key", "back_cover"),
                            ("passport_photo_s3_key", "photo")):
        key = getattr(source, attribute)
        if not key:
            continue
        asset_id = uuid.uuid4()
        session.add(TravellerDocumentAssetModel(id=asset_id, agency_id=request.agency_id, company_id=request.company_id,
            traveller_id=revision.traveller_id, passport_id=revision.passport_id, document_revision_id=revision.id,
            kind="original", document_side=side, source_object_key=key,
            source_extraction_revision=source.extraction_revision,
            object_key=f"travellers/{request.agency_id}/{request.company_id}/{revision.traveller_id}/{revision.id}/{asset_id}",
            content_type="application/octet-stream", byte_size=0, availability="pending", retention_basis=basis,
            next_attempt_at=now))
        count += 1
    return count


async def _historical_membership(
    session: AsyncSession, group: ClientGroupModel, source: PassportSubmissionModel,
    person: TravellerProfileModel, passport: TravellerPassportModel,
    revision: TravellerDocumentRevisionModel, now: datetime,
) -> None:
    existing = await session.scalar(select(TravellerParticipationModel).where(
        TravellerParticipationModel.group_id == group.id, TravellerParticipationModel.traveller_id == person.id,
    ).with_for_update())
    if existing is not None:
        # Freeze the versions already used by an accepted/completed trip.
        return
    session.add(TravellerParticipationModel(agency_id=group.agency_id, company_id=group.company_id,
        traveller_id=person.id, group_id=group.id, source_submission_id=source.id,
        source_kind="accepted_submission", source_row_key=str(source.id),
        passport_id=passport.id, document_revision_id=revision.id, profile_revision=person.revision,
        contact_revision=person.contact_revision, status="accepted", question_version="accepted_source_snapshot",
        answers={"custom_answers": source.custom_answers, "custom_detail_answers": source.custom_detail_answers},
        confirmations={"source_submission_id": str(source.id), "contact_at_submission": source.client_phone},
        idempotency_key=f"source:{source.id}", accepted_at=now, trip_started_at=group.travel_date))
