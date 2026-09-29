"""Stable bounded SQL keysets for server-chosen read projections."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.ext.asyncio import AsyncSession


def page_query(statement: Any, model: Any, *, cutoff: datetime,
               after: tuple[datetime, uuid.UUID] | None, size: int, timestamp: Any = None) -> Any:
    if not 1 <= size <= 100:
        raise ValueError("Page size must be between 1 and 100")
    stamp = model.created_at if timestamp is None else timestamp
    statement = statement.where(stamp <= cutoff)
    if after:
        statement = statement.where(or_(stamp < after[0], and_(stamp == after[0], model.id < after[1])))
    return statement.order_by(stamp.desc(), model.id.desc()).limit(size + 1)


async def read_page(session: AsyncSession, statement: Any, model: Any, **page: Any) -> list[dict[str, Any]]:
    result = await session.execute(page_query(statement, model, **page))
    return [dict(row) for row in result.mappings()]
