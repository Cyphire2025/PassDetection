"""Bounded exact matching after contact proof; never authorizes disclosure.

Index seeks are O(log n + k), with k capped at 21 for phone candidates and two
for strong identifiers. There is no fuzzy automatic merge or phone-unique key.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.travellers.authority import ReuseScope, accepted_document, eligible_person
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.passport_lookup import (
    passport_lookup_fingerprints,
    require_unambiguous_legacy_owner,
)
from app.application.travellers.retained_authority import retained_authority_predicate
from app.domain.services.traveller_verification import MAX_PHONE_CANDIDATES
from app.infrastructure.database.traveller_reuse_models import (
    TravellerCandidateHandleModel,
    TravellerClaimModel,
    TravellerContactBindingModel,
    TravellerIdentifierModel,
    TravellerParticipationModel,
    TravellerPassportModel,
    TravellerProfileModel,
)
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto


@dataclass(frozen=True, slots=True)
class MaskedCandidate:
    handle: str
    label: str
    passport_hint: str


async def phone_candidates(
    session: AsyncSession, scope: ReuseScope, claim: TravellerClaimModel,
    crypto: TravellerReuseCrypto, now: datetime,
) -> tuple[tuple[MaskedCandidate, ...], bool]:
    if claim.otp_verified_at is None or not claim.phone_fingerprint:
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    membership = exists(select(TravellerParticipationModel.id).where(
        TravellerParticipationModel.traveller_id == TravellerProfileModel.id,
        TravellerParticipationModel.group_id == claim.group_id,
        TravellerParticipationModel.company_id == claim.company_id,
        TravellerParticipationModel.agency_id == claim.agency_id,
        TravellerParticipationModel.status != "withdrawn",
    ))
    phone = exists(select(TravellerContactBindingModel.id).where(
        TravellerContactBindingModel.traveller_id == TravellerProfileModel.id,
        TravellerContactBindingModel.agency_id == claim.agency_id,
        TravellerContactBindingModel.company_id == claim.company_id,
        TravellerContactBindingModel.kind == "phone",
        TravellerContactBindingModel.value_fingerprint == claim.phone_fingerprint,
        TravellerContactBindingModel.fingerprint_key_version == crypto.key_version,
        TravellerContactBindingModel.status == "current",
    ))
    statement = select(TravellerProfileModel.id, TravellerProfileModel.display_name_ciphertext,
        TravellerPassportModel.number_ciphertext).outerjoin(TravellerPassportModel,
            (TravellerPassportModel.traveller_id == TravellerProfileModel.id)
            & (TravellerPassportModel.agency_id == claim.agency_id)
            & (TravellerPassportModel.company_id == claim.company_id)
            & TravellerPassportModel.is_default.is_(True)
            & (TravellerPassportModel.status == "accepted")
        ).where(
        TravellerProfileModel.agency_id == claim.agency_id,
        TravellerProfileModel.company_id == claim.company_id,
        retained_authority_predicate(),
        or_(TravellerProfileModel.retention_until.is_(None), TravellerProfileModel.retention_until > now),
        phone,
    )
    if scope.config.roster_mode == "closed":
        statement = statement.where(membership)
    people = (await session.execute(statement.order_by(TravellerProfileModel.id).limit(MAX_PHONE_CANDIDATES + 1))).all()
    if len(people) > MAX_PHONE_CANDIDATES:
        return (), True
    # User-authorized limited disclosure: surname and last two passport symbols.
    # Collisions fall back to neutral labels; never expose additional attributes.
    existing = set((await session.scalars(select(TravellerCandidateHandleModel.traveller_id).where(
        TravellerCandidateHandleModel.claim_id == claim.id,
        TravellerCandidateHandleModel.agency_id == claim.agency_id,
        TravellerCandidateHandleModel.company_id == claim.company_id,
    ).limit(MAX_PHONE_CANDIDATES))).all())
    result: list[MaskedCandidate] = []
    masked: list[tuple[str, str]] = []
    for _, name_ciphertext, number_ciphertext in people:
        name = crypto.decrypt(name_ciphertext).split() if name_ciphertext else []
        number = crypto.decrypt(number_ciphertext) if number_ciphertext else ""
        masked.append((f"******** {name[-1]}" if name else "Traveller", f"********{number[-2:]}" if number else ""))
    for index, (traveller_id, _, _) in enumerate(people):
        handle = crypto.digest("candidate-handle", claim.secret_hash, str(traveller_id))
        if traveller_id not in existing:
            session.add(TravellerCandidateHandleModel(
                id=uuid.uuid4(), agency_id=claim.agency_id, company_id=claim.company_id,
                claim_id=claim.id, traveller_id=traveller_id,
                token_hash=crypto.digest("candidate", handle), expires_at=claim.expires_at,
            ))
        label, hint = masked[index]
        if masked.count((label, hint)) > 1:
            label, hint = f"Traveller {index + 1}", ""
        result.append(MaskedCandidate(handle, label, hint))
    return tuple(result), False


async def select_candidate(
    session: AsyncSession, scope: ReuseScope, claim: TravellerClaimModel,
    crypto: TravellerReuseCrypto, handle: str, now: datetime,
) -> None:
    if claim.otp_verified_at is None or claim.passport_id is not None:
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    candidate = await session.scalar(select(TravellerCandidateHandleModel).where(
        TravellerCandidateHandleModel.token_hash == crypto.digest("candidate", handle),
        TravellerCandidateHandleModel.claim_id == claim.id,
        TravellerCandidateHandleModel.agency_id == claim.agency_id,
        TravellerCandidateHandleModel.company_id == claim.company_id,
        TravellerCandidateHandleModel.expires_at > now,
    ))
    if candidate is None:
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    await eligible_person(session, scope, candidate.traveller_id, now)
    claim.traveller_id = candidate.traveller_id


async def resolve_passport(
    session: AsyncSession, scope: ReuseScope, claim: TravellerClaimModel,
    crypto: TravellerReuseCrypto, now: datetime,
) -> None:
    if (claim.method == "phone" and claim.otp_verified_at is None) or not claim.supplied_passport_fingerprint:
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    passports = list((await session.scalars(select(TravellerPassportModel).where(
        TravellerPassportModel.agency_id == claim.agency_id,
        TravellerPassportModel.company_id == claim.company_id,
        TravellerPassportModel.number_fingerprint.in_(passport_lookup_fingerprints(claim)),
        TravellerPassportModel.fingerprint_key_version == crypto.key_version,
        TravellerPassportModel.status.in_(("accepted", "superseded")),
    ).limit(2))).all())
    if len(passports) != 1:
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    passport = passports[0]
    await require_unambiguous_legacy_owner(session, claim, passport, crypto, now)
    if claim.traveller_id is not None and claim.traveller_id != passport.traveller_id:
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    person = await eligible_person(session, scope, passport.traveller_id, now)
    # Bind a uniquely eligible person before checking another strong identifier
    # so a wrong employee code cannot reset the person budget by restarting.
    claim.traveller_id = person.id
    if claim.method == "code" or scope.config.identifier_required:
        await _require_individual_code(session, scope, claim, crypto, person.id)
    _, revision = await accepted_document(session, agency_id=claim.agency_id,
        company_id=claim.company_id, traveller_id=person.id, passport_id=passport.id)
    established = await session.scalar(select(TravellerContactBindingModel.id).where(
        TravellerContactBindingModel.agency_id == claim.agency_id,
        TravellerContactBindingModel.company_id == claim.company_id,
        TravellerContactBindingModel.traveller_id == person.id,
        TravellerContactBindingModel.kind == "phone",
        TravellerContactBindingModel.status == "current",
        TravellerContactBindingModel.value_fingerprint == claim.phone_fingerprint,
        TravellerContactBindingModel.fingerprint_key_version == crypto.key_version,
        TravellerContactBindingModel.verified_at.is_not(None),
        TravellerContactBindingModel.verification_evidence["method"].as_string() == "whatsapp_otp",
    ).limit(1))
    claim.traveller_id, claim.passport_id = person.id, passport.id
    claim.document_revision_id = revision.id
    claim.expected_profile_revision = person.revision
    claim.expected_contact_revision = person.contact_revision
    claim.expected_authorization_version = person.authorization_version
    claim.required_question_count = (
        (0 if established else 2) if claim.method == "phone" else (1 if claim.method == "passport" else 0)
    )
    claim.status = "passport_matched"


async def _require_individual_code(
    session: AsyncSession, scope: ReuseScope, claim: TravellerClaimModel,
    crypto: TravellerReuseCrypto, traveller_id: uuid.UUID,
) -> None:
    if not claim.identifier_fingerprint or not scope.config.individual_identifier_type or scope.group.travel_date is None:
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    trip_date = scope.group.travel_date
    ids = list((await session.scalars(select(TravellerIdentifierModel.traveller_id).where(
        TravellerIdentifierModel.agency_id == claim.agency_id,
        TravellerIdentifierModel.company_id == claim.company_id,
        TravellerIdentifierModel.identifier_type == scope.config.individual_identifier_type,
        TravellerIdentifierModel.value_fingerprint == claim.identifier_fingerprint,
        TravellerIdentifierModel.fingerprint_key_version == crypto.key_version,
        TravellerIdentifierModel.is_individual.is_(True),
        or_(TravellerIdentifierModel.effective_from.is_(None), TravellerIdentifierModel.effective_from <= trip_date),
        or_(TravellerIdentifierModel.effective_until.is_(None), TravellerIdentifierModel.effective_until >= trip_date),
    ).distinct().limit(2))).all())
    if ids != [traveller_id]:
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
