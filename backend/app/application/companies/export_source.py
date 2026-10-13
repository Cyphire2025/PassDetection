"""Keyset export sources; every page repeats current tenant/actor authority."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.access import visible_company_groups
from app.application.companies.original_record import latest_original_records
from app.application.companies.people import document_fields, person_scope
from app.application.companies.source_documents import SOURCE_SIDES
from app.application.travellers.asset_policy import is_reviewable_asset
from app.application.travellers.snapshot_access import retained_asset_authority
from app.domain.entities.entities import User
from app.infrastructure.database.company_data_export_models import CompanyDataExportJobModel as Job
from app.infrastructure.database.models import ClientGroupModel
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
    TravellerPassportModel as Passport,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerProfileModel as Person,
)
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto

EXCEL_FIELDS = ("surname", "given_names", "passport_number", "nationality", "sex", "date_of_birth",
    "place_of_birth", "date_of_issue", "date_of_expiry", "place_of_issue", "issuing_country", "document_type")
EXCEL_HEADERS = ("Traveller ID", "Current name", "Current phone", "Profile revision", *EXCEL_FIELDS, "Record source", "Source record ID")
PERSON_PAGE_SIZE = 250
IMAGE_PAGE_SIZE = 16


@dataclass(frozen=True)
class ImageSource:
    identifier: uuid.UUID
    person_id: uuid.UUID
    revision_id: uuid.UUID
    version: int
    side: str
    key: str
    content_type: str
    size: int
    source_kind: str = "retained_revision"


async def source_image_page(session: AsyncSession, job: Job, user: User) -> list[ImageSource]:
    """One side per pass avoids losing a fifth image at a volume boundary."""
    side = job.phase.removeprefix("source_")
    if side not in SOURCE_SIDES:
        raise ValueError("invalid_source_export_phase")
    groups = visible_company_groups(user, job.agency_id, job.company_id).with_only_columns(ClientGroupModel.id)
    query = select(MatchCase).where(MatchCase.agency_id == job.agency_id, MatchCase.company_id == job.company_id,
        MatchCase.group_id.in_(groups), MatchCase.source_kind == "passport_submission",
        MatchCase.status == "resolved", MatchCase.traveller_id.in_(person_scope(user, job.agency_id, job.company_id).with_only_columns(Person.id)),
        MatchCase.created_at <= job.created_at)
    if job.cursor:
        query = query.where(MatchCase.id > job.cursor)
    cases = list((await session.scalars(query.order_by(MatchCase.id).limit(IMAGE_PAGE_SIZE))).all())
    source_ids = [uuid.UUID(case.source_row_key) for case in cases]
    from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES
    from app.infrastructure.database.models import PassportSubmissionModel as Submission
    attribute = getattr(Submission, SOURCE_SIDES[side])
    sources = {row.id: row for row in (await session.execute(select(Submission.id,
        Submission.group_id, Submission.extraction_revision, attribute.label("key")).where(
        Submission.agency_id == job.agency_id, Submission.id.in_(source_ids),
        Submission.group_id.in_(groups), Submission.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES)))).all()}
    result = []
    for case in cases:
        assert case.traveller_id is not None
        source_id = uuid.UUID(case.source_row_key)
        source = sources.get(source_id)
        # Retained keys are exported only through their independently authorized
        # asset rows, never through a stale operational pointer.
        key = (source.key if source and source.group_id == case.group_id
            and source.key and not source.key.startswith("travellers/") else "")
        result.append(ImageSource(case.id, case.traveller_id, source_id,
            source.extraction_revision if source else 0, side, key, "", -1 if key else 0, "original_submission"))
    return result


async def people_export_page(session: AsyncSession, job: Job, user: User,
    crypto: TravellerReuseCrypto,
) -> tuple[list[list[str | int]], uuid.UUID | None]:
    query = person_scope(user, job.agency_id, job.company_id).where(Person.created_at <= job.created_at)
    if job.cursor:
        query = query.where(Person.id > job.cursor)
    people = list((await session.scalars(query.order_by(Person.id).limit(PERSON_PAGE_SIZE))).all())
    if not people:
        return [], None
    ids = [person.id for person in people]
    latest = select(func.max(Document.revision_number)).where(Document.passport_id == Passport.id,
        Document.status == "accepted").correlate(Passport).scalar_subquery()
    documents = dict((await session.execute(select(Passport.traveller_id, Document).join(Document,
        (Document.passport_id == Passport.id) & (Document.agency_id == Passport.agency_id)
        & (Document.company_id == Passport.company_id)).where(Passport.agency_id == job.agency_id,
        Passport.company_id == job.company_id, Passport.traveller_id.in_(ids), Passport.is_default.is_(True),
        Passport.status == "accepted", Document.revision_number == latest))).tuples().all())
    contacts = dict((await session.execute(select(Contact.traveller_id, Contact.value_ciphertext).where(
        Contact.agency_id == job.agency_id, Contact.company_id == job.company_id, Contact.traveller_id.in_(ids),
        Contact.kind == "phone", Contact.status == "current"))).tuples().all())
    originals = await latest_original_records(session, user=user, agency_id=job.agency_id, company_id=job.company_id,
        person_ids=[identifier for identifier in ids if identifier not in documents])
    result: list[list[str | int]] = []
    for person in people:
        fields = document_fields(crypto, documents[person.id]) if person.id in documents else originals[person.id].fields if person.id in originals else {}
        result.append([str(person.id), crypto.decrypt(person.display_name_ciphertext) if person.display_name_ciphertext else "Traveller",
            crypto.decrypt(contacts[person.id]) if person.id in contacts else "", person.revision,
            *(fields.get(key, "") for key in EXCEL_FIELDS),
            "accepted_current_document" if person.id in documents else "original_submission" if person.id in originals else "profile_only",
            str(documents[person.id].id) if person.id in documents else str(originals[person.id].source_id) if person.id in originals else ""])
    return result, people[-1].id


async def retained_image_page(session: AsyncSession, job: Job, user: User) -> list[ImageSource]:
    people = person_scope(user, job.agency_id, job.company_id).with_only_columns(Person.id)
    query = select(Asset, Document.revision_number).join(Document,
        (Document.id == Asset.document_revision_id) & (Document.agency_id == Asset.agency_id)
        & (Document.company_id == Asset.company_id)).join(Person,
        (Person.id == Asset.traveller_id) & (Person.agency_id == Asset.agency_id)
        & (Person.company_id == Asset.company_id)).where(Asset.agency_id == job.agency_id,
        Asset.company_id == job.company_id, Asset.traveller_id.in_(people), Asset.created_at <= job.created_at,
        Asset.kind == "original", Asset.availability == "available", Asset.purged_at.is_(None), retained_asset_authority())
    if job.cursor:
        query = query.where(Asset.id > job.cursor)
    rows = (await session.execute(query.order_by(Asset.id).limit(IMAGE_PAGE_SIZE))).all()
    # Unreadable or purged evidence is reported by the UI, never exported by
    # following stale locators. The cursor still advances over expired rows.
    return [ImageSource(asset.id, asset.traveller_id, asset.document_revision_id, revision,
        asset.document_side, asset.object_key or "", asset.content_type,
        asset.byte_size if is_reviewable_asset(asset, datetime.now(UTC)) else 0) for asset, revision in rows]
