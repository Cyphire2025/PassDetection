"""Bounded scalar rename metadata, without storage locators or full ORM rows."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.document_rename.read_scope import download_metadata_eligible
from app.domain.entities.entities import User
from app.infrastructure.database.models import DocumentRenameBatchModel, DocumentRenameItemModel
from app.infrastructure.repositories.document_rename_queries import (
    rename_batches_query,
    rename_items_query,
)

MAX_RENAME_BATCH_ITEMS = 1500
BATCH_TEXT = {"title": 160, "status": 32}
BATCH_COUNTS = ("total_count", "visa_count", "ticket_count", "unknown_count")
ITEM_TEXT = {"original_filename": 255, "renamed_filename": 255, "detected_type": 32, "status": 32, "reason": 255}
IDENTIFIER_TEXT = {"extracted_name": 255, "extracted_passport_number": 32, "extracted_reference": 80}


class RenameReadLimitError(ValueError):
    pass


class RenameReadUnavailableError(ValueError):
    pass


def _check_text(rows: list[dict[str, Any]], bounds: dict[str, int]) -> None:
    for row in rows:
        if any(row[key] is not None and len(row[key]) > bound for key, bound in bounds.items()):
            raise RenameReadLimitError("Rename metadata exceeds its field bound")


class DocumentRenameReadRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _batches(self, actor: User, agency_id: UUID):  # type: ignore[no-untyped-def]
        model = DocumentRenameBatchModel
        columns: list[Any] = [model.id, model.created_at, *(getattr(model, name) for name in BATCH_COUNTS)]
        columns.extend(func.substr(getattr(model, name), 1, bound + 1).label(name) for name, bound in BATCH_TEXT.items())
        return rename_batches_query(user_id=actor.id, role=actor.role, agency_id=agency_id).with_only_columns(*columns)

    @staticmethod
    def _check_batches(rows: list[dict[str, Any]]) -> None:
        _check_text(rows, BATCH_TEXT)
        if any(type(row[key]) is not int or row[key] < 0 for row in rows for key in BATCH_COUNTS):
            raise RenameReadLimitError("Rename counters are unavailable")

    async def batches(self, actor: User, agency_id: UUID, *, cutoff: datetime,
                      after: tuple[datetime, UUID] | None, limit: int) -> list[dict[str, Any]]:
        model = DocumentRenameBatchModel
        query = self._batches(actor, agency_id).where(model.created_at <= cutoff)
        if after:
            stamp, identifier = after
            query = query.where(or_(model.created_at < stamp, and_(model.created_at == stamp, model.id < identifier)))
        rows = [dict(row) for row in (await self.session.execute(query.order_by(model.created_at.desc(), model.id.desc())
            .limit(limit + 1))).mappings()]
        self._check_batches(rows)
        return rows

    async def batch(self, actor: User, agency_id: UUID, batch_id: UUID) -> dict[str, Any]:
        row = (await self.session.execute(self._batches(actor, agency_id)
            .where(DocumentRenameBatchModel.id == batch_id))).mappings().one_or_none()
        if row is None:
            raise RenameReadUnavailableError("Rename batch is unavailable")
        result = dict(row)
        self._check_batches([result])
        return result

    async def items(self, agency_id: UUID, batch_id: UUID, *, page: int, page_size: int,
                    include_extracted_identifiers: bool) -> tuple[list[dict[str, Any]], int]:
        model = DocumentRenameItemModel
        count = int(await self.session.scalar(select(func.count(model.id)).where(
            model.batch_id == batch_id, model.agency_id == agency_id)) or 0)
        if count > MAX_RENAME_BATCH_ITEMS:
            raise RenameReadLimitError("Rename batch exceeds supported item bound")
        columns: list[Any] = [model.id, (model.storage_key != "").label("storage_present")]
        columns.extend(func.substr(getattr(model, name), 1, bound + 1).label(name) for name, bound in ITEM_TEXT.items())
        for name, bound in IDENTIFIER_TEXT.items():
            columns.append((func.substr(getattr(model, name), 1, bound + 1)
                            if include_extracted_identifiers else literal(None)).label(name))
        query = rename_items_query(batch_id, agency_id).with_only_columns(*columns).order_by(model.id.asc())
        rows = [dict(row) for row in (await self.session.execute(query.offset((page - 1) * page_size).limit(page_size))).mappings()]
        _check_text(rows, {**ITEM_TEXT, **IDENTIFIER_TEXT})
        for row in rows:
            row["download_metadata_eligible"] = download_metadata_eligible(row["detected_type"], row["status"], bool(row.pop("storage_present")))
        return rows, count
