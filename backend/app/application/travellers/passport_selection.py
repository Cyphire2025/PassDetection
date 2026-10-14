"""Choose an accepted passport for one grant without changing future defaults."""

import uuid

from sqlalchemy import select

from app.application.travellers.authority import accepted_document
from app.application.travellers.claims import ReturningClaims
from app.application.travellers.document_selection import current_document_id
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.grants import require_grant
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentRevisionModel,
    TravellerPassportModel,
)


async def available_passports(service: ReturningClaims, *, agency_id: uuid.UUID, company_id: uuid.UUID,
                              traveller_id: uuid.UUID) -> list[dict[str, object]]:
    passport, revision = TravellerPassportModel, TravellerDocumentRevisionModel
    rows = (await service.session.execute(select(passport.id, passport.number_ciphertext,
        passport.issuing_country, passport.document_type, passport.is_default, revision.expiry_date)
        .join(revision, revision.id == current_document_id(passport)).where(passport.agency_id == agency_id,
            passport.company_id == company_id, passport.traveller_id == traveller_id, passport.status == "accepted")
        .order_by(passport.is_default.desc(), passport.id).limit(20))).all()
    return [{"id": row.id, "number": service.crypto.decrypt(row.number_ciphertext),
        "issuing_country": row.issuing_country, "document_type": row.document_type,
        "is_default": row.is_default, "expiry_date": row.expiry_date} for row in rows]


async def select_passport(service: ReturningClaims, token: str, passport_id: uuid.UUID, *, expected_group_token: str | None = None) -> None:
    grant, scope, person = await require_grant(service, token, "history:read")
    if expected_group_token is not None and scope.group.token != expected_group_token:
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    passport, _ = await accepted_document(service.session, agency_id=grant.agency_id,
        company_id=grant.company_id, traveller_id=person.id, passport_id=passport_id, crypto=service.crypto)
    if passport.status != "accepted":
        raise ReuseError(ReuseReason.UNAVAILABLE)
    grant.actor_evidence = {**grant.actor_evidence, "review_passport_id": str(passport.id)}
    await service.session.commit()
