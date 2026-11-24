"""Typed batch projection and durable-deletion integration seams."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.models import DocumentRenameBatchModel, StorageCleanupJobModel
from app.infrastructure.documents.storage_cleanup import StorageCleanupResult
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.routes.document_rename_upload_contracts import (
    BatchFilters,
    BatchResponse,
)
from app.presentation.api.v1.schemas.document_rename_schemas import (
    RenameDocumentBatchSummaryResponse,
)


class CleanupStager(Protocol):
    def __call__(
        self,
        session: AsyncSession,
        *,
        agency_id: uuid.UUID,
        source: str,
        context_id: str,
        storage_keys: Sequence[str],
    ) -> tuple[StorageCleanupJobModel, ...]: ...


@dataclass(frozen=True, slots=True)
class RenameBatchServices:
    ensure_allowed: Callable[[User], uuid.UUID]
    batch_filters: BatchFilters
    summary_response: Callable[[DocumentRenameBatchModel], RenameDocumentBatchSummaryResponse]
    batch_response: BatchResponse
    audit_factory: Callable[[AsyncSession], AuditLogRepository]
    stage_cleanup: CleanupStager
    process_cleanup: Callable[[uuid.UUID], Awaitable[StorageCleanupResult | None]]
