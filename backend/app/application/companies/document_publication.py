"""Publish a successfully owned upload without replacing a newer staff edit."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.current_record import refresh_current_identity, revoke_person_access
from app.application.companies.people import document_fields
from app.application.travellers.retained_authority import (
    OPERATOR_STAFF_RECORD_VERSION,
    has_retained_authority,
)
from app.application.travellers.versioning import promote_default
from app.domain.exceptions.exceptions import ConflictError
from app.infrastructure.database.traveller_reuse_models import (
    TravellerChangeEventModel as Event,
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
    TravellerPassportModel as Passport,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerProfileModel as Person,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto


async def publish_document_upload(session: AsyncSession, *, person: Person,
    asset_id: uuid.UUID, actor_id: uuid.UUID, crypto: TravellerReuseCrypto,
) -> None:
    """Caller holds person lock and confirmed the owned provider write completed."""
    if person.deleted_at is not None or person.status != "active" or person.reuse_permission_status == "withdrawn":
        raise ConflictError("The retained document authority changed during upload.")
    row = (await session.execute(select(Asset, Document, Passport).join(Document,
        Document.id == Asset.document_revision_id).join(Passport, Passport.id == Document.passport_id).where(
        Asset.id == asset_id, Asset.agency_id == person.agency_id, Asset.company_id == person.company_id,
        Asset.traveller_id == person.id, Document.agency_id == person.agency_id,
        Document.company_id == person.company_id, Document.traveller_id == person.id,
        Passport.agency_id == person.agency_id, Passport.company_id == person.company_id,
        Passport.traveller_id == person.id).with_for_update(of=[Asset.id, Document.id, Passport.id]))).first()
    if row is None:
        raise ConflictError("The upload receipt is no longer available.")
    asset, revision, passport = row
    provenance = revision.source_provenance
    if asset.purged_at is not None or provenance.get("actor_user_id") != str(actor_id):
        raise ConflictError("The upload receipt is no longer available.")
    if revision.status == "accepted" and asset.availability == "available":
        return
    if revision.status != "candidate" or provenance.get("expected_profile_revision") != person.revision:
        raise ConflictError("The record changed during upload. Reopen it before adding this version.")
    if passport.status not in {"candidate", "accepted", "superseded"}:
        raise ConflictError("The passport authority changed during upload.")
    if not has_retained_authority(person):
        person.reuse_permission_evidence = {"authority_kind": OPERATOR_STAFF_RECORD_VERSION,
            "actor_user_id": str(actor_id), "reason": str(provenance["review_reason"]),
            "source": "staff_reviewed_document_upload"}
    now = datetime.now(UTC)
    asset.availability, asset.source_object_key, asset.lease_expires_at = "available", None, None
    revision.status, revision.accepted_at = "accepted", now
    await promote_default(session, person, passport, revision, make_default=provenance.get("change_kind") == "renewal")
    # The ordinary copier can now copy inherited sides independently. While
    # candidate, it could only mark them unreadable; never publish their bytes.
    await session.execute(update(Asset).where(Asset.document_revision_id == revision.id,
        Asset.id != asset.id, Asset.source_object_key.is_not(None), Asset.purged_at.is_(None))
        .values(availability="pending", copy_attempt_count=0, next_attempt_at=now))
    fields = document_fields(crypto, revision)
    phone = await session.scalar(select(Contact.value_ciphertext).where(Contact.agency_id == person.agency_id,
        Contact.company_id == person.company_id, Contact.traveller_id == person.id,
        Contact.kind == "phone", Contact.status == "current"))
    await refresh_current_identity(session, person, fields,
        crypto.decrypt(person.display_name_ciphertext) if person.display_name_ciphertext else "Traveller",
        crypto.decrypt(phone) if phone else None, actor_id, crypto)
    person.revision += 1
    person.authorization_version += 1
    await revoke_person_access(session, person, now)
    session.add(Event(agency_id=person.agency_id, company_id=person.company_id, traveller_id=person.id,
        event_type="document_promoted", aggregate_id=passport.id, aggregate_revision=passport.revision,
        idempotency_key=f"staff-document:{revision.id}", reason_code="staff_reviewed_upload"))
    await AuditLogRepository(session).record(action="traveller.staff_document_version_added", entity_type="traveller_profile",
        entity_id=str(person.id), agency_id=person.agency_id, user_id=actor_id,
        metadata={"document_revision_id": str(revision.id), "change_kind": provenance["change_kind"],
            "reason": provenance["review_reason"]})
    await session.flush()
