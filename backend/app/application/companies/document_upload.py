"""Prepare an immutable reviewed revision before writing its bounded image."""

import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.current_record import (
    append_correction,
)
from app.application.companies.people import current_document, document_fields
from app.application.companies.people_contracts import DocumentUpload
from app.application.travellers.versioning import accepted_dates
from app.domain.exceptions.exceptions import ConflictError
from app.domain.services.traveller_verification import exact_passport_number, issuing_context
from app.domain.value_objects.passport_fields import normalize_reviewed_passport_fields
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
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto


@dataclass(frozen=True)
class UploadTarget:
    asset_id: uuid.UUID
    key: str
    already_available: bool


async def prepare_document_upload(session: AsyncSession, *, person: Person, actor_id: uuid.UUID,
    body: DocumentUpload, checksum: str, size: int, media: str, crypto: TravellerReuseCrypto,
) -> UploadTarget:
    if person.deleted_at is not None or person.status != "active" or person.reuse_permission_status == "withdrawn":
        raise ConflictError("Review the unavailable or withdrawn identity before adding document versions.")
    key = crypto.scoped_digest("staff-document-upload", person.agency_id, person.company_id,
        str(actor_id), str(person.id), body.idempotency_key)
    digest = crypto.digest("staff-document-content", body.model_dump_json(exclude={"idempotency_key"}), checksum)
    previous = await session.scalar(select(Document).where(Document.agency_id == person.agency_id,
        Document.company_id == person.company_id, Document.traveller_id == person.id, Document.idempotency_key == key))
    if previous:
        if not hmac.compare_digest(str(previous.source_provenance.get("request_digest", "")), digest):
            raise ConflictError("The document request differs. Use a new request key.")
        asset = await session.scalar(select(Asset).where(Asset.document_revision_id == previous.id,
            Asset.agency_id == person.agency_id, Asset.company_id == person.company_id,
            Asset.document_side == body.side, Asset.kind == "original"))
        if asset is None or not asset.object_key or asset.purged_at is not None:
            raise ConflictError("The previous upload is no longer available.")
        return UploadTarget(asset.id, asset.object_key, asset.availability == "available")
    if person.revision != body.expected_revision:
        raise ConflictError("The record changed. Reopen it before uploading.")
    fields = normalize_reviewed_passport_fields(body.fields)
    issuer, kind = issuing_context(body.issuing_country, body.document_type)
    number = exact_passport_number(fields.get("passport_number", ""))
    fields.update(issuing_country=issuer, document_type=kind)
    fingerprint = crypto.passport_fingerprint(person.agency_id, person.company_id, number, issuer, kind)
    matches = list((await session.scalars(select(Passport).where(Passport.agency_id == person.agency_id,
        Passport.company_id == person.company_id, Passport.number_fingerprint == fingerprint,
        Passport.fingerprint_key_version == crypto.key_version).limit(2))).all())
    if len(matches) > 1:
        raise ConflictError("This document identity is ambiguous and needs review.")
    passport = matches[0] if matches else None
    if passport is not None and (passport.traveller_id != person.id or passport.status not in {"accepted", "superseded"}):
        raise ConflictError("This document identity needs review; it cannot be assigned automatically.")
    selected = await current_document(session, person)
    if body.change_kind != "renewal" and (not selected or selected[0].number_fingerprint != fingerprint):
        raise ConflictError("Use a reviewed renewal for a changed passport identity.")
    if body.change_kind == "renewal" and body.side != "front":
        raise ConflictError("Start a renewed passport with its front information page.")
    if body.change_kind != "renewal" and selected:
        fields = {**document_fields(crypto, selected[1]), **fields}
        revision = await append_correction(session, person=person, passport=selected[0], prior=selected[1],
            fields=fields, actor_id=actor_id, key=key, crypto=crypto, publish=False)
        replacement = await session.scalar(select(Asset).where(Asset.document_revision_id == revision.id,
            Asset.document_side == body.side, Asset.kind == "original"))
        if replacement:
            await session.delete(replacement)  # Pending copy only, never a stored version.
    else:
        if passport is None:
            passport = Passport(agency_id=person.agency_id, company_id=person.company_id, traveller_id=person.id,
                issuing_country=issuer, document_type=kind, number_ciphertext=crypto.encrypt(number),
                number_fingerprint=fingerprint, fingerprint_key_version=crypto.key_version, status="candidate")
            session.add(passport)
            await session.flush()
        maximum = await session.scalar(select(func.max(Document.revision_number)).where(Document.passport_id == passport.id))
        dates = accepted_dates(fields)
        revision = Document(agency_id=person.agency_id, company_id=person.company_id, traveller_id=person.id,
            passport_id=passport.id, revision_number=int(maximum or 0) + 1, status="candidate",
            fields_ciphertext=crypto.encrypt(json.dumps(fields)), source_provenance={},
            reliable_fields={key: {"accepted": True, "source": "staff_review"} for key in dates},
            date_of_birth=dates.get("date_of_birth"), issue_date=dates.get("issue_date"), expiry_date=dates.get("expiry_date"),
            accepted_at=None, accepted_by_user_id=actor_id, idempotency_key=key)
        session.add(revision)
        await session.flush()
    revision.source_provenance = {**revision.source_provenance, "staff_record_edit": True,
        "change_kind": body.change_kind, "request_digest": digest, "actor_user_id": str(actor_id),
        "expected_profile_revision": body.expected_revision, "review_reason": body.reason}
    asset_id = uuid.uuid4()
    object_key = f"travellers/{person.agency_id}/{person.company_id}/{person.id}/{revision.id}/{asset_id}.jpg"
    asset = Asset(id=asset_id, agency_id=person.agency_id, company_id=person.company_id, traveller_id=person.id,
        passport_id=revision.passport_id, document_revision_id=revision.id, kind="original", document_side=body.side,
        object_key=object_key, content_type=media, byte_size=size, content_sha256=checksum,
        availability="pending", retention_basis="staff_reviewed_current_record",
        next_attempt_at=datetime.now(UTC) + timedelta(minutes=10))
    session.add(asset)
    await session.flush()
    return UploadTarget(asset.id, object_key, False)
