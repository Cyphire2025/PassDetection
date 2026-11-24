"""Private rename download resources, captured at route invocation."""

from __future__ import annotations

import threading
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import BinaryIO, Literal, Protocol

from app.domain.entities.entities import User
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes.document_rename_upload_contracts import BatchFilters


class ArchiveSpoolFactory(Protocol):
    def __call__(self, *, max_size: int, mode: Literal["w+b"]) -> BinaryIO: ...


class ArchiveStreamer(Protocol):
    def __call__(self, archive: BinaryIO, *, release_admission: bool) -> AsyncIterator[bytes]: ...


@dataclass(frozen=True, slots=True)
class RenameDownloadServices:
    ensure_allowed: Callable[[User], uuid.UUID]
    batch_filters: BatchFilters
    storage_factory: Callable[[], MinioStorageRepository]
    admission: threading.BoundedSemaphore
    max_uncompressed_bytes: int
    fetch_batch_size: int
    spool_factory: ArchiveSpoolFactory
    fetch_batch: Callable[
        [MinioStorageRepository, list[tuple[uuid.UUID, str, str, str, str]]], Awaitable[list[bytes]]
    ]
    stream_archive: ArchiveStreamer
