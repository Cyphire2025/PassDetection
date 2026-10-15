"""Reviewed current-record edits never rewrite historical submissions or trips."""

from __future__ import annotations

import hmac
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.people import current_document, document_fields
from app.application.companies.people_contracts import PersonEdit
from app.application.travellers.identity_index import IDENTITY_PREFIX, replace_identity_evidence
from app.application.travellers.versioning import accepted_dates, promote_default
from app.domain.exceptions.exceptions import ConflictError, ValidationError
from app.domain.services.traveller_identity import IdentityEvidence, identity_evidence
from app.domain.services.traveller_verification import exact_passport_number, issuing_context
from app.domain.value_objects.passport_fields import normalize_reviewed_passport_fields
from app.domain.value_objects.phone_number import normalize_phone_number
from app.infrastructure.database.traveller_reuse_models import (
    TravellerChangeEventModel as Event,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerClaimModel as Claim,
)
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
    TravellerHistoryGrantModel as Grant,
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
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto


async def edit_current_record(session: AsyncSession, *, person: Person, body: PersonEdit,
    actor_id: uuid.UUID, crypto: TravellerReuseCrypto,
) -> None:
    """Caller holds person lock. Fixed queries and <=16 assets/signals per edit."""
    digest = crypto.scoped_digest("staff-record-edit", person.agency_id, person.company_id,
        str(person.id), str(actor_id), body.model_dump_json(exclude={"idempotency_key"}))
    key = crypto.scoped_digest("staff-record-idempotency", person.agency_id, person.company_id,
        str(person.id), str(actor_id), body.idempotency_key)
    previous = await session.scalar(select(Event).where(Event.agency_id == person.agency_id,
        Event.company_id == person.company_id, Event.idempotency_key == key).limit(1))
    if previous:
        if not hmac.compare_digest(previous.reason_code, digest):
            raise ConflictError("The saved request differs. Use a new request key.")
        return
    if person.revision != body.expected_revision:
        raise ConflictError("The current record changed. Reopen it before saving.")
    if person.status == "blocked":
        raise ConflictError("Review the blocked identity before editing its current record.")
    selected = await current_document(session, person)
    fields = document_fields(crypto, selected[1]) if selected else {}
    if body.fields is not None:
        if selected is None:
            raise ValidationError("Upload a reviewed document before editing its passport fields.")
        fields.update(normalize_reviewed_passport_fields(body.fields))
        await append_correction(session, person=person, passport=selected[0], prior=selected[1],
            fields=fields, actor_id=actor_id, key=key, crypto=crypto)
    now = datetime.now(UTC)
    contact = await session.scalar(select(Contact).where(Contact.agency_id == person.agency_id,
        Contact.company_id == person.company_id, Contact.traveller_id == person.id,
        Contact.kind == "phone", Contact.status == "current").with_for_update())
    phone = crypto.decrypt(contact.value_ciphertext) if contact else None
    if "phone_number" in body.model_fields_set:
        changed_phone = normalize_phone_number(body.phone_number) if body.phone_number else None
        if body.phone_number and changed_phone is None:
            raise ValidationError("Enter a valid phone number.", field="phone_number")
        if changed_phone != phone:
            if contact:
                contact.status = "historical"
                await session.flush()
            person.contact_revision += 1
            if changed_phone:
                session.add(Contact(agency_id=person.agency_id, company_id=person.company_id, traveller_id=person.id,
                    kind="phone", status="current", revision=person.contact_revision,
                    value_ciphertext=crypto.encrypt(changed_phone),
                    value_fingerprint=crypto.scoped_digest("phone", person.agency_id, person.company_id, changed_phone),
                    fingerprint_key_version=crypto.key_version, verified_at=None,
                    verification_evidence={"method": "staff_unverified", "actor_user_id": str(actor_id)}))
            phone = changed_phone
    await refresh_current_identity(session, person, fields, body.display_name, phone, actor_id, crypto)
    person.display_name_ciphertext = crypto.encrypt(body.display_name)
    person.revision += 1
    person.authorization_version += 1
    await revoke_person_access(session, person, now)
    session.add(Event(agency_id=person.agency_id, company_id=person.company_id, traveller_id=person.id,
        event_type="changed", aggregate_id=person.id, aggregate_revision=person.revision,
        idempotency_key=key, reason_code=digest))
    await AuditLogRepository(session).record(action="traveller.staff_current_record_edited", entity_type="traveller_profile",
        entity_id=str(person.id), agency_id=person.agency_id, user_id=actor_id,
        metadata={"previous_revision": body.expected_revision, "revision": person.revision,
            "reason": body.reason, "passport_fields_changed": body.fields is not None})
    await session.flush()


