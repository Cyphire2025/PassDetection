"""Bounded current-person projections; documents are loaded only on explicit open.

The directory fetches at most K+1 people and aggregates only those IDs. It uses
constant query count, O(K) application space, and indexed tenant/person joins.
Encrypted full-name search uses the existing tenant HMAC index, never a scan.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import Select, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.access import visible_company_groups
from app.application.companies.original_record import latest_original_records
from app.application.companies.people_contracts import (
    CurrentDocument,
    CurrentPerson,
    DocumentAsset,
    DocumentVersion,
    PersonItem,
)
from app.application.travellers.document_selection import current_document_id
from app.application.travellers.history import PASSPORT_REVIEW_FIELDS
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.traveller_reuse_models import (
    TravellerContactBindingModel as Contact,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentAssetModel as Asset,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentRevisionModel as Document,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerMatchCaseModel as MatchCase,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerParticipationModel as Participation,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerPassportModel as Passport,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerProfileModel as Person,
)
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto


def person_scope(user: User, agency_id: uuid.UUID, company_id: uuid.UUID) -> Select[tuple[Person]]:
    groups = visible_company_groups(user, agency_id, company_id).subquery()
    membership = exists(select(Participation.id).join(groups, groups.c.id == Participation.group_id).where(
        Participation.agency_id == agency_id, Participation.company_id == company_id,
        Participation.traveller_id == Person.id,
    ))
    source = exists(select(MatchCase.id).join(groups, groups.c.id == MatchCase.group_id).where(
        MatchCase.agency_id == agency_id, MatchCase.company_id == company_id,
        MatchCase.traveller_id == Person.id, MatchCase.status == "resolved",
    ))
    return select(Person).where(Person.agency_id == agency_id, Person.company_id == company_id,
        Person.deleted_at.is_(None), Person.status != "deleted", membership | source)


async def require_person(session: AsyncSession, *, user: User, agency_id: uuid.UUID,
    company_id: uuid.UUID, person_id: uuid.UUID, lock: bool = False,
) -> Person:
    query = person_scope(user, agency_id, company_id).where(Person.id == person_id)
    if lock:
        query = query.with_for_update(of=Person).execution_options(populate_existing=True)
    row = await session.scalar(query)
    if row is None:
        raise EntityNotFoundError("Traveller", person_id)
    return row


def document_fields(crypto: TravellerReuseCrypto, document: Document) -> dict[str, str]:
    raw = json.loads(crypto.decrypt(document.fields_ciphertext))
    if not isinstance(raw, dict):
        raise ValueError("invalid_retained_fields")
    return {key: value for key, value in raw.items() if key in PASSPORT_REVIEW_FIELDS and isinstance(value, str)}


async def current_document(session: AsyncSession, person: Person) -> tuple[Passport, Document] | None:
    return (await session.execute(select(Passport, Document).join(Document,
        Document.id == current_document_id(Passport)).where(
        Passport.agency_id == person.agency_id, Passport.company_id == person.company_id,
        Passport.traveller_id == person.id, Passport.is_default.is_(True), Passport.status == "accepted",
    ).limit(1))).tuples().first()


async def current_person(session: AsyncSession, person: Person, crypto: TravellerReuseCrypto, *, user: User | None = None) -> CurrentPerson:
    selected = await current_document(session, person)
    contact = await session.scalar(select(Contact).where(Contact.agency_id == person.agency_id,
        Contact.company_id == person.company_id, Contact.traveller_id == person.id,
        Contact.kind == "phone", Contact.status == "current").limit(1))
    document = None
    if selected:
        passport, version = selected
        document = CurrentDocument(id=version.id, passport_id=passport.id, revision_number=version.revision_number,
            fields=document_fields(crypto, version), issuing_country=passport.issuing_country,
            document_type=passport.document_type)
    originals = await latest_original_records(session, user=user, agency_id=person.agency_id,
        company_id=person.company_id, person_ids=[person.id]) if selected is None and user is not None else {}
    return CurrentPerson(id=person.id, status=person.status, display_name=crypto.decrypt(person.display_name_ciphertext) if person.display_name_ciphertext else "Traveller",
        revision=person.revision, contact_revision=person.contact_revision,
        phone_number=crypto.decrypt(contact.value_ciphertext) if contact else None,
        phone_verified=bool(contact and contact.verified_at), current_document=document, original_record=originals.get(person.id))


async def directory_items(session: AsyncSession, rows: list[Person], user: User,
    crypto: TravellerReuseCrypto,
) -> list[PersonItem]:
    if not rows:
        return []
    agency, company, ids = rows[0].agency_id, rows[0].company_id, [row.id for row in rows]
    groups = visible_company_groups(user, agency, company).subquery()
    trips = dict((await session.execute(select(Participation.traveller_id, func.count()).join(
        groups, groups.c.id == Participation.group_id).where(Participation.agency_id == agency,
        Participation.company_id == company, Participation.traveller_id.in_(ids))
        .group_by(Participation.traveller_id))).tuples().all())
    versions = dict((await session.execute(select(Document.traveller_id, func.count()).where(
        Document.agency_id == agency, Document.company_id == company, Document.traveller_id.in_(ids))
        .group_by(Document.traveller_id))).tuples().all())
    possible = set((await session.scalars(select(MatchCase.traveller_id).where(
        MatchCase.agency_id == agency, MatchCase.company_id == company, MatchCase.traveller_id.in_(ids),
        (MatchCase.status.in_(("provisional", "ambiguous", "conflicting"))
         | MatchCase.evidence["possible_duplicate"].as_boolean().is_(True))).distinct())).all())
    passports = dict((await session.execute(select(Passport.traveller_id, Passport.number_ciphertext).where(
        Passport.agency_id == agency, Passport.company_id == company, Passport.traveller_id.in_(ids),
        Passport.is_default.is_(True), Passport.status == "accepted"))).tuples().all())
    return [PersonItem(id=row.id, display_name=crypto.decrypt(row.display_name_ciphertext) if row.display_name_ciphertext else "Traveller",
        status=row.status, revision=row.revision, trip_count=trips.get(row.id, 0),
        document_version_count=versions.get(row.id, 0), duplicate_status="possible" if row.id in possible else "none",
        current_passport_last4=crypto.decrypt(passports[row.id])[-4:] if row.id in passports else None) for row in rows]


async def document_items(session: AsyncSession, rows: list[Document], person: Person,
    crypto: TravellerReuseCrypto,
) -> list[DocumentVersion]:
    if not rows:
        return []
    assets = (await session.scalars(select(Asset).where(Asset.agency_id == person.agency_id,
        Asset.company_id == person.company_id, Asset.traveller_id == person.id,
        Asset.document_revision_id.in_([row.id for row in rows]), Asset.kind == "original")
        .order_by(Asset.id).limit(len(rows) * 16))).all()
    by_version: dict[uuid.UUID, list[DocumentAsset]] = defaultdict(list)
    for asset in assets:
        by_version[asset.document_revision_id].append(DocumentAsset(id=asset.id, side=asset.document_side,
            content_type=asset.content_type, byte_size=asset.byte_size, availability=asset.availability))
    selected = await current_document(session, person)
    return [DocumentVersion(id=row.id, passport_id=row.passport_id, revision_number=row.revision_number,
        status=row.status, created_at=row.created_at, change_kind=str(row.source_provenance.get("change_kind", "historical")),
        is_current=bool(selected and selected[1].id == row.id), fields=document_fields(crypto, row),
        assets=by_version[row.id]) for row in rows]


def seek_before(query: Select[tuple[Person]], after: tuple[datetime, uuid.UUID] | None) -> Select[tuple[Person]]:
    if after:
        query = query.where((Person.created_at < after[0]) | ((Person.created_at == after[0]) & (Person.id < after[1])))
    return query
