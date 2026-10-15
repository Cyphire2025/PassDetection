"""Canonical current names without editing snapshots or merging profiles.

Caller-held company/profile locks protect a bounded current-document lookup and
at most 16 identity rows. Replays create no documents and never change status.
"""

import json

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.data_exports import invalidate_company_exports
from app.application.travellers.accepted_source import accept_source, retained_source_is_current
from app.application.travellers.authority import accepted_document
from app.application.travellers.errors import ReuseError
from app.application.travellers.identity_index import replace_identity_evidence
from app.application.travellers.versioning import EnrollmentError
from app.domain.services.traveller_identity import (
    IdentityEvidence,
    identity_evidence,
    normalize_name,
)
from app.domain.services.traveller_names import passport_holder_name
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerContactBindingModel as Contact,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerIdentifierModel as Identifier,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerPassportModel as Passport,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerProfileModel as Person,
)
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto


def canonical_source_name(source: PassportSubmissionModel) -> str | None:
    try:
        fields = accept_source(source, dict(source.confirmed_fields or {}), operator=True).fields
    except EnrollmentError:
        return None
    return passport_holder_name(fields)


def historical_source_evidence(source: PassportSubmissionModel) -> IdentityEvidence:
    fields = {**(source.extracted_fields or {}), **(source.confirmed_fields or {}), **(source.staff_metadata or {})}
    return identity_evidence(fields, name=source.client_name, phone=source.client_phone,
        email=source.client_email, authoritative_name=canonical_source_name(source))


async def refresh_registered_identity(session: AsyncSession, person: Person, crypto: TravellerReuseCrypto) -> None:
    """Reindex the established profile from its current accepted source proof."""
    passport_id = await session.scalar(select(Passport.id).where(Passport.agency_id == person.agency_id,
        Passport.company_id == person.company_id, Passport.traveller_id == person.id,
        Passport.is_default.is_(True), Passport.status == "accepted").limit(1))
    if passport_id is None or person.status != "active":
        return
    try:
        _, revision = await accepted_document(session, agency_id=person.agency_id,
            company_id=person.company_id, traveller_id=person.id, passport_id=passport_id, crypto=crypto)
    except ReuseError:
        return
    source = await session.scalar(select(PassportSubmissionModel).join(ClientGroupModel,
        (ClientGroupModel.id == PassportSubmissionModel.group_id)
        & (ClientGroupModel.agency_id == PassportSubmissionModel.agency_id)).where(
        PassportSubmissionModel.id == revision.source_submission_id, PassportSubmissionModel.agency_id == person.agency_id,
        ClientGroupModel.company_id == person.company_id, ClientGroupModel.deleted_at.is_(None))
        .execution_options(populate_existing=True))
    if (source is None or source.extraction_revision != revision.source_provenance.get("extraction_revision")
            or not retained_source_is_current(revision, source, crypto)):
        return
    fields = json.loads(crypto.decrypt(revision.fields_ciphertext))
    name = passport_holder_name(fields)
    if name is None:
        return
    existing = await session.scalar(select(Identifier).where(Identifier.agency_id == person.agency_id,
        Identifier.company_id == person.company_id, Identifier.traveller_id == person.id,
        Identifier.identifier_type == "identity_v1:name").limit(1))
    if existing is None:
        contacts = (await session.execute(select(Contact.kind, Contact.value_ciphertext).where(
            Contact.agency_id == person.agency_id, Contact.company_id == person.company_id,
            Contact.traveller_id == person.id, Contact.status == "current").limit(3))).all()
        values = {**fields, **(source.staff_metadata or {}), **{kind: crypto.decrypt(value) for kind, value in contacts}}
        evidence = identity_evidence(values, authoritative_name=name)
        if evidence.conflicts:
            return
        await replace_identity_evidence(session, person=person,
            evidence=evidence, crypto=crypto,
            source={"document_revision_id": str(revision.id), "canonical_name_version": 1})
    fingerprint = crypto.scoped_digest("name", person.agency_id, person.company_id, normalize_name(name))
    if (person.name_fingerprint == fingerprint and person.fingerprint_key_version == crypto.key_version
            and person.display_name_ciphertext and crypto.decrypt(person.display_name_ciphertext) == name
            and (existing is None or existing.value_fingerprint == crypto.scoped_digest("identity_v1",
                person.agency_id, person.company_id, "name", normalize_name(name)))):
        return
    await invalidate_company_exports(session, person.agency_id, person.company_id)
    await session.execute(delete(Identifier).where(Identifier.agency_id == person.agency_id,
        Identifier.company_id == person.company_id, Identifier.traveller_id == person.id,
        Identifier.identifier_type == "identity_v1:name"))
    normalized = normalize_name(name)
    session.add(Identifier(agency_id=person.agency_id, company_id=person.company_id, traveller_id=person.id,
        identifier_type="identity_v1:name", value_ciphertext=crypto.encrypt(normalized),
        value_fingerprint=crypto.scoped_digest("identity_v1", person.agency_id, person.company_id, "name", normalized),
        fingerprint_key_version=crypto.key_version, is_individual=False,
        source_evidence={"document_revision_id": str(revision.id), "canonical_name_version": 1}))
    person.name_fingerprint, person.fingerprint_key_version = fingerprint, crypto.key_version
    person.display_name_ciphertext = crypto.encrypt(name)
    person.revision += 1
    person.authorization_version += 1
    await session.flush()
