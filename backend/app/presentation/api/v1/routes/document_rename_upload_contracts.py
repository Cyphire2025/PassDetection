"""Typed phase inputs and the narrow service seams for rename uploads."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    DocumentRenameBatchModel,
    DocumentRenameItemModel,
    UserModel,
)
from app.infrastructure.documents.document_matcher import ClassifiedDocument, DocumentMatcher
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.security.upload_security import UploadSecurityContext
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.document_chunk_uploads import (
    DocumentChunkMetadata as DocumentChunkMetadata,
)
from app.presentation.api.v1.document_uploads import BoundedDocumentUpload
from app.presentation.api.v1.schemas.document_rename_schemas import RenameDocumentBatchResponse

BatchFilters = Callable[[User, uuid.UUID], list[ColumnElement[bool]]]
BatchResponse = Callable[
    [DocumentRenameBatchModel, list[DocumentRenameItemModel]],
    Awaitable[RenameDocumentBatchResponse],
]


class UploadReader(Protocol):
    def __call__(
        self, files: list[UploadFile], *, security_context: UploadSecurityContext
    ) -> Awaitable[list[BoundedDocumentUpload]]: ...


class DocumentClassifier(Protocol):
    def __call__(
        self,
        matcher: DocumentMatcher,
        jobs: list[tuple[str, bytes, str]],
        *,
        isolate_pdf_parsing: bool,
        batch_timeout_seconds: float | None,
        reject_common_unsupported_format: bool,
    ) -> list[ClassifiedDocument]: ...


class OwnedStorageCleanup(Protocol):
    def __call__(
        self,
        storage: MinioStorageRepository,
        storage_keys: list[str],
        *,
        agency_id: uuid.UUID,
        batch_id: uuid.UUID,
    ) -> Awaitable[None]: ...


class ActiveActorLock(Protocol):
    def __call__(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        agency_id: uuid.UUID,
        expected_role: UserRole,
        current_user: User | None = None,
    ) -> Awaitable[UserModel | User]: ...


@dataclass(frozen=True, slots=True)
class RenamePreparationServices:
    read_uploads: UploadReader
    batch_filters: BatchFilters
    batch_response: BatchResponse


@dataclass(frozen=True, slots=True)
class RenameStorageServices:
    matcher_factory: Callable[[], DocumentMatcher]
    storage_factory: Callable[[], MinioStorageRepository]
    classify: DocumentClassifier
    cleanup: OwnedStorageCleanup


@dataclass(frozen=True, slots=True)
class RenameFinalizationServices:
    lock_actor: ActiveActorLock
    batch_response: BatchResponse
    audit_factory: Callable[[AsyncSession], AuditLogRepository]
    cleanup: OwnedStorageCleanup


@dataclass(frozen=True, slots=True)
class PreparedRenameUpload:
    agency_id: uuid.UUID
    actor_id: uuid.UUID
    expected_actor_role: UserRole
    title: str
    chunk_metadata: DocumentChunkMetadata | None
    uploads: list[BoundedDocumentUpload]
    chunk_byte_count: int
    fingerprint: str | None
    batch_id: uuid.UUID
    existing_batch: DocumentRenameBatchModel | None
    used_names: set[str]


@dataclass(frozen=True, slots=True)
class StagedRenameUpload:
    batch: DocumentRenameBatchModel
    items: list[DocumentRenameItemModel]
    uploaded_keys: list[str]
    storage: MinioStorageRepository
    now: datetime
