"""Exact context plus an explicit unknown-context legacy lookup, bounded to two.

The alternate HMAC is written only by the server before proof. It conveys no
authority and is removed when the verified actor declaration creates a grant.
The owner veto visits C exact-number index matches: O(log N + C) database work,
at most one returned owner and O(1) application memory; no history scan.
"""

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.identity_index import IDENTITY_PREFIX
from app.application.travellers.retained_authority import retained_authority_predicate
from app.domain.services.traveller_verification import (
    UNKNOWN_ISSUING_COUNTRY,
    exact_passport_number,
    issuing_context,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerClaimModel,
    TravellerIdentifierModel,
    TravellerPassportModel,
    TravellerProfileModel,
)
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto

LEGACY_LOOKUP_KEY = "_legacy_passport_fingerprint"


def set_passport_identifiers(claim: TravellerClaimModel, crypto: TravellerReuseCrypto,
    number: str, issuer: str | None, document_type: str,
) -> None:
    if not issuer:
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    fingerprint = crypto.passport_fingerprint(claim.agency_id, claim.company_id, number, issuer, document_type)
    if claim.passport_id is not None and claim.supplied_passport_fingerprint != fingerprint:
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    _, kind = issuing_context(issuer, document_type)
    alternate = crypto.passport_fingerprint(claim.agency_id, claim.company_id, number,
        UNKNOWN_ISSUING_COUNTRY, "P") if kind in {"P", "PASSPORT"} else None
    claim.supplied_passport_fingerprint = fingerprint
    evidence = dict(claim.actor_evidence or {})
    evidence.pop(LEGACY_LOOKUP_KEY, None)
    if alternate is not None:
        evidence[LEGACY_LOOKUP_KEY] = alternate
    claim.actor_evidence = evidence


def passport_lookup_fingerprints(claim: TravellerClaimModel) -> tuple[str, ...]:
    result = [claim.supplied_passport_fingerprint] if claim.supplied_passport_fingerprint else []
    alternate = (claim.actor_evidence or {}).get(LEGACY_LOOKUP_KEY)
    if isinstance(alternate, str) and len(alternate) == 64 and alternate not in result:
        result.append(alternate)
    return tuple(result)


async def require_unambiguous_legacy_owner(session: AsyncSession, claim: TravellerClaimModel,
    passport: TravellerPassportModel, crypto: TravellerReuseCrypto, now: datetime,
) -> None:
    """Indexed owner veto across issuer contexts; no disclosure or merge."""
    if passport.issuing_country != UNKNOWN_ISSUING_COUNTRY:
        return
    number = exact_passport_number(crypto.decrypt(passport.number_ciphertext))
    fingerprint = crypto.scoped_digest("identity_v1", claim.agency_id, claim.company_id, "passport", number)
    index, person = TravellerIdentifierModel, TravellerProfileModel
    other_owner = await session.scalar(select(index.traveller_id).join(person,
        (person.id == index.traveller_id) & (person.agency_id == index.agency_id)
        & (person.company_id == index.company_id)).where(
        index.agency_id == claim.agency_id, index.company_id == claim.company_id,
        index.identifier_type == IDENTITY_PREFIX + "passport", index.fingerprint_key_version == crypto.key_version,
        index.value_fingerprint == fingerprint, index.traveller_id != passport.traveller_id,
        retained_authority_predicate(), or_(person.retention_until.is_(None), person.retention_until > now),
    ).limit(1))
    if other_owner is not None:
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
