"""Shared canonical rename ownership predicates and entity queries."""

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.sql.elements import ColumnElement

from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import DocumentRenameBatchModel, DocumentRenameItemModel


def rename_batch_filters(*, user_id: UUID, role: UserRole | str, agency_id: UUID) -> list[ColumnElement[bool]]:
    filters = [DocumentRenameBatchModel.agency_id == agency_id]
    role_value = role.value if isinstance(role, UserRole) else role
    if role_value == UserRole.AGENCY_STAFF.value:
        filters.append(DocumentRenameBatchModel.created_by_user_id == user_id)
    return filters


def rename_batches_query(*, user_id: UUID, role: UserRole | str, agency_id: UUID) -> Select[tuple[DocumentRenameBatchModel]]:
    return select(DocumentRenameBatchModel).where(*rename_batch_filters(user_id=user_id, role=role, agency_id=agency_id))


def rename_items_query(batch_id: UUID, agency_id: UUID) -> Select[tuple[DocumentRenameItemModel]]:
    return select(DocumentRenameItemModel).where(DocumentRenameItemModel.batch_id == batch_id,
        DocumentRenameItemModel.agency_id == agency_id).order_by(DocumentRenameItemModel.renamed_filename.asc())
