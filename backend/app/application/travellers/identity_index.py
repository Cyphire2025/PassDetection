"""Tenant-scoped exact candidate indexing, separate from disclosure authority.

One exact-name index seek returns at most 101 profiles. At most 100 * 16 current
signal rows are projected; common-name overflow is review-only. Application
memory is bounded. Query work is O(log N + C), C <= 101; no history scan occurs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.data_exports import invalidate_company_exports
from app.domain.services.traveller_identity import IdentityEvidence, compare_identity
from app.infrastructure.database.traveller_reuse_models import (
    TravellerIdentifierModel,
    TravellerProfileModel,
)
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto

IDENTITY_PREFIX = "identity_v1:"
COMPANY_INDIVIDUAL_CODE = "company_individual_code"
MAX_IDENTITY_CANDIDATES = 100
MAX_SIGNALS = 16


async def replace_phone_identity_evidence(session: AsyncSession, *, person: TravellerProfileModel,
    normalized_phone: str, crypto: TravellerReuseCrypto, source: dict[str, object],
) -> None:
    """Atomic verified contact change; preserve every unrelated identity signal."""
    model = TravellerIdentifierModel
    await session.execute(delete(model).where(model.agency_id == person.agency_id,
        model.company_id == person.company_id, model.traveller_id == person.id,
        model.identifier_type == IDENTITY_PREFIX + "phone"))
    session.add(model(agency_id=person.agency_id, company_id=person.company_id, traveller_id=person.id,
        identifier_type=IDENTITY_PREFIX + "phone", value_ciphertext=crypto.encrypt(normalized_phone),
        value_fingerprint=crypto.scoped_digest("identity_v1", person.agency_id, person.company_id, "phone", normalized_phone),
        fingerprint_key_version=crypto.key_version, is_individual=False, source_evidence=source))


async def replace_identity_evidence(session: AsyncSession, *, person: TravellerProfileModel,
    evidence: IdentityEvidence, crypto: TravellerReuseCrypto, source: dict[str, object],
) -> None:
    """Caller holds the profile lock and owns commit; never changes permission."""
    await invalidate_company_exports(session, person.agency_id, person.company_id)
    model = TravellerIdentifierModel
    await session.execute(delete(model).where(model.agency_id == person.agency_id,
        model.company_id == person.company_id, model.traveller_id == person.id,
        or_(model.identifier_type.startswith(IDENTITY_PREFIX), model.identifier_type == COMPANY_INDIVIDUAL_CODE)))
    names = evidence.get("name")
    person.name_fingerprint = (crypto.scoped_digest("name", person.agency_id, person.company_id,
        next(iter(names))) if len(names) == 1 else None)
    person.fingerprint_key_version = crypto.key_version
    if evidence.conflicts or len(evidence.values) > MAX_SIGNALS:
        return
    for kind, value in evidence.values:
        session.add(model(agency_id=person.agency_id, company_id=person.company_id, traveller_id=person.id,
            identifier_type=IDENTITY_PREFIX + kind, value_ciphertext=crypto.encrypt(value),
            value_fingerprint=crypto.scoped_digest("identity_v1", person.agency_id, person.company_id, kind, value),
            fingerprint_key_version=crypto.key_version, is_individual=False, source_evidence=source))
    for code in {value.partition(":")[2] for kind, value in evidence.values if kind == "code"}:
        if 1 <= len(code) <= 128:
            session.add(model(agency_id=person.agency_id, company_id=person.company_id, traveller_id=person.id,
                identifier_type=COMPANY_INDIVIDUAL_CODE, value_ciphertext=crypto.encrypt(code),
                value_fingerprint=crypto.scoped_digest("identifier", person.agency_id, person.company_id,
                    COMPANY_INDIVIDUAL_CODE, code), fingerprint_key_version=crypto.key_version,
                is_individual=True, source_evidence=source))
    await session.flush()


@dataclass(frozen=True, slots=True)
class IdentityMatch:
    status: str
    reason: str
    traveller_id: uuid.UUID | None = None
    matching_types: tuple[str, ...] = ()


async def find_exact_identity(session: AsyncSession, *, agency_id: uuid.UUID, company_id: uuid.UUID,
    evidence: IdentityEvidence, crypto: TravellerReuseCrypto,
) -> IdentityMatch:
    names = evidence.get("name")
    if evidence.conflicts or len(names) != 1:
        return IdentityMatch("conflicting" if evidence.conflicts else "unmatched", "exact_name_required")
    fingerprint = crypto.scoped_digest("name", agency_id, company_id, next(iter(names)))
    person, index = TravellerProfileModel, TravellerIdentifierModel
    ids = list((await session.scalars(select(person.id).where(person.agency_id == agency_id,
        person.company_id == company_id, person.fingerprint_key_version == crypto.key_version,
        person.name_fingerprint == fingerprint, person.status.in_(("active", "review_required")),
        person.deleted_at.is_(None)).order_by(person.id).limit(MAX_IDENTITY_CANDIDATES + 1))).all())
    if len(ids) > MAX_IDENTITY_CANDIDATES:
        return IdentityMatch("ambiguous", "candidate_limit_exceeded")
    if not ids:
        return IdentityMatch("unmatched", "no_exact_name_candidate")
    rows = (await session.execute(select(index.traveller_id, index.identifier_type, index.value_ciphertext)
        .where(index.agency_id == agency_id, index.company_id == company_id, index.traveller_id.in_(ids),
            index.fingerprint_key_version == crypto.key_version, index.identifier_type.startswith(IDENTITY_PREFIX))
        .limit(MAX_IDENTITY_CANDIDATES * MAX_SIGNALS + 1))).all()
    if len(rows) > MAX_IDENTITY_CANDIDATES * MAX_SIGNALS:
        return IdentityMatch("ambiguous", "candidate_evidence_limit_exceeded")
    candidates: dict[uuid.UUID, list[tuple[str, str]]] = {identifier: [] for identifier in ids}
    for identifier, kind, ciphertext in rows:
        candidates[identifier].append((kind.removeprefix(IDENTITY_PREFIX), crypto.decrypt(ciphertext)))
    matches: list[tuple[uuid.UUID, tuple[str, ...]]] = []
    conflict = False
    for identifier, values in candidates.items():
        saved = IdentityEvidence(tuple(values))
        if len(values) > MAX_SIGNALS or any(len(saved.get(kind)) > 1 for kind in ("name", "birth_date", "phone", "email")):
            conflict = True
            continue
        decision = compare_identity(evidence, saved)
        conflict |= decision.reason in {"passport_conflict", "birth_date_conflict"}
        if decision.matched:
            matches.append((identifier, decision.matching_types))
    if len(matches) > 1:
        return IdentityMatch("ambiguous", "multiple_three_type_matches")
    if matches:
        return IdentityMatch("matched", "exact_three_type_match", matches[0][0], matches[0][1])
    return IdentityMatch("conflicting" if conflict else "unmatched",
        "identity_conflict" if conflict else "three_independent_types_required")
