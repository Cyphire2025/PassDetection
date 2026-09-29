"""Database-side admission before retained source values reach the Python ORM.

This measures uncompressed textual column values, not Python heap consumption.
Callers lock parent rows before children so FK insertions cannot widen a source;
all retained children are locked, including currently excluded status values.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import LargeBinary, Text, cast, func, inspect, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.application.mcp.artifacts import ArtifactError
from app.core.config.settings import Settings


class ExportSourceBudget:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session = session
        self.row_limit = settings.mcp.export_source_row_limit
        self.remaining_bytes = settings.mcp.export_source_byte_limit

    async def retain(
        self, model: Any, *predicates: Any, update: bool = False
    ) -> list[Any]:
        """Only scalar IDs and one aggregate integer cross the admission boundary."""
        mapper = inspect(model)
        primary_key = mapper.primary_key[0]
        identifiers = list(
            (
                await self.session.scalars(
                    select(primary_key)
                    .where(*predicates)
                    .order_by(primary_key)
                    .limit(self.row_limit + 1)
                    .with_for_update(read=not update, nowait=True)
                )
            ).all()
        )
        if len(identifiers) > self.row_limit:
            raise ArtifactError("Export sources exceed the configured row limit", 413)
        if not identifiers:
            return []
        size: ColumnElement[int] = literal(0)
        postgres = self.session.get_bind().dialect.name == "postgresql"
        for column in mapper.columns:
            # PostgreSQL octet_length detoasts before measuring. SQLite BLOB cast
            # counts UTF-8 bytes rather than Unicode code points in test fixtures.
            value = cast(column, Text)
            length = func.octet_length(value) if postgres else func.length(cast(value, LargeBinary))
            size = size + func.coalesce(length, 0)
        consumed = await self.session.scalar(
            select(func.coalesce(func.sum(size), 0)).where(primary_key.in_(identifiers))
        )
        self.remaining_bytes -= int(consumed or 0)
        if self.remaining_bytes < 0:
            raise ArtifactError("Export sources exceed the configured byte limit", 413)
        return identifiers