async def revoke_person_access(session: AsyncSession, person: Person, now: datetime) -> None:
    await session.execute(update(Grant).where(Grant.agency_id == person.agency_id,
        Grant.company_id == person.company_id, Grant.traveller_id == person.id,
        Grant.revoked_at.is_(None)).values(revoked_at=now))
    await session.execute(update(Claim).where(Claim.agency_id == person.agency_id,
        Claim.company_id == person.company_id, Claim.traveller_id == person.id,
        Claim.revoked_at.is_(None)).values(revoked_at=now, status="revoked"))


async def refresh_current_identity(session: AsyncSession, person: Person, fields: dict[str, str],
    name: str, phone: str | None, actor_id: uuid.UUID, crypto: TravellerReuseCrypto,
) -> None:
    # Preserve independent existing codes/email when this editor has no controls
    # for them. Replacing name/contact/document evidence must not erase those.
    rows = (await session.execute(select(Identifier.identifier_type, Identifier.value_ciphertext).where(
        Identifier.agency_id == person.agency_id, Identifier.company_id == person.company_id,
        Identifier.traveller_id == person.id, Identifier.identifier_type.in_((IDENTITY_PREFIX + "code", IDENTITY_PREFIX + "email")))
        .limit(17))).all()
    if len(rows) > 16:
        raise ConflictError("The identity evidence needs review before editing.")
    evidence = identity_evidence(fields, name=name, phone=phone)
    preserved = tuple((kind.removeprefix(IDENTITY_PREFIX), crypto.decrypt(value)) for kind, value in rows)
    await replace_identity_evidence(session, person=person,
        evidence=IdentityEvidence(tuple(sorted(set((*evidence.values, *preserved)))), evidence.conflicts), crypto=crypto,
        source={"method": "staff_current_record", "actor_user_id": str(actor_id)})


async def append_correction(session: AsyncSession, *, person: Person, passport: Passport, prior: Document,
    fields: dict[str, str], actor_id: uuid.UUID, key: str, crypto: TravellerReuseCrypto,
    publish: bool = True,
) -> Document:
    number = exact_passport_number(fields.get("passport_number", ""))
    issuer, kind = issuing_context(fields.get("issuing_country", passport.issuing_country), passport.document_type)
    if crypto.passport_fingerprint(person.agency_id, person.company_id, number, issuer, kind) != passport.number_fingerprint:
        raise ConflictError("A changed passport identity requires uploading a reviewed replacement document.")
    dates = accepted_dates(fields)
    maximum = await session.scalar(select(func.max(Document.revision_number)).where(Document.passport_id == passport.id))
    revision = Document(agency_id=person.agency_id, company_id=person.company_id, traveller_id=person.id,
        passport_id=passport.id, revision_number=int(maximum or 0) + 1, status="accepted" if publish else "candidate",
        fields_ciphertext=crypto.encrypt(json.dumps(fields, ensure_ascii=False)),
        source_provenance={"change_kind": "correction", "staff_record_edit": True,
            "copy_parent_revision_id": str(prior.id), "actor_user_id": str(actor_id)},
        reliable_fields={key: {"accepted": True, "source": "staff_review"} for key in dates},
        date_of_birth=dates.get("date_of_birth"), issue_date=dates.get("issue_date"), expiry_date=dates.get("expiry_date"),
        accepted_by_user_id=actor_id, accepted_at=datetime.now(UTC) if publish else None, idempotency_key=key)
    session.add(revision)
    await session.flush()
    assets = (await session.scalars(select(Asset).where(Asset.agency_id == person.agency_id,
        Asset.company_id == person.company_id, Asset.traveller_id == person.id, Asset.document_revision_id == prior.id,
        Asset.kind == "original", Asset.availability == "available", Asset.purged_at.is_(None)).limit(17))).all()
    if len(assets) > 16:
        raise ConflictError("Document assets need review before editing.")
    for asset in assets:
        identifier = uuid.uuid4()
        session.add(Asset(id=identifier, agency_id=person.agency_id, company_id=person.company_id,
            traveller_id=person.id, passport_id=passport.id, document_revision_id=revision.id,
            kind="original", document_side=asset.document_side, source_object_key=asset.object_key,
            object_key=f"travellers/{person.agency_id}/{person.company_id}/{person.id}/{revision.id}/{identifier}",
            content_type=asset.content_type, byte_size=asset.byte_size, availability="pending",
            retention_basis=asset.retention_basis, retention_until=asset.retention_until, next_attempt_at=datetime.now(UTC)))
    if publish:
        await promote_default(session, person, passport, revision)
        session.add(Event(agency_id=person.agency_id, company_id=person.company_id, traveller_id=person.id,
            event_type="document_promoted", aggregate_id=passport.id, aggregate_revision=passport.revision,
            idempotency_key=f"staff-document:{revision.id}", reason_code="staff_current_correction"))
    return revision
