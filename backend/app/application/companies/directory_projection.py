"""Restartable derived directory maintenance, never identity ownership changes.

Each transaction handles one profile and at most 1,000 compact group counters.
Source counts aggregate indexed resolved source cases; application memory does
not grow with the number of historical submissions. No source or trip is edited.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.directory_names import prefix_digests
from app.application.companies.directory_ranks import allocate_name_rank
from app.infrastructure.database.company_directory_models import (
    CompanyDirectoryGroupCountModel as GroupCount,
)
from app.infrastructure.database.company_directory_models import (
    CompanyDirectoryPersonModel as Entry,
)
from app.infrastructure.database.company_directory_models import (
    CompanyDirectoryPrefixModel as Prefix,
)
from app.infrastructure.database.company_directory_models import (
    CompanyDirectoryQueueModel as Queue,
)
from app.infrastructure.database.company_directory_models import (
    CompanyDirectoryStateModel as State,
)
from app.infrastructure.database.company_directory_queue import queue_directory_rows
from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel as Company
from app.infrastructure.database.models import ClientGroupModel as Group
from app.infrastructure.database.traveller_reuse_models import TravellerMatchCaseModel as Case
from app.infrastructure.database.traveller_reuse_models import TravellerProfileModel as Person
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto


async def ensure_directory_state(session: AsyncSession, agency_id: uuid.UUID, company_id: uuid.UUID) -> State:
    insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert
    await session.execute(insert(State).values(agency_id=agency_id, company_id=company_id,
        generation=1, backfill_complete=False).on_conflict_do_nothing(index_elements=[State.company_id]))
    state = await session.scalar(select(State).where(State.agency_id == agency_id, State.company_id == company_id)
        .with_for_update(read=True))
    assert state is not None
    return state


async def backfill_directory_page(session: AsyncSession, limit: int = 100) -> int:
    candidate = await session.scalar(select(State).where(State.backfill_complete.is_(False))
        .order_by(State.company_id).limit(1))
    if candidate is None:
        return 0
    await session.scalar(select(Company.id).where(Company.id == candidate.company_id,
        Company.agency_id == candidate.agency_id).with_for_update())
    state = await session.scalar(select(State).where(State.company_id == candidate.company_id,
        State.agency_id == candidate.agency_id, State.backfill_complete.is_(False))
        .with_for_update().execution_options(populate_existing=True))
    if state is None:
        return 0
    query = select(Person.id).where(Person.agency_id == state.agency_id, Person.company_id == state.company_id)
    if state.backfill_after is not None:
        query = query.where(Person.id > state.backfill_after)
    ids = list(await session.scalars(query.order_by(Person.id).limit(min(100, max(1, limit)))))
    await session.run_sync(lambda sync: queue_directory_rows(sync, [{"traveller_id": person_id,
        "agency_id": state.agency_id, "company_id": state.company_id,
        "available_at": datetime.now(UTC), "attempt_count": 0} for person_id in ids], reset=False))
    if ids:
        state.backfill_after = ids[-1]
    else:
        state.backfill_complete = True
    return len(ids)


async def refresh_directory_person(session: AsyncSession, person_id: uuid.UUID,
    crypto: TravellerReuseCrypto,
) -> bool:
    pending = await session.get(Queue, person_id)
    if pending is None:
        return False
    await session.scalar(select(Company.id).where(Company.id == pending.company_id,
        Company.agency_id == pending.agency_id).with_for_update())
    person = await session.scalar(select(Person).where(Person.id == person_id,
        Person.agency_id == pending.agency_id, Person.company_id == pending.company_id)
        .with_for_update().execution_options(populate_existing=True))
    pending = await session.scalar(select(Queue).where(Queue.traveller_id == person_id,
        Queue.agency_id == pending.agency_id, Queue.company_id == pending.company_id)
        .with_for_update().execution_options(populate_existing=True))
    if person is None or pending is None:
        return False
    state = await ensure_directory_state(session, person.agency_id, person.company_id)
    if person.deleted_at is not None or person.status == "deleted":
        for model in (Prefix, GroupCount, Entry):
            await session.execute(delete(model).where(model.traveller_id == person.id,
                model.agency_id == person.agency_id, model.company_id == person.company_id))
    else:
        await _project_person(session, person, crypto)
    state.generation += 1
    await session.delete(pending)
    await session.flush()
    return True


async def _project_person(session: AsyncSession, person: Person, crypto: TravellerReuseCrypto) -> None:
    counts = (await session.execute(select(Case.group_id, func.count(), func.max(Case.source_created_at))
        .join(Group, (Group.id == Case.group_id) & (Group.agency_id == Case.agency_id)).where(
        Case.agency_id == person.agency_id, Case.company_id == person.company_id, Case.traveller_id == person.id,
        Case.status == "resolved", Case.source_kind == "passport_submission",
        Case.reason_code != "retained_trip_snapshot", Case.source_created_at.is_not(None),
        Group.company_id == person.company_id, Group.deleted_at.is_(None),
        Group.status.in_(("active", "closed", "archived"))).group_by(Case.group_id).limit(1001))).all()
    if len(counts) > 1000:
        raise ValueError("directory_group_budget")
    name = crypto.decrypt(person.display_name_ciphertext) if person.display_name_ciphertext else "Traveller"
    entry = await session.get(Entry, person.id)
    changed_name = entry is None or entry.key_version != crypto.key_version or crypto.decrypt(entry.name_ciphertext) != name
    if changed_name:
        rank = await allocate_name_rank(session, agency_id=person.agency_id, company_id=person.company_id,
            person_id=person.id, name=name, crypto=crypto)
        await session.execute(delete(Prefix).where(Prefix.agency_id == person.agency_id,
            Prefix.company_id == person.company_id, Prefix.traveller_id == person.id))
        session.add_all([Prefix(agency_id=person.agency_id, company_id=person.company_id, traveller_id=person.id,
            key_version=crypto.key_version, token_digest=value) for value in prefix_digests(name, person.agency_id, person.company_id, crypto)])
        if entry is None:
            entry = Entry(agency_id=person.agency_id, company_id=person.company_id, traveller_id=person.id)
            session.add(entry)
        entry.name_rank, entry.name_ciphertext, entry.key_version = rank, crypto.encrypt(name), crypto.key_version
    assert entry is not None
    entry.profile_revision, entry.indexed_at = person.revision, datetime.now(UTC)
    entry.submission_count = sum(row[1] for row in counts)
    entry.latest_submission_at = max((row[2] for row in counts), default=None)
    entry.latest_sort_at = entry.latest_submission_at or person.created_at
    await session.execute(delete(GroupCount).where(GroupCount.agency_id == person.agency_id,
        GroupCount.company_id == person.company_id, GroupCount.traveller_id == person.id))
    session.add_all([GroupCount(agency_id=person.agency_id, company_id=person.company_id, traveller_id=person.id,
        group_id=group_id, submission_count=count, latest_submission_at=created) for group_id, count, created in counts])
