"""Staff-only latest original fields without asserting reusable identity evidence."""

import uuid
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.access import visible_company_groups
from app.application.travellers.history import PASSPORT_REVIEW_FIELDS
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES, User
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.models import PassportSubmissionModel as Source
from app.infrastructure.database.traveller_reuse_models import TravellerMatchCaseModel as MatchCase
from app.infrastructure.database.traveller_reuse_models import TravellerProfileModel as Person


class OriginalRecord(BaseModel):
    source_id: uuid.UUID
    group_id: uuid.UUID
    status: str
    source_revision: int
    created_at: datetime
    fields: dict[str, str]


async def latest_original_records(session: AsyncSession, *, user: User, agency_id: uuid.UUID,
    company_id: uuid.UUID, person_ids: list[uuid.UUID],
) -> dict[uuid.UUID, OriginalRecord]:
    """Two queries, <=250 indexed top-one probes, O(page size) application RAM.

    The final source is rechecked against live visibility. An unavailable newest
    source is not silently replaced by older identity facts.
    """
    if not person_ids:
        return {}
    if len(person_ids) > 250:
        raise ValueError("original_record_page_limit")
    groups = visible_company_groups(user, agency_id, company_id).with_only_columns(ClientGroupModel.id)
    newest = select(MatchCase.id).where(MatchCase.agency_id == agency_id,
        MatchCase.company_id == company_id, MatchCase.traveller_id == Person.id,
        MatchCase.group_id.in_(groups), MatchCase.status == "resolved", MatchCase.source_kind == "passport_submission",
        MatchCase.source_created_at.is_not(None))
    newest = newest.order_by(MatchCase.source_created_at.desc(), MatchCase.id.desc()).limit(1).correlate(Person)
    pairs = (await session.execute(select(Person.id, MatchCase.source_row_key, MatchCase.group_id)
        .outerjoin(MatchCase, MatchCase.id == newest.scalar_subquery()).where(
        Person.agency_id == agency_id, Person.company_id == company_id, Person.id.in_(person_ids)))).all()
    source_by_person = {}
    for person_id, key, group_id in pairs:
        try:
            source_by_person[person_id] = (uuid.UUID(key), group_id) if key else None
        except ValueError:
            continue
    source_ids = [pair[0] for pair in source_by_person.values() if pair is not None]
    sources = (await session.execute(select(Source.id, Source.group_id, Source.status, Source.extraction_revision,
        Source.created_at, Source.extracted_fields, Source.confirmed_fields).where(Source.agency_id == agency_id,
        Source.id.in_(source_ids), Source.group_id.in_(groups), Source.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES)))).all()
    by_source = {source.id: OriginalRecord(source_id=source.id, group_id=source.group_id, status=source.status,
        source_revision=source.extraction_revision, created_at=source.created_at,
        fields={key: value for key, value in {**(source.extracted_fields or {}), **(source.confirmed_fields or {})}.items()
            if key in PASSPORT_REVIEW_FIELDS and isinstance(value, str) and len(value) <= 160}) for source in sources}
    return {person_id: by_source[pair[0]] for person_id, pair in source_by_person.items()
        if pair is not None and pair[0] in by_source and by_source[pair[0]].group_id == pair[1]}
