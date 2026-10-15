"""Encrypted comparisons maintain an indexed, opaque alphabetical ordinal.

Caller holds the company lock. A numeric seek takes at most 260 comparisons;
normal ordered inserts use a fixed wide stride. Crowded interior gaps rebalance
at most 512 adjacent rows, never the whole company. Exhaustion remains queued.
Ranks expose ordering only; names are decrypted only in this background path.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.directory_names import name_order_key
from app.infrastructure.database.company_directory_models import (
    CompanyDirectoryPersonModel as Entry,
)
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto

MAX_RANK = 10**78 - 1
STRIDE = 10**40


class DirectoryRankUnavailable(RuntimeError):
    pass


def encode_rank(value: int) -> str:
    if not 0 < value < MAX_RANK:
        raise DirectoryRankUnavailable("directory_rank_capacity")
    return str(value).zfill(78)


def _key(entry: Entry, crypto: TravellerReuseCrypto) -> tuple[str, str]:
    return name_order_key(crypto.decrypt(entry.name_ciphertext), entry.traveller_id)


async def allocate_name_rank(session: AsyncSession, *, agency_id: uuid.UUID, company_id: uuid.UUID,
    person_id: uuid.UUID, name: str, crypto: TravellerReuseCrypto,
) -> str:
    query = select(Entry).where(Entry.agency_id == agency_id, Entry.company_id == company_id,
        Entry.traveller_id != person_id)
    target = name_order_key(name, person_id)
    left = await session.scalar(query.order_by(Entry.name_rank).limit(1))
    if left is None:
        return encode_rank(MAX_RANK // 2)
    if target < _key(left, crypto):
        return encode_rank(int(left.name_rank) - STRIDE)
    right = await session.scalar(query.order_by(Entry.name_rank.desc()).limit(1))
    assert right is not None
    if target > _key(right, crypto):
        return encode_rank(int(right.name_rank) + STRIDE)
    for _ in range(260):
        low, high = int(left.name_rank), int(right.name_rank)
        if high - low <= 1:
            return await _rebalance(session, query, person_id, target, left, right, crypto)
        middle = encode_rank((low + high) // 2)
        candidate = await session.scalar(query.where(Entry.name_rank > left.name_rank,
            Entry.name_rank < right.name_rank, Entry.name_rank <= middle).order_by(Entry.name_rank.desc()).limit(1))
        if candidate is None:
            candidate = await session.scalar(query.where(Entry.name_rank > middle,
                Entry.name_rank < right.name_rank).order_by(Entry.name_rank).limit(1))
        if candidate is None:
            return middle
        if target < _key(candidate, crypto):
            right = candidate
        else:
            left = candidate
    raise DirectoryRankUnavailable("directory_rank_seek_budget")


async def _rebalance(session: AsyncSession, query: object, person_id: uuid.UUID,
    target: tuple[str, str], left: Entry, right: Entry, crypto: TravellerReuseCrypto,
) -> str:
    # Query's shape is fixed by allocate_name_rank and retains tenant scope.
    from sqlalchemy import Select
    assert isinstance(query, Select)
    before = list(await session.scalars(query.where(Entry.name_rank <= left.name_rank)
        .order_by(Entry.name_rank.desc()).limit(256)))
    after = list(await session.scalars(query.where(Entry.name_rank >= right.name_rank)
        .order_by(Entry.name_rank).limit(256)))
    rows = sorted(before + after, key=lambda row: row.name_rank)
    lower = await session.scalar(query.where(Entry.name_rank < rows[0].name_rank).order_by(Entry.name_rank.desc()).limit(1))
    upper = await session.scalar(query.where(Entry.name_rank > rows[-1].name_rank).order_by(Entry.name_rank).limit(1))
    start = int(lower.name_rank) if lower else max(0, int(rows[0].name_rank) - STRIDE * (len(rows) + 1))
    end = int(upper.name_rank) if upper else min(MAX_RANK, int(rows[-1].name_rank) + STRIDE * (len(rows) + 1))
    step = (end - start) // (len(rows) + 2)
    if step < 2:
        raise DirectoryRankUnavailable("directory_rank_rebalance_budget")
    ordered = sorted([(_key(row, crypto), row.traveller_id) for row in rows] + [(target, person_id)])
    ranks = {identifier: encode_rank(start + step * (index + 1)) for index, (_, identifier) in enumerate(ordered)}
    # SQLAlchemy batches changed rows; keep its identity map coherent as well.
    for row in rows:
        row.name_rank = ranks[row.traveller_id]
    await session.flush()
    return ranks[person_id]
