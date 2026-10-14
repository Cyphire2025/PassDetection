"""Two indexed candidate seeks, never a passport-source or historical scan.

Each branch reads at most 101 IDs. The union returns at most 101 distinct IDs;
overflow remains ambiguous. O(log N + C) indexed work and O(C) memory, C <= 202.
"""

import uuid

from sqlalchemy import select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.services.traveller_identity import IdentityEvidence
from app.infrastructure.database.traveller_reuse_models import (
    TravellerIdentifierModel as Identifier,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerProfileModel as Person,
)
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto


async def identity_candidate_ids(session: AsyncSession, *, agency_id: uuid.UUID,
    company_id: uuid.UUID, evidence: IdentityEvidence, crypto: TravellerReuseCrypto, limit: int,
) -> list[uuid.UUID]:
    scope = (Person.agency_id == agency_id, Person.company_id == company_id,
        Person.status.in_(("active", "review_required")), Person.deleted_at.is_(None))
    name = crypto.scoped_digest("name", agency_id, company_id, next(iter(evidence.get("name"))))
    named = select(Person.id).where(*scope, Person.fingerprint_key_version == crypto.key_version,
        Person.name_fingerprint == name).order_by(Person.id).limit(limit).subquery()
    passports = evidence.get("passport")
    if len(passports) != 1:
        return list(await session.scalars(select(named.c.id)))
    fingerprint = crypto.scoped_digest("identity_v1", agency_id, company_id, "passport", next(iter(passports)))
    passport = select(Person.id).join(Identifier, (Identifier.traveller_id == Person.id)
        & (Identifier.agency_id == Person.agency_id) & (Identifier.company_id == Person.company_id)).where(
        *scope, Identifier.agency_id == agency_id, Identifier.company_id == company_id,
        Identifier.identifier_type == "identity_v1:passport", Identifier.fingerprint_key_version == crypto.key_version,
        Identifier.value_fingerprint == fingerprint).distinct().order_by(Person.id).limit(limit).subquery()
    combined = union(select(named.c.id), select(passport.c.id)).subquery()
    return list(await session.scalars(select(combined.c.id).order_by(combined.c.id).limit(limit)))
