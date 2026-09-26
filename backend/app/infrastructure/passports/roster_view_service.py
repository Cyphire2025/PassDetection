"""Revision-fenced shared preparation of the exact duplicate-aware roster view."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.passports.submission_view import (
    PreparedSubmissionView,
    prepare_submission_view,
)
from app.domain.entities.entities import User
from app.infrastructure.passports.roster_cache import RosterCache
from app.infrastructure.repositories.passport_submission_view_repository import (
    PassportSubmissionViewRepository,
)


async def prepared_roster(
    session: AsyncSession, *, group_id: uuid.UUID, user: User, include_deleted: bool,
    submission_filter: str, sort_by: str, sort_order: str, search: str | None, page_size: int,
) -> tuple[PreparedSubmissionView, tuple[int, date | None] | None]:
    repository = PassportSubmissionViewRepository(session)
    revision = await repository.revision(group_id=group_id, user=user, include_deleted=include_deleted)
    today = datetime.now(UTC).date()
    options: dict[str, Any] = dict(submission_filter=submission_filter, sort_by=sort_by,
        sort_order=sort_order, search=search, page_size=page_size, today=today,
        travel_date=revision[1] if revision is not None else None)
    if revision is None:
        return prepare_submission_view([], **options), None

    async def compute() -> PreparedSubmissionView:
        rows = await repository.projection(group_id=group_id, user=user, include_deleted=include_deleted)
        return await asyncio.to_thread(prepare_submission_view, rows, **options)

    # SQLite does not run the PostgreSQL invalidation triggers. Do not make
    # local/unit stores incorrectly look revision-safe by caching revision 0.
    if session.get_bind().dialect.name != "postgresql":
        return await compute(), revision
    cache = RosterCache()
    identity = cache.identity(group_id=group_id, user_id=user.id, agency_id=user.agency_id,
        role=user.role.value, include_deleted=include_deleted, revision=revision[0], **options)
    token = None
    try:
        found = await cache.get(identity)
        if found is not None:
            return found, revision
        token = await cache.claim(identity)
        if token is None:
            # Bounded single-flight wait across workers. Cache failure always
            # falls back to the existing authoritative computation.
            try:
                async with asyncio.timeout(1):
                    while True:
                        await asyncio.sleep(0.05)
                        found = await cache.get(identity)
                        if found is not None:
                            return found, revision
            except TimeoutError:
                pass
        index = await compute()
        await cache.put(identity, index)
        return index, revision
    finally:
        if token is not None:
            await cache.release(identity, token)
        await cache.close()
