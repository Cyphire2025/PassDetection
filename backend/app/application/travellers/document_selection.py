"""One bounded current-revision rule, never a generic usable-image fallback.

Read at most 16 accepted revisions through the passport/status/revision index.
Each placeholder check is a scoped source primary-key seek. O(log R + K log S)
database work, K <= 16; O(1) result space, O(K) for exceptional proof checks.
New real pending, failed, corrected or expired revisions remain authoritative.
"""

import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.orm.util import AliasedClass
from sqlalchemy.sql import ColumnElement
from sqlalchemy.sql.selectable import ScalarSelect

from app.application.travellers.errors import ReuseError, ReuseReason
from app.infrastructure.database.models import PassportSubmissionModel as Source
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentRevisionModel as Document,
)
from app.infrastructure.database.traveller_reuse_models import TravellerPassportModel as Passport
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto

MAX_CURRENT_DOCUMENT_CANDIDATES = 16
SOURCE_IMAGES = ("image_s3_key", "passport_back_s3_key", "passport_cover_s3_key",
    "passport_back_cover_s3_key", "passport_photo_s3_key")
PLACEHOLDER_PREFIX = "excel-imports/"


def metadata_only_source(source: Source) -> bool:
    return bool(source.image_s3_key and source.image_s3_key.startswith(PLACEHOLDER_PREFIX)
        and all(not getattr(source, field) or getattr(source, field).startswith(PLACEHOLDER_PREFIX)
            for field in SOURCE_IMAGES))


def metadata_only_revision(document: type[Document] | AliasedClass[Document]) -> ColumnElement[bool]:
    """Only canonical operator history backed solely by import placeholders."""
    from app.application.travellers.legacy_staff_acceptance import STAFF_ACCEPTANCE_RULE
    source = aliased(Source)
    return and_(document.source_provenance["authority_kind"].as_string() == "operator_registration",
        document.source_provenance["acceptance_rule"].as_string() == STAFF_ACCEPTANCE_RULE,
        select(source.id).where(source.id == document.source_submission_id,
            source.agency_id == document.agency_id, source.group_id == document.source_group_id,
            source.status == "staff_approved",
            source.extraction_revision == document.source_provenance["extraction_revision"].as_integer(),
            source.image_s3_key.startswith(PLACEHOLDER_PREFIX),
            *(or_(getattr(source, field).is_(None), getattr(source, field) == "",
                getattr(source, field).startswith(PLACEHOLDER_PREFIX)) for field in SOURCE_IMAGES)
        ).correlate(document).exists()).is_(True)


def latest_document_id(passport: type[Passport] | AliasedClass[Passport]) -> ScalarSelect[uuid.UUID]:
    revision = aliased(Document)
    return select(revision.id).where(*_passport_scope(revision, passport))\
        .order_by(revision.revision_number.desc()).limit(1).correlate(passport).scalar_subquery()


def current_document_id(passport: type[Passport] | AliasedClass[Passport]) -> ScalarSelect[uuid.UUID]:
    """Fail closed beyond the cap; never switch passports or skip real evidence."""
    revision = aliased(Document)
    candidates = select(revision.id, revision.revision_number).where(*_passport_scope(revision, passport))\
        .order_by(revision.revision_number.desc()).limit(MAX_CURRENT_DOCUMENT_CANDIDATES).correlate(passport).subquery()
    chosen = aliased(Document)
    return select(chosen.id).join(candidates, candidates.c.id == chosen.id).where(
        *_passport_scope(chosen, passport), ~metadata_only_revision(chosen))\
        .order_by(candidates.c.revision_number.desc()).limit(1).correlate(passport).scalar_subquery()


def _passport_scope(document: type[Document] | AliasedClass[Document], passport: type[Passport] | AliasedClass[Passport]) -> tuple[ColumnElement[bool], ...]:
    return (document.passport_id == passport.id, document.agency_id == passport.agency_id,
        document.company_id == passport.company_id, document.traveller_id == passport.traveller_id,
        document.status == "accepted")


async def require_frozen_selection_proof(session: AsyncSession, passport: Passport, selected: Document,
    crypto: TravellerReuseCrypto | None = None,
) -> None:
    """A skipped import must not bypass changed source proof or original ownership."""
    from app.application.travellers.accepted_source import retained_source_is_current
    rows = (await session.execute(select(Document, Source).outerjoin(Source,
        (Source.id == Document.source_submission_id) & (Source.agency_id == Document.agency_id)
        & (Source.group_id == Document.source_group_id)).where(
        Document.passport_id == passport.id, Document.agency_id == passport.agency_id,
        Document.company_id == passport.company_id, Document.traveller_id == passport.traveller_id,
        Document.status == "accepted", Document.revision_number >= selected.revision_number,
    ).order_by(Document.revision_number.desc()).limit(MAX_CURRENT_DOCUMENT_CANDIDATES + 1)
        .execution_options(populate_existing=True))).all()
    if not rows or len(rows) > MAX_CURRENT_DOCUMENT_CANDIDATES:
        raise ReuseError(ReuseReason.UNAVAILABLE)
    for revision, source in rows:
        if (source is None or source.extraction_revision != revision.source_provenance.get("extraction_revision")
                or (revision.id != selected.id and not metadata_only_source(source))
                or not retained_source_is_current(revision, source, crypto)):
            raise ReuseError(ReuseReason.REVISION_CONFLICT)
