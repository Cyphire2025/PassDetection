"""Tenant-scoped blind search and keyset paging over the derived directory.

Each page hydrates at most 101 profiles. Name-prefix checks use the keyed token
index; sorting uses opaque ranks. No identity ciphertext is decrypted to filter
or sort. Visible-group counters prevent manager filters exposing hidden trips.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.application.companies.access import visible_company_groups
from app.application.companies.directory_names import search_digests
from app.application.companies.directory_projection import ensure_directory_state
from app.application.companies.people import directory_items, person_scope
from app.application.companies.people_contracts import PersonPage
from app.application.companies.source_documents import indexing_pending
from app.application.mcp.read_cursor import MCPReadCursor
from app.domain.entities.entities import User, UserRole
from app.domain.services.traveller_identity import normalize_name
from app.infrastructure.database.company_directory_models import (
    CompanyDirectoryGroupCountModel as Count,
)
from app.infrastructure.database.company_directory_models import (
    CompanyDirectoryPersonModel as Entry,
)
from app.infrastructure.database.company_directory_models import (
    CompanyDirectoryPrefixModel as Prefix,
)
from app.infrastructure.database.company_directory_models import CompanyDirectoryQueueModel as Queue
from app.infrastructure.database.models import ClientGroupModel as Group
from app.infrastructure.database.traveller_reuse_models import TravellerProfileModel as Person
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto

DirectorySort = Literal["newest", "name_asc", "name_desc"]
SubmissionFilter = Literal["all", "one", "multiple"]


class DirectoryIndexChanged(ValueError):
    pass


def _ordered_page(query: Select[tuple[Person]], column: ColumnElement[Any],
    state: dict[str, Any], sort: DirectorySort,
) -> Select[tuple[Person]]:
    descending = sort != "name_asc"
    if after := MCPReadCursor.after(state):
        marker = after[0] if sort == "newest" else state.get("after_rank")
        if sort != "newest" and (not isinstance(marker, str) or len(marker) != 78 or not marker.isascii() or not marker.isdigit()):
            raise ValueError("Invalid directory cursor; restart the query")
        query = query.where((column < marker) | ((column == marker) & (Person.id < after[1])) if descending
            else (column > marker) | ((column == marker) & (Person.id > after[1])))
    return query.order_by(column.desc() if descending else column.asc(),
        Person.id.desc() if descending else Person.id.asc())


async def company_directory_page(session: AsyncSession, *, user: User, agency_id: uuid.UUID,
    company_id: uuid.UUID, crypto: TravellerReuseCrypto, secret: str, search: str,
    sort: DirectorySort, submissions: SubmissionFilter, cursor: str | None, page_size: int,
) -> PersonPage:
    if not 1 <= page_size <= 100:
        raise ValueError("Choose a page size between 1 and 100")
    projection = await ensure_directory_state(session, agency_id, company_id)
    normalized = normalize_name(search)
    codec = MCPReadCursor(secret, "company-directory-v2")
    state = codec.read(cursor, {"actor": str(user.id), "agency": str(agency_id), "company": str(company_id),
        "search": normalized, "sort": sort, "submissions": submissions})
    if cursor is not None and state.get("generation") != projection.generation:
        raise DirectoryIndexChanged("The directory was updated. Restart from the first page.")
    state["generation"] = projection.generation
    query = person_scope(user, agency_id, company_id).join(Entry, (Entry.traveller_id == Person.id)
        & (Entry.agency_id == agency_id) & (Entry.company_id == company_id)).where(
        Person.created_at <= datetime.fromisoformat(state["cutoff"]), Entry.profile_revision == Person.revision,
        Entry.key_version == crypto.key_version)
    if normalized:
        try:
            query = query.where(Person.id == uuid.UUID(normalized))
        except ValueError:
            for digest in search_digests(normalized, agency_id, company_id, crypto):
                query = query.where(select(Prefix.traveller_id).where(Prefix.agency_id == agency_id,
                    Prefix.company_id == company_id, Prefix.traveller_id == Person.id,
                    Prefix.key_version == crypto.key_version, Prefix.token_digest == digest).exists())
    if submissions != "all":
        groups = visible_company_groups(user, agency_id, company_id).with_only_columns(Group.id)
        total = select(func.coalesce(func.sum(Count.submission_count), 0)).where(
            Count.agency_id == agency_id, Count.company_id == company_id, Count.traveller_id == Person.id,
            Count.group_id.in_(groups)).correlate(Person).scalar_subquery()
        query = query.where(total == 1 if submissions == "one" else total > 1)
    latest: ColumnElement[datetime] = Entry.latest_sort_at.expression
    if user.role == UserRole.AGENCY_MANAGER:
        groups = visible_company_groups(user, agency_id, company_id).with_only_columns(Group.id)
        latest = func.coalesce(select(func.max(Count.latest_submission_at)).where(
            Count.agency_id == agency_id, Count.company_id == company_id, Count.traveller_id == Person.id,
            Count.group_id.in_(groups)).correlate(Person).scalar_subquery(), Person.created_at)
    column = latest if sort == "newest" else Entry.name_rank.expression
    query = _ordered_page(query, column, state, sort).add_columns(Entry.name_rank, latest).limit(page_size + 1)
    selected = (await session.execute(query)).all()
    more, selected = len(selected) > page_size, selected[:page_size]
    pending, failed = (await session.execute(select(
        select(Queue.traveller_id).where(Queue.agency_id == agency_id, Queue.company_id == company_id).exists(),
        select(Queue.traveller_id).where(Queue.agency_id == agency_id, Queue.company_id == company_id,
            Queue.attempt_count >= 5).exists()))).one()
    next_cursor = None
    if more:
        row, rank, submitted = selected[-1]
        next_cursor = codec.encode({**state, "after_created_at": submitted.isoformat(),
            "after_id": str(row.id), "after_rank": rank})
    return PersonPage(items=await directory_items(session, [row for row, _rank, _submitted in selected], user, crypto),
        has_more=more, next_cursor=next_cursor, indexing_failed=bool(failed),
        indexing_pending=bool(not projection.backfill_complete or pending
            or await indexing_pending(session, agency_id, company_id)))
